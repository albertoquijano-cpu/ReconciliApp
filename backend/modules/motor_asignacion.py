from sqlalchemy.orm import Session
from itertools import combinations
from backend.models.database import Pedido, PagoPlataforma
from backend.utils.calendario_colombia import calcular_mora
from backend.modules.credenciales import calcular_valor_bruto
from datetime import datetime

TOLERANCIA = 50.0

def obtener_pedidos_pendientes(db: Session, periodo_id: int):
    return db.query(Pedido).filter(
        Pedido.periodo_id == periodo_id,
        Pedido.estado_conciliacion == "pendiente"
    ).all()

def reconstruir_bruto(pago):
    try:
        info = calcular_valor_bruto(pago.plataforma, pago.valor_neto, pago.metodo_pago or "default")
        return info["valor_bruto"]
    except Exception:
        return pago.valor_neto

def buscar_combinacion(pedidos, objetivo, tolerancia=TOLERANCIA):
    valores = [(p, round(p.valor_total, 2)) for p in pedidos]
    for r in range(1, min(len(valores)+1, 15)):
        for combo in combinations(valores, r):
            total = sum(v for _, v in combo)
            if abs(total - objetivo) <= tolerancia:
                return [p for p, _ in combo]
    return None

def asignar_pago(db: Session, pago: PagoPlataforma, pedidos_pendientes: list):
    valor_bruto = reconstruir_bruto(pago)
    pedidos_plataforma = [p for p in pedidos_pendientes if p.plataforma_pago == pago.plataforma]
    if not pedidos_plataforma:
        pedidos_plataforma = pedidos_pendientes
    match = buscar_combinacion(pedidos_plataforma, valor_bruto)
    if match:
        for pedido in match:
            pedido.pago_id = pago.id
            pedido.estado_conciliacion = "pagado"
            pedido.fecha_pago_real = pago.fecha_pago
            pedido.valor_recibido = pedido.valor_total
            if pedido.fecha_pago_esperada and pago.fecha_pago:
                fp = pago.fecha_pago.date() if isinstance(pago.fecha_pago, datetime) else pago.fecha_pago
                fe = pedido.fecha_pago_esperada.date() if isinstance(pedido.fecha_pago_esperada, datetime) else pedido.fecha_pago_esperada
                pedido.dias_mora = max(0, calcular_mora(fe, fp))
        pago.estado_asignacion = "asignado"
        pago.valor_bruto = valor_bruto
        pago.comision_total = round(valor_bruto - pago.valor_neto, 2)
        db.commit()
        return {"asignado": True, "pedidos": [p.numero_pedido for p in match], "valor_bruto": valor_bruto}
    else:
        pago.estado_asignacion = "revision"
        db.commit()
        candidatos = sorted(pedidos_plataforma, key=lambda p: abs(p.valor_total - valor_bruto))[:5]
        return {"asignado": False, "requiere_revision": True,
                "valor_buscado": valor_bruto, "candidatos": [p.numero_pedido for p in candidatos]}

def ejecutar_conciliacion(db: Session, periodo_id: int):
    pagos = db.query(PagoPlataforma).filter(
        PagoPlataforma.periodo_id == periodo_id,
        PagoPlataforma.estado_asignacion == "sin_asignar"
    ).all()
    pendientes = obtener_pedidos_pendientes(db, periodo_id)
    resultados = {"asignados": 0, "revision": 0, "detalles": []}
    for pago in pagos:
        pendientes_actuales = obtener_pedidos_pendientes(db, periodo_id)
        resultado = asignar_pago(db, pago, pendientes_actuales)
        resultados["detalles"].append({"pago_id": pago.id, "plataforma": pago.plataforma, **resultado})
        if resultado["asignado"]:
            resultados["asignados"] += 1
        else:
            resultados["revision"] += 1
    pedidos_finales = obtener_pedidos_pendientes(db, periodo_id)
    resultados["pedidos_aun_pendientes"] = len(pedidos_finales)
    resultados["valor_pendiente"] = sum(p.valor_total for p in pedidos_finales)
    return resultados