import anthropic, base64, json, re, os
from datetime import datetime
from pathlib import Path

def imagen_a_base64(ruta_imagen: str) -> tuple:
    ext = Path(ruta_imagen).suffix.lower()
    tipos = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = tipos.get(ext, "image/jpeg")
    with open(ruta_imagen, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, media_type

def analizar_extracto_con_ia(ruta_imagen: str, api_key: str = None, fecha_inicio: str = "", fecha_corte: str = "", fuente: str = "bancolombia") -> list:
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("Falta ANTHROPIC_API_KEY en .env o como parametro")
    cliente = anthropic.Anthropic(api_key=api_key)
    img_data, media_type = imagen_a_base64(ruta_imagen)
    prompt = f"Analiza este extracto bancario de {fuente} y extrae SOLO los movimientos de INGRESO entre {fecha_inicio} y {fecha_corte}. Responde UNICAMENTE con un JSON array con campos: fecha (DD/MM/YYYY), descripcion, valor, origen. Si no hay movimientos responde []"
    respuesta = cliente.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}},
            {"type": "text", "text": prompt}
        ]}]
    )
    texto = re.sub(r"```json|```", "", respuesta.content[0].text.strip()).strip()
    movimientos = json.loads(texto)
    resultado = []
    for m in movimientos:
        try:
            resultado.append({"fecha": datetime.strptime(m["fecha"], "%d/%m/%Y"), "descripcion": m.get("descripcion", ""), "valor": float(m.get("valor", 0)), "origen": m.get("origen", fuente)})
        except:
            continue
    return resultado
