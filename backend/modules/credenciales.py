import json, os, base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.orm import Session
from datetime import datetime
from backend.models.database import Credencial

PLATAFORMAS = {
    "shopify":      {"nombre": "Shopify",       "campos": ["url_tienda", "email", "password"], "descripcion": "Portal admin Shopify"},
    "bold":         {"nombre": "Bold",           "campos": ["email", "password"], "descripcion": "Portal Bold Colombia"},
    "wompi":        {"nombre": "Wompi",          "campos": ["email", "password"], "descripcion": "Portal Wompi"},
    "mercadopago":  {"nombre": "Mercado Pago",   "campos": ["email", "password"], "descripcion": "Portal Mercado Pago"},
    "mercadolibre": {"nombre": "Mercado Libre",  "campos": ["email", "password"], "descripcion": "Portal Mercado Libre"},
    "paypal":       {"nombre": "PayPal",         "campos": ["email", "password"], "descripcion": "Portal PayPal Business"},
    "payu":         {"nombre": "PayU",           "campos": ["email", "password"], "descripcion": "Portal PayU Colombia"},
    "addi":         {"nombre": "Addi",           "campos": ["email", "password"], "descripcion": "Portal Addi (30 dias)"},
    "sistecredito": {"nombre": "Sistecredito",   "campos": ["email", "password"], "descripcion": "Portal Sistecredito (45 dias)"},
}

COMISIONES = {
    "impuesto_fijo": 0.01914,
    "bold":         {"visa_debito": 0.0229, "visa_credito": 0.0299, "mastercard_debito": 0.0229, "mastercard_credito": 0.0299, "default": 0.0299},
    "wompi":        {"visa_debito": 0.0199, "visa_credito": 0.0279, "mastercard_debito": 0.0199, "mastercard_credito": 0.0279, "default": 0.0279},
    "mercadopago":  {"visa_credito": 0.0349, "mastercard_credito": 0.0349, "default": 0.0349},
    "mercadolibre": {"default": 0.0349},
    "paypal":       {"default": 0.0399},
    "payu":         {"default": 0.0299},
    "addi":         {"default": 0.0},
    "sistecredito": {"default": 0.0},
    "shopify":      {"default": 0.02},
}

PLAZOS_DIAS = {
    "shopify": 3, "bold": 2, "wompi": 2, "mercadopago": 2,
    "mercadolibre": 2, "paypal": 1, "payu": 2,
    "addi": 30, "sistecredito": 45,
    "transferencia": 0, "tarjeta_directa": 1,
}

# Mapeo de nombres del Excel a claves internas
MAPEO_NOMBRES = {
    "wompi": "wompi", "bold": "bold", "addi": "addi",
    "sistecredito": "sistecredito", "shopify": "shopify",
    "mercadopago": "mercadopago", "mercado pago": "mercadopago",
    "mercadolibre": "mercadolibre", "mercado libre": "mercadolibre",
    "paypal": "paypal", "payu": "payu", "pay u": "payu",
}

SALT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", ".salt")

def _obtener_o_crear_salt():
    os.makedirs(os.path.dirname(SALT_PATH), exist_ok=True)
    if os.path.exists(SALT_PATH):
        with open(SALT_PATH, "rb") as f:
            return f.read()
    salt = os.urandom(16)
    with open(SALT_PATH, "wb") as f:
        f.write(salt)
    return salt

def _derivar_clave(password):
    salt = _obtener_o_crear_salt()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return Fernet(key)

def guardar_credencial(db, plataforma, datos, password_master):
    if plataforma not in PLATAFORMAS:
        raise ValueError(f"Plataforma '{plataforma}' no reconocida.")
    f = _derivar_clave(password_master)
    datos_cifrados = f.encrypt(json.dumps(datos).encode()).decode()
    cred = db.query(Credencial).filter_by(plataforma=plataforma).first()
    if cred:
        cred.datos_cifrados = datos_cifrados
        cred.actualizada_en = datetime.now()
    else:
        cred = Credencial(plataforma=plataforma, datos_cifrados=datos_cifrados)
        db.add(cred)
    db.commit()
    return True

def obtener_credencial(db, plataforma, password_master):
    cred = db.query(Credencial).filter_by(plataforma=plataforma, activa=True).first()
    if not cred:
        raise ValueError(f"No hay credenciales para '{plataforma}'.")
    f = _derivar_clave(password_master)
    return json.loads(f.decrypt(cred.datos_cifrados.encode()))

def listar_plataformas_configuradas(db):
    configuradas = {c.plataforma: c.ultima_sync for c in db.query(Credencial).filter_by(activa=True).all()}
    return [{"plataforma": k, "nombre": v["nombre"], "descripcion": v["descripcion"],
             "campos": v["campos"], "configurada": k in configuradas,
             "ultima_sync": configuradas.get(k)} for k, v in PLATAFORMAS.items()]

def calcular_valor_bruto(plataforma, valor_neto, metodo_pago="default"):
    comisiones_plataforma = COMISIONES.get(plataforma, {"default": 0.0})
    tasa_plataforma = comisiones_plataforma.get(metodo_pago, comisiones_plataforma["default"])
    tasa_total = tasa_plataforma + COMISIONES["impuesto_fijo"]
    valor_bruto = valor_neto / (1 - tasa_total)
    comision = valor_bruto - valor_neto
    return {"valor_neto": round(valor_neto, 2), "valor_bruto": round(valor_bruto, 2),
            "comision_total": round(comision, 2), "tasa_plataforma": round(tasa_plataforma * 100, 4),
            "tasa_impuesto": round(COMISIONES["impuesto_fijo"] * 100, 4), "tasa_total": round(tasa_total * 100, 4)}

def cargar_credenciales_excel(db, ruta_excel, password_master):
    import openpyxl
    wb = openpyxl.load_workbook(ruta_excel)
    ws = wb.active
    guardadas = []
    errores = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        nombre_plat = str(row[0]).strip().lower()
        email = str(row[1]).strip() if row[1] else ""
        password = str(row[2]).strip() if row[2] else ""
        plataforma = MAPEO_NOMBRES.get(nombre_plat)
        if not plataforma:
            errores.append(f"Plataforma '{row[0]}' no reconocida - omitida")
            continue
        try:
            datos = {"email": email, "password": password}
            guardar_credencial(db, plataforma, datos, password_master)
            guardadas.append(plataforma)
        except Exception as e:
            errores.append(f"{row[0]}: {str(e)}")
    return guardadas, errores
