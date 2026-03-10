from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from sqlalchemy.orm import Session

from backend.models.database import crear_tablas, get_db, Periodo, Pedido, PagoPlataforma
from backend.modules.credenciales import (
    guardar_credencial, obtener_credencial, listar_plataformas_configuradas, calcular_valor_bruto
)
from backend.modules.conector_shopify import sincronizar_shopify
from backend.utils.calendario_colombia import calcular_fecha_pago_esperada, calcular_mora


crear_tablas()
app = FastAPI(title="ReconciliApp", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class CredencialInput(BaseModel):
    plataforma: str
    datos: dict
    password_master: str

class PeriodoInput(BaseModel):
    fecha_inicio: date
    fecha_corte: date
    descripcion: Optional[str] = None

class SyncShopifyInput(BaseModel):
    periodo_id: int
    password_master: str
    headless: bool = True

class ComisionInput(BaseModel):
    plataforma: str
    valor_neto: float
    metodo_pago: str = "default"

@app.get("/api/plataformas")
def listar_plataformas(db: Session = Depends(get_db)):
    return listar_plataformas_configuradas(db)

@app.post("/api/credenciales")
def guardar_cred(body: CredencialInput, db: Session = Depends(get_db)):
    try:
        guardar_credencial(db, body.plataforma, body.datos, body.password_master)
        return {"ok": True, "mensaje": f"Credenciales de {body.plataforma} guardadas."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/periodos")
def crear_periodo(body: PeriodoInput, db: Session = Depends(get_db)):
    periodo = Periodo(
        fecha_inicio=datetime.combine(body.fecha_inicio, datetime.min.time()),
        fecha_corte=datetime.combine(body.fecha_corte, datetime.min.time()),
        descripcion=body.descripcion or f"Conciliacion {body.fecha_inicio} a {body.fecha_corte}",
    )
    db.add(periodo)
    db.commit()
    db.refresh(periodo)
    return {"id": periodo.id, "fecha_inicio": periodo.fecha_inicio.date().isoformat(),
            "fecha_corte": periodo.fecha_corte.date().isoformat(), "descripcion": periodo.descripcion}

@app.get("/api/periodos")
def listar_periodos(db: Session = Depends(get_db)):
    periodos = db.query(Periodo).order_by(Periodo.fecha_inicio.desc()).all()
    return [{"id": p.id, "fecha_inicio": p.fecha_inicio.date().isoformat(),
             "fecha_corte": p.fecha_corte.date().isoformat(), "descripcion": p.descripcion} for p in periodos]

@app.get("/api/periodos/{periodo_id}/resumen")
def resumen_periodo(periodo_id: int, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    pedidos = db.query(Pedido).filter_by(periodo_id=periodo_id).all()
    pagos = db.query(PagoPlataforma).filter_by(periodo_id=periodo_id).all()
    pagados = [p for p in pedidos if p.estado_conciliacion == "pagado"]
    pendientes = [p for p in pedidos if p.estado_conciliacion == "pendiente"]
    mora = [p for p in pedidos if p.dias_mora and p.dias_mora > 0]
    return {
        "periodo": {"id": periodo.id, "fecha_inicio": periodo.fecha_inicio.date().isoformat(),
                    "fecha_corte": periodo.fecha_corte.date().isoformat()},
        "pedidos": {"total": len(pedidos), "valor_total": sum(p.valor_total for p in pedidos),
                    "pagados": len(pagados), "valor_pagado": sum(p.valor_total for p in pagados),
                    "pendientes": len(pendientes), "valor_pendiente": sum(p.valor_total for p in pendientes),
                    "en_mora": len(mora)},
        "pagos_plataforma": {"total_pagos": len(pagos), "valor_total_neto": sum(p.valor_neto for p in pagos),
                             "sin_asignar": len([p for p in pagos if p.estado_asignacion == "sin_asignar"])}
    }

@app.post("/api/sync/shopify")
async def sync_shopify(body: SyncShopifyInput, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=body.periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    try:
        credenciales = obtener_credencial(db, "shopify", body.password_master)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="reconcili_shopify_")
    resultado = await sincronizar_shopify(credenciales, periodo.fecha_inicio.date(),
                                          periodo.fecha_corte.date(), carpeta, body.headless)
    if not resultado["ok"]:
        raise HTTPException(status_code=500, detail=resultado["error"])
    guardados = 0
    for p in resultado["pedidos"]:
        fecha_esperada = None
        if p["fecha_pedido"] and p["plataforma_pago"]:
            fecha_esperada = calcular_fecha_pago_esperada(
                p["fecha_pedido"].date() if isinstance(p["fecha_pedido"], datetime) else p["fecha_pedido"],
                p["plataforma_pago"])
        dias_mora = 0
        if fecha_esperada and p.get("fecha_pago_real"):
            dias_mora = max(0, calcular_mora(fecha_esperada,
                p["fecha_pago_real"].date() if isinstance(p["fecha_pago_real"], datetime) else p["fecha_pago_real"]))
        db.add(Pedido(periodo_id=body.periodo_id, numero_pedido=p["numero_pedido"],
                      cliente_nombre=p["cliente_nombre"], cliente_email=p["cliente_email"],
                      fecha_pedido=p["fecha_pedido"], valor_total=p["valor_total"],
                      plataforma_pago=p["plataforma_pago"], estado_shopify=p["estado_shopify"],
                      estado_conciliacion=p["estado_conciliacion"], fecha_pago_real=p.get("fecha_pago_real"),
                      fecha_pago_esperada=datetime.combine(fecha_esperada, datetime.min.time()) if fecha_esperada else None,
                      dias_mora=dias_mora))
        guardados += 1
    db.commit()
    return {"ok": True, "pedidos_descargados": resultado["total_pedidos"],
            "pedidos_guardados": guardados, "valor_total": resultado["total_valor"]}

@app.post("/api/calcular-comision")
def calcular_comision(body: ComisionInput):
    try:
        return calcular_valor_bruto(body.plataforma, body.valor_neto, body.metodo_pago)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


from backend.modules.conector_bold import sincronizar_bold
from backend.modules.conector_wompi import sincronizar_wompi
from backend.modules.conector_mercadopago import sincronizar_mercadopago

class SyncPlataformaInput(BaseModel):
    periodo_id: int
    password_master: str
    headless: bool = True

@app.post("/api/sync/bold")
async def sync_bold(body: SyncPlataformaInput, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=body.periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    try:
        credenciales = obtener_credencial(db, "bold", body.password_master)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="reconcili_bold_")
    resultado = await sincronizar_bold(credenciales, periodo.fecha_inicio.date(),
                                       periodo.fecha_corte.date(), carpeta, body.headless)
    if not resultado["ok"]:
        raise HTTPException(status_code=500, detail=resultado["error"])
    guardados = 0
    for p in resultado["pagos"]:
        db.add(PagoPlataforma(periodo_id=body.periodo_id, plataforma="bold",
                              fecha_pago=p["fecha_pago"], valor_neto=p["valor_neto"],
                              referencia=p["referencia"], metodo_pago=p["metodo_pago"],
                              descripcion=p["descripcion"]))
        guardados += 1
    db.commit()
    return {"ok": True, "pagos_guardados": guardados, "total_neto": resultado["total_neto"]}

@app.post("/api/sync/wompi")
async def sync_wompi(body: SyncPlataformaInput, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=body.periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    try:
        credenciales = obtener_credencial(db, "wompi", body.password_master)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="reconcili_wompi_")
    resultado = await sincronizar_wompi(credenciales, periodo.fecha_inicio.date(),
                                        periodo.fecha_corte.date(), carpeta, body.headless)
    if not resultado["ok"]:
        raise HTTPException(status_code=500, detail=resultado["error"])
    guardados = 0
    for p in resultado["pagos"]:
        db.add(PagoPlataforma(periodo_id=body.periodo_id, plataforma="wompi",
                              fecha_pago=p["fecha_pago"], valor_neto=p["valor_neto"],
                              referencia=p["referencia"], metodo_pago=p["metodo_pago"],
                              descripcion=p["descripcion"]))
        guardados += 1
    db.commit()
    return {"ok": True, "pagos_guardados": guardados, "total_neto": resultado["total_neto"]}

@app.post("/api/sync/mercadopago")
async def sync_mercadopago(body: SyncPlataformaInput, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=body.periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    try:
        credenciales = obtener_credencial(db, "mercadopago", body.password_master)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="reconcili_mp_")
    resultado = await sincronizar_mercadopago(credenciales, periodo.fecha_inicio.date(),
                                              periodo.fecha_corte.date(), carpeta, body.headless)
    if not resultado["ok"]:
        raise HTTPException(status_code=500, detail=resultado["error"])
    guardados = 0
    for p in resultado["pagos"]:
        db.add(PagoPlataforma(periodo_id=body.periodo_id, plataforma="mercadopago",
                              fecha_pago=p["fecha_pago"], valor_neto=p["valor_neto"],
                              referencia=p["referencia"], metodo_pago=p["metodo_pago"],
                              descripcion=p["descripcion"]))
        guardados += 1
    db.commit()
    return {"ok": True, "pagos_guardados": guardados, "total_neto": resultado["total_neto"]}

from backend.modules.conector_paypal import sincronizar_paypal
from backend.modules.conector_addi import sincronizar_addi
from backend.modules.conector_sistecredito import sincronizar_sistecredito

@app.post("/api/sync/paypal")
async def sync_paypal(body: SyncPlataformaInput, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=body.periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    try:
        credenciales = obtener_credencial(db, "paypal", body.password_master)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="reconcili_paypal_")
    resultado = await sincronizar_paypal(credenciales, periodo.fecha_inicio.date(),
                                         periodo.fecha_corte.date(), carpeta, body.headless)
    if not resultado["ok"]:
        raise HTTPException(status_code=500, detail=resultado["error"])
    guardados = 0
    for p in resultado["pagos"]:
        db.add(PagoPlataforma(periodo_id=body.periodo_id, plataforma="paypal",
                              fecha_pago=p["fecha_pago"], valor_neto=p["valor_neto"],
                              referencia=p["referencia"], metodo_pago=p["metodo_pago"],
                              descripcion=p["descripcion"]))
        guardados += 1
    db.commit()
    return {"ok": True, "pagos_guardados": guardados, "total_neto": resultado["total_neto"]}

@app.post("/api/sync/addi")
async def sync_addi(body: SyncPlataformaInput, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=body.periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    try:
        credenciales = obtener_credencial(db, "addi", body.password_master)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="reconcili_addi_")
    resultado = await sincronizar_addi(credenciales, periodo.fecha_inicio.date(),
                                       periodo.fecha_corte.date(), carpeta, body.headless)
    if not resultado["ok"]:
        raise HTTPException(status_code=500, detail=resultado["error"])
    guardados = 0
    for p in resultado["pagos"]:
        db.add(PagoPlataforma(periodo_id=body.periodo_id, plataforma="addi",
                              fecha_pago=p["fecha_pago"], valor_neto=p["valor_neto"],
                              referencia=p["referencia"], metodo_pago=p["metodo_pago"],
                              descripcion=p["descripcion"]))
        guardados += 1
    db.commit()
    return {"ok": True, "pagos_guardados": guardados, "total_neto": resultado["total_neto"]}

@app.post("/api/sync/sistecredito")
async def sync_sistecredito(body: SyncPlataformaInput, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=body.periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    try:
        credenciales = obtener_credencial(db, "sistecredito", body.password_master)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="reconcili_sistecredito_")
    resultado = await sincronizar_sistecredito(credenciales, periodo.fecha_inicio.date(),
                                               periodo.fecha_corte.date(), carpeta, body.headless)
    if not resultado["ok"]:
        raise HTTPException(status_code=500, detail=resultado["error"])
    guardados = 0
    for p in resultado["pagos"]:
        db.add(PagoPlataforma(periodo_id=body.periodo_id, plataforma="sistecredito",
                              fecha_pago=p["fecha_pago"], valor_neto=p["valor_neto"],
                              referencia=p["referencia"], metodo_pago=p["metodo_pago"],
                              descripcion=p["descripcion"]))
        guardados += 1
    db.commit()
    return {"ok": True, "pagos_guardados": guardados, "total_neto": resultado["total_neto"]}

from backend.modules.motor_asignacion import ejecutar_conciliacion, asignar_pago

class AsignacionManualInput(BaseModel):
    pago_id: int
    pedido_ids: list[int]

@app.post("/api/conciliar/{periodo_id}")
def conciliar_periodo(periodo_id: int, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    resultado = ejecutar_conciliacion(db, periodo_id)
    return resultado

@app.post("/api/asignar-manual")
def asignar_manual(body: AsignacionManualInput, db: Session = Depends(get_db)):
    pago = db.query(PagoPlataforma).filter_by(id=body.pago_id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    from backend.models.database import Pedido
    from backend.utils.calendario_colombia import calcular_mora
    from datetime import datetime
    for pedido_id in body.pedido_ids:
        pedido = db.query(Pedido).filter_by(id=pedido_id).first()
        if pedido:
            pedido.pago_id = pago.id
            pedido.estado_conciliacion = "pagado"
            pedido.fecha_pago_real = pago.fecha_pago
            if pedido.fecha_pago_esperada and pago.fecha_pago:
                fp = pago.fecha_pago.date() if isinstance(pago.fecha_pago, datetime) else pago.fecha_pago
                fe = pedido.fecha_pago_esperada.date() if isinstance(pedido.fecha_pago_esperada, datetime) else pedido.fecha_pago_esperada
                pedido.dias_mora = max(0, calcular_mora(fe, fp))
    pago.estado_asignacion = "asignado"
    db.commit()
    return {"ok": True, "pedidos_asignados": len(body.pedido_ids)}

@app.get("/api/pagos-sin-asignar/{periodo_id}")
def pagos_sin_asignar(periodo_id: int, db: Session = Depends(get_db)):
    pagos = db.query(PagoPlataforma).filter(
        PagoPlataforma.periodo_id == periodo_id,
        PagoPlataforma.estado_asignacion == "sin_asignar"
    ).all()
    return [{"id": p.id, "plataforma": p.plataforma, "fecha": p.fecha_pago,
             "valor_neto": p.valor_neto, "referencia": p.referencia} for p in pagos]

from backend.modules.generador_reportes import generar_reportes_excel
from fastapi.responses import FileResponse

@app.get("/api/reportes/{periodo_id}")
def generar_reporte(periodo_id: int, db: Session = Depends(get_db)):
    periodo = db.query(Periodo).filter_by(id=periodo_id).first()
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    try:
        import os
        carpeta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports")
        ruta = generar_reportes_excel(db, periodo_id, carpeta)
        return FileResponse(ruta, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename=os.path.basename(ruta))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.responses import HTMLResponse
import os as _os

@app.get("/", response_class=HTMLResponse)
def dashboard():
    fp = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "frontend", "index.html")
    with open(fp, encoding="utf-8") as f:
        return f.read()

from backend.modules.conector_bancolombia import parsear_extracto_bancolombia, guardar_extracto_en_bd
from fastapi import UploadFile, File, Form
import tempfile, shutil

@app.post("/api/banco/cargar-extracto")
async def cargar_extracto(
    periodo_id: int = Form(...),
    archivo: UploadFile = File(...)
):
    db_gen = get_db()
    db = next(db_gen)
    try:
        periodo = db.query(Periodo).filter_by(id=periodo_id).first()
        if not periodo:
            raise HTTPException(status_code=404, detail="Periodo no encontrado")
        tmp = tempfile.mkdtemp()
        ruta = os.path.join(tmp, archivo.filename)
        with open(ruta, "wb") as f:
            shutil.copyfileobj(archivo.file, f)
        movimientos = parsear_extracto_bancolombia(ruta)
        if not movimientos:
            raise HTTPException(status_code=400, detail="No se encontraron ingresos en el extracto. Verifica el formato CSV.")
        guardados = guardar_extracto_en_bd(db, periodo_id, movimientos)
        resumen = {}
        for m in movimientos:
            resumen[m["origen"]] = resumen.get(m["origen"], 0) + 1
        return {"ok": True, "total_movimientos": guardados, "por_origen": resumen,
                "total_valor": sum(m["valor"] for m in movimientos)}
    finally:
        db_gen.close()

from backend.modules.vision_extracto import analizar_extracto_con_ia
from backend.modules.conector_bancolombia import guardar_extracto_en_bd

@app.post("/api/banco/cargar-foto")
async def cargar_foto_extracto(
    periodo_id: int = Form(...),
    fuente: str = Form(...),
    api_key_claude: str = Form(...),
    archivo: UploadFile = File(...)
):
    db_gen = get_db()
    db = next(db_gen)
    try:
        periodo = db.query(Periodo).filter_by(id=periodo_id).first()
        if not periodo:
            raise HTTPException(status_code=404, detail="Periodo no encontrado")
        tmp = tempfile.mkdtemp()
        ruta = os.path.join(tmp, archivo.filename)
        with open(ruta, "wb") as f:
            shutil.copyfileobj(archivo.file, f)
        fecha_ini = periodo.fecha_inicio.strftime("%d/%m/%Y")
        fecha_fin = periodo.fecha_corte.strftime("%d/%m/%Y")
        movimientos = analizar_extracto_con_ia(ruta, api_key_claude, fecha_ini, fecha_fin, fuente)
        if not movimientos:
            return {"ok": True, "total_movimientos": 0, "mensaje": "No se encontraron ingresos en el periodo indicado"}
        guardados = guardar_extracto_en_bd(db, periodo_id, movimientos)
        resumen = {}
        for m in movimientos:
            origen = m.get("origen", "desconocido")
            resumen[origen] = resumen.get(origen, 0) + 1
        return {"ok": True, "total_movimientos": guardados,
                "total_valor": sum(m["valor"] for m in movimientos),
                "por_origen": resumen}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_gen.close()

from backend.modules.vision_extracto import analizar_extracto_con_ia
from backend.modules.conector_bancolombia import guardar_extracto_en_bd

@app.post("/api/banco/cargar-foto")
async def cargar_foto_extracto(
    periodo_id: int = Form(...),
    fuente: str = Form(...),
    api_key_claude: str = Form(...),
    archivo: UploadFile = File(...)
):
    db_gen = get_db()
    db = next(db_gen)
    try:
        periodo = db.query(Periodo).filter_by(id=periodo_id).first()
        if not periodo:
            raise HTTPException(status_code=404, detail="Periodo no encontrado")
        tmp = tempfile.mkdtemp()
        ruta = os.path.join(tmp, archivo.filename)
        with open(ruta, "wb") as f:
            shutil.copyfileobj(archivo.file, f)
        fecha_ini = periodo.fecha_inicio.strftime("%d/%m/%Y")
        fecha_fin = periodo.fecha_corte.strftime("%d/%m/%Y")
        movimientos = analizar_extracto_con_ia(ruta, api_key_claude, fecha_ini, fecha_fin, fuente)
        if not movimientos:
            return {"ok": True, "total_movimientos": 0, "mensaje": "No se encontraron ingresos en el periodo indicado"}
        guardados = guardar_extracto_en_bd(db, periodo_id, movimientos)
        resumen = {}
        for m in movimientos:
            origen = m.get("origen", "desconocido")
            resumen[origen] = resumen.get(origen, 0) + 1
        return {"ok": True, "total_movimientos": guardados,
                "total_valor": sum(m["valor"] for m in movimientos),
                "por_origen": resumen}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_gen.close()

from backend.modules.cargador_cxc import cargar_cxc_excel

@app.post("/api/cxc/cargar-inicial")
async def cargar_cxc_inicial(
    periodo_id: int = Form(...),
    archivo: UploadFile = File(...)
):
    db_gen = get_db()
    db = next(db_gen)
    try:
        periodo = db.query(Periodo).filter_by(id=periodo_id).first()
        if not periodo:
            raise HTTPException(status_code=404, detail="Periodo no encontrado")
        tmp = tempfile.mkdtemp()
        ruta = os.path.join(tmp, archivo.filename)
        with open(ruta, "wb") as f:
            shutil.copyfileobj(archivo.file, f)
        guardados, errores = cargar_cxc_excel(ruta, periodo_id, db)
        return {"ok": True, "guardados": guardados, "errores": errores, "total_errores": len(errores)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_gen.close()
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "app": "ReconciliApp"}
