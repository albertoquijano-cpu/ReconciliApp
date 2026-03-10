import anthropic, base64, json, re
from datetime import datetime
from pathlib import Path

def imagen_a_base64(ruta_imagen: str) -> tuple:
    ext = Path(ruta_imagen).suffix.lower()
    tipos = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = tipos.get(ext, "image/jpeg")
    with open(ruta_imagen, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, media_type

def analizar_extracto_con_ia(ruta_imagen: str, api_key: str, fecha_inicio: str, fecha_corte: str, fuente: str = "bancolombia") -> list:
    cliente = anthropic.Anthropic(api_key=api_key)
    img_data, media_type = imagen_a_base64(ruta_imagen)
    prompt = f"""Analiza este extracto bancario de {fuente} y extrae SOLO los movimientos de INGRESO (abonos, creditos, depositos) entre {fecha_inicio} y {fecha_corte}.

Responde UNICAMENTE con un JSON array con este formato exacto, sin texto adicional:
[
  {{
    "fecha": "DD/MM/YYYY",
    "descripcion": "descripcion del movimiento",
    "referencia": "numero de referencia o vacio",
    "valor": 123456.00,
    "origen": "bold|wompi|shopify|mercadopago|paypal|addi|sistecredito|nequi|qr|pse|tarjeta|transferencia|consignacion|bancolombia"
  }}
]

Reglas:
- Solo incluir ingresos (valores positivos que entran a la cuenta)
- Ignorar debitos, retiros, cargos
- El campo origen debe identificar de donde viene el pago segun la descripcion
- Si no hay movimientos en el rango de fechas, retorna array vacio []
- El valor debe ser numerico sin simbolos
"""
    mensaje = cliente.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}},
                {"type": "text", "text": prompt}
            ]
        }]
    )
    respuesta = mensaje.content[0].text.strip()
    # Limpiar posibles markdown
    respuesta = re.sub(r"^$", "", respuesta).strip()
    try:
        movimientos = json.loads(respuesta)
        # Normalizar fechas
        for m in movimientos:
            if isinstance(m.get("fecha"), str):
                for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]:
                    try:
                        m["fecha"] = datetime.strptime(m["fecha"], fmt)
                        break
                    except: continue
        return movimientos
    except json.JSONDecodeError as e:
        msg = "Claude no retorno JSON valido: " + str(e) + " Respuesta: " + respuesta
        raise ValueError(msg)