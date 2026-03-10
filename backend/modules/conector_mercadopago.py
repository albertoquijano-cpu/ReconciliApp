import os
from datetime import date, datetime
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

async def sincronizar_mercadopago(credenciales, fecha_inicio, fecha_corte, carpeta_descarga, headless=True):
    os.makedirs(carpeta_descarga, exist_ok=True)
    resultado = {"ok": False, "pagos": [], "error": None, "archivo": None}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            await page.goto("https://www.mercadopago.com.co/login", wait_until="networkidle", timeout=30000)
            await page.fill('input[id="user_id"]', credenciales["email"])
            await page.click('button[type="submit"]')
            await page.wait_for_timeout(2000)
            await page.fill('input[id="password"]', credenciales["password"])
            await page.click('button[type="submit"]')
            await page.wait_for_url("**mercadopago.com.co/**", timeout=20000)

            reporte_url = (
                f"https://www.mercadopago.com.co/movements/list"
                f"?startDate={fecha_inicio.isoformat()}"
                f"&endDate={fecha_corte.isoformat()}"
            )
            await page.goto(reporte_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            async with page.expect_download(timeout=60000) as dl_info:
                await page.click('button:has-text("Descargar"), a:has-text("Descargar reporte")')
            download = await dl_info.value
            ruta = os.path.join(carpeta_descarga, f"mercadopago_{fecha_inicio}_{fecha_corte}.csv")
            await download.save_as(ruta)

            pagos = parsear_reporte_mercadopago(ruta)
            resultado.update({"ok": True, "pagos": pagos, "archivo": ruta,
                              "total_pagos": len(pagos), "total_neto": sum(p["valor_neto"] for p in pagos)})
        except Exception as e:
            resultado["error"] = str(e)
        finally:
            await browser.close()
    return resultado

def parsear_reporte_mercadopago(ruta_csv):
    import csv, re
    pagos = []
    with open(ruta_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tipo = row.get("TIPO", row.get("TYPE", "")).upper()
            if "PAGO" not in tipo and "PAYMENT" not in tipo:
                continue
            valor_str = row.get("MONTO_NETO", row.get("NET_CREDIT_AMOUNT", row.get("TOTAL", "0")))
            valor_neto = float(re.sub(r"[^\d.]", "", valor_str or "0") or 0)
            fecha_str = row.get("FECHA", row.get("DATE", ""))
            try:
                fecha = datetime.fromisoformat(fecha_str.split("+")[0].strip()) if fecha_str else None
            except Exception:
                fecha = None
            pagos.append({
                "plataforma": "mercadopago",
                "fecha_pago": fecha,
                "valor_neto": valor_neto,
                "referencia": row.get("DESCRIPCION", row.get("DESCRIPTION", "")),
                "metodo_pago": row.get("MEDIO_DE_PAGO", row.get("PAYMENT_METHOD", "default")).lower(),
                "descripcion": row.get("DESCRIPCION", ""),
            })
    return pagos
