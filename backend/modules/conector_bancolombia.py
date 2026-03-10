import os, re
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models.database import PagoPlataforma

COLUMNAS_BANCOLOMBIA = {
    "fecha": ["Fecha", "FECHA", "Fecha Transaccion"],
    "descripcion": ["Descripcion", "DESCRIPCION", "Concepto"],
    "referencia": ["Referencia", "REFERENCIA", "No. Comprobante"],
    "debito": ["Debito", "DEBITO", "Retiro"],
    "credito": ["Credito", "CREDITO", "Deposito", "Abono"],
    "saldo": ["Saldo", "SALDO"],
}

ORIGEN_KEYWORDS = {
    "shopify": ["shopify", "stripe"],
    "bold": ["bold"],
    "wompi": ["wompi"],
    "mercadopago": ["mercado pago", "mercadopago"],
    "paypal": ["paypal"],
    "addi": ["addi"],
    "sistecredito": ["sistecredito"],
    "nequi": ["nequi"],
    "qr": ["qr", "codigo qr"],
    "pse": ["pse", "ach"],
    "tarjeta": ["credibanco", "redeban", "visa", "mastercard"],
    "transferencia": ["transferencia", "trf"],
    "consignacion": ["consignacion"],
}

def limpiar_valor(txt):
    if not txt: return 0.0
    l = re.sub(r"[^\d,.]", "", str(txt).strip())
    if "," in l and "." in l: l = l.replace(".","").replace(",",".")
    elif "," in l: l = l.replace(",",".")
    try: return float(l)
    except: return 0.0

def parsear_fecha(txt):
    if not txt: return None
    for fmt in ["%d/%m/%Y","%Y-%m-%d","%d-%m-%Y","%Y/%m/%d"]:
        try: return datetime.strptime(str(txt).strip()[:10], fmt)
        except: continue
    return None

def identificar_origen(desc):
    if not desc: return "bancolombia"
    d = desc.lower()
    for origen, kws in ORIGEN_KEYWORDS.items():
        for kw in kws:
            if kw in d: return origen
    return "bancolombia"

def encontrar_col(headers, opciones):
    for h in headers:
        for op in opciones:
            if op.lower() == h.lower().strip(): return h
    return None

def parsear_extracto_bancolombia(ruta):
    import csv
    from io import StringIO
    contenido = None
    for enc in ["utf-8-sig","latin-1","cp1252"]:
        try:
            with open(ruta, encoding=enc) as f: lines = f.readlines()
            contenido = lines
            break
        except: continue
    if not contenido: return []
    header_row = 0
    for i, line in enumerate(contenido):
        if any(c.lower() in line.lower() for c in ["fecha","debito","credito"]):
            header_row = i
            break
    reader = csv.DictReader(StringIO("".join(contenido[header_row:])))
    headers = reader.fieldnames or []
    col_f = encontrar_col(headers, COLUMNAS_BANCOLOMBIA["fecha"])
    col_d = encontrar_col(headers, COLUMNAS_BANCOLOMBIA["descripcion"])
    col_r = encontrar_col(headers, COLUMNAS_BANCOLOMBIA["referencia"])
    col_c = encontrar_col(headers, COLUMNAS_BANCOLOMBIA["credito"])
    movs = []
    for row in reader:
        val = limpiar_valor(row.get(col_c, 0)) if col_c else 0
        if val <= 0: continue
        desc = row.get(col_d, "") if col_d else ""
        movs.append({
            "fecha": parsear_fecha(row.get(col_f,"")) if col_f else None,
            "descripcion": desc,
            "referencia": row.get(col_r,"") if col_r else "",
            "valor": val,
            "origen": identificar_origen(desc),
        })
    return movs

def guardar_extracto_en_bd(db, periodo_id, movimientos):
    guardados = 0
    for m in movimientos:
        db.add(PagoPlataforma(
            periodo_id=periodo_id,
            plataforma=m["origen"],
            fecha_pago=m["fecha"],
            valor_neto=m["valor"],
            valor_bruto=m["valor"],
            referencia=m["referencia"],
            descripcion=m["descripcion"],
            metodo_pago=m["origen"],
            estado_asignacion="sin_asignar",
        ))
        guardados += 1
    db.commit()
    return guardados