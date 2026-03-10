import asyncio, os, re
from datetime import datetime, date
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

SHOPIFY_PLATAFORMAS_PAGO = {
    "bold": "bold", "wompi": "wompi", "mercado pago": "mercadopago",
    "mercadopago": "mercadopago", "paypal": "paypal", "addi": "addi",
    "sistecredito": "sistecredito", "shopify payments": "shopify",
    "transferencia": "transferencia", "efectivo": "efectivo",
}

def normalizar_plataforma(gateway):
    if not gateway:
        return "desconocido"
    g = gateway.lower().strip()
    for key, val in SHOPIFY_PLATAFORMAS_PAGO.items():
        if key in g:
            return val
    return g

def limpiar_valor(texto):
    if not texto:
        return 0.0
    limpio = re.sub(r"[^\d.,]", "", texto)
    if "," in limpio and "." in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    elif "," in limpio:
        limpio = limpio.replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return 0.0

async def login_shopify(page, url_tienda, email, password):
    try:
        admin_url = url_tienda.rstrip("/") + "/admin"
        await page.goto(admin_url, wait_until="networkidle", timeout=30000)
        if "accounts.shopify.com" in page.url or "login" in page.url:
            await page.fill('input[type="email"], input[name="email"]', email)
            await page.click('button[type="submit"]')
            await page.wait_for_timeout(2000)
            try:
                await page.fill('input[type="password"]', password)
                await page.click('button[type="submit"]')
            except Exception:
                pass
            await page.wait_for_url("**/admin**", timeout=20000)
        return True
    except Exception as e:
        print(f"[Shopify] Error login: {e}")
        return False

async def descargar_pedidos_csv(page, url_tienda, fecha_inicio, fecha_corte, carpeta):
    try:
        orders_url = (f"{url_tienda.rstrip('/')}/admin/orders"
                      f"?created_at_min={fecha_inicio.isoformat()}"
                      f"&created_at_max={fecha_corte.isoformat()}")
        await page.goto(orders_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        await page.locator('button:has-text("Exportar"), button:has-text("Export")').first.click()
        await page.wait_for_timeout(1500)
        opciones = page.locator('input[value="current_page"], input[value="filtered"]')
        if await opciones.count() > 0:
            await opciones.first.click()
        async with page.expect_download(timeout=60000) as dl_info:
            await page.click('button:has-text("Exportar pedidos"), button:has-text("Export orders")')
        download = await dl_info.value
        ruta = os.path.join(carpeta, f"shopify_{fecha_inicio}_{fecha_corte}.csv")
        await download.save_as(ruta)
        return ruta
    except Exception as e:
        print(f"[Shopify] Error descarga: {e}")
        return None

def parsear_csv_shopify(ruta_csv):
    import csv
    pedidos = []
    with open(ruta_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numero = row.get("Name", row.get("Order", "")).strip()
            if not numero:
                continue
            fecha_str = row.get("Created at", "")
            try:
                fecha = datetime.fromisoformat(fecha_str.split("+")[0].strip()) if fecha_str else None
            except ValueError:
                fecha = None
            fecha_pago_str = row.get("Paid at", "")
            try:
                fecha_pago = datetime.fromisoformat(fecha_pago_str.split("+")[0].strip()) if fecha_pago_str else None
            except ValueError:
                fecha_pago = None
            gateway_raw = row.get("Payment Method", row.get("Gateway", ""))
            estado_financiero = row.get("Financial Status", "").lower()
            pedidos.append({
                "numero_pedido": numero,
                "cliente_nombre": row.get("Billing Name", ""),
                "cliente_email": row.get("Email", ""),
                "fecha_pedido": fecha,
                "valor_total": limpiar_valor(row.get("Total", "0")),
                "plataforma_pago": normalizar_plataforma(gateway_raw),
                "estado_shopify": estado_financiero,
                "estado_conciliacion": "pagado" if estado_financiero == "paid" else "pendiente",
                "fecha_pago_real": fecha_pago,
            })
    return pedidos

async def sincronizar_shopify(credenciales, fecha_inicio, fecha_corte, carpeta_descarga, headless=True):
    os.makedirs(carpeta_descarga, exist_ok=True)
    resultado = {"ok": False, "pedidos": [], "error": None, "archivo": None}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            ok = await login_shopify(page, credenciales["url_tienda"], credenciales["email"], credenciales["password"])
            if not ok:
                resultado["error"] = "No se pudo iniciar sesion en Shopify."
                return resultado
            ruta_csv = await descargar_pedidos_csv(page, credenciales["url_tienda"], fecha_inicio, fecha_corte, carpeta_descarga)
            if not ruta_csv or not os.path.exists(ruta_csv):
                resultado["error"] = "No se pudo descargar el CSV."
                return resultado
            pedidos = parsear_csv_shopify(ruta_csv)
            resultado.update({"ok": True, "pedidos": pedidos, "archivo": ruta_csv,
                              "total_pedidos": len(pedidos), "total_valor": sum(p["valor_total"] for p in pedidos)})
        except Exception as e:
            resultado["error"] = str(e)
        finally:
            await browser.close()
    return resultado
