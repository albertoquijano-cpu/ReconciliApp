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

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "app": "ReconciliApp"}
