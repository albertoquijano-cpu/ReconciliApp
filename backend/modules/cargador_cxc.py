import openpyxl, re
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend.models.database import Pedido
from backend.utils.calendario_colombia import calcular_fecha_pago_esperada

PLAZOS_DIAS = {
    "shopify": 3, "bold": 2, "wompi": 2,
    "mercadopago": 2, "paypal": 1,
    "addi": 30, "sistecredito": 45,
}

def normalizar_columnas(headers):
    mapa = {}
    for i, h in enumerate(headers):
        if not h: continue
        h2 = str(h).lower().strip()
        if any(x in h2 for x in ["numero","pedido","order","ms-","#"]): mapa["numero"] = i
        elif any(x in h2 for x in ["cliente","nombre","customer"]): mapa["cliente"] = i
        elif any(x in h2 for x in ["email","correo"]): mapa["email"] = i
        elif any(x in h2 for x in ["fecha_pedido","fecha pedido","order date","fecha_orden"]): mapa["fecha_pedido"] = i
        elif any(x in h2 for x in ["fecha_acordada","fecha acordada","fecha_pago","fecha pago esperada","vencimiento"]): mapa["fecha_acordada"] = i
        elif any(x in h2 for x in ["valor","total","amount","monto"]): mapa["valor"] = i
        elif any(x in h2 for x in ["plataforma","medio","metodo","payment"]): mapa["plataforma"] = i
    return mapa

def limpiar_valor(v):
    if v is None: return 0.0
    s = re.sub(r"[^\d,.]", "", str(v).strip())
    if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
    elif "," in s: s = s.replace(",", ".")
    try: return float(s)
    except: return 0.0

def parsear_fecha(v):
    if not v: return None
    if isinstance(v, datetime): return v
    for fmt in ["%d/%m/%Y","%Y-%m-%d","%d-%m-%Y","%d/%m/%Y %H:%M:%S","%Y/%m/%d"]:
        try: return datetime.strptime(str(v).strip()[:10], fmt)
        except: continue
    return None

def calcular_fecha_acordada(fecha_pedido, plataforma):
    if not fecha_pedido: return None
    dias = PLAZOS_DIAS.get(plataforma.lower() if plataforma else "", 3)
    # Suma dias habiles simples si es menos de 7, calendario si es mas
    if dias <= 7:
        fecha = fecha_pedido
        habiles = 0
        while habiles < dias:
            fecha = fecha + timedelta(days=1)
            if fecha.weekday() < 5:
                habiles += 1
        return fecha
    else:
        return fecha_pedido + timedelta(days=dias)

def cargar_cxc_excel(ruta: str, periodo_id: int, db: Session):
    wb = openpyxl.load_workbook(ruta, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows: return 0, []
    # Buscar fila de headers
    header_row = 0
    for i, row in enumerate(rows):
        if any(str(c or "").lower() in ["numero pedido","numero","pedido","order"] for c in row):
            header_row = i
            break
    headers = rows[header_row]
    mapa = normalizar_columnas(headers)
    if "numero" not in mapa or "valor" not in mapa:
        raise ValueError("No se encontraron columnas requeridas: numero pedido y valor")
    guardados = 0
    errores = []
    for row in rows[header_row+1:]:
        if not any(row): continue
        numero = str(row[mapa["numero"]] or "").strip()
        if not numero or not numero.upper().startswith("MS"): continue
        valor = limpiar_valor(row[mapa.get("valor", 0)])
        if valor <= 0: continue
        fecha_pedido = parsear_fecha(row[mapa["fecha_pedido"]]) if "fecha_pedido" in mapa else None
        plataforma = str(row[mapa["plataforma"]] or "shopify").strip().lower() if "plataforma" in mapa else "shopify"
        # Fecha acordada: usar la del Excel si existe, sino calcular
        if "fecha_acordada" in mapa and row[mapa["fecha_acordada"]]:
            fecha_acordada = parsear_fecha(row[mapa["fecha_acordada"]])
        else:
            fecha_acordada = calcular_fecha_acordada(fecha_pedido, plataforma)
        cliente = str(row[mapa["cliente"]] or "") if "cliente" in mapa else ""
        email = str(row[mapa["email"]] or "") if "email" in mapa else ""
        # Evitar duplicados
        existe = db.query(Pedido).filter_by(numero_pedido=numero, periodo_id=periodo_id).first()
        if existe:
            errores.append(numero + " ya existe")
            continue
        db.add(Pedido(
            periodo_id=periodo_id,
            numero_pedido=numero,
            cliente_nombre=cliente,
            cliente_email=email,
            fecha_pedido=fecha_pedido,
            fecha_pago_esperada=fecha_acordada,
            valor_total=valor,
            plataforma_pago=plataforma,
            estado_conciliacion="pendiente",
            es_pendiente_inicial=True,
        ))
        guardados += 1
    db.commit()
    return guardados, errores