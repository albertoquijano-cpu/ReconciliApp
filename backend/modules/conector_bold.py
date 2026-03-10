import os
from datetime import date
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

async def sincronizar_bold(credenciales, fecha_inicio, fecha_corte, carpeta_descarga, headless=True):
    os.makedirs(carpeta_descarga, exist_ok=True)
    resultado = {"ok": False, "pagos": [], "error": None, "archivo": None}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            await page.goto("https://commerce.bold.co/login", wait_until="networkidle", timeout=30000)
            await page.fill('input[type="email"]', credenciales["email"])
            await page.fill('input[type="password"]', credenciales["password"])
            await page.click('button[type="submit"]')
            await page.wait_for_url("**/dashboard**", timeout=20000)

            await page.goto("https://commerce.bold.co/reports", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            await page.fill('input[placeholder*="inicio"], input[name*="start"]', fecha_inicio.strftime("%d/%m/%Y"))
            await page.fill('input[placeholder*="fin"], input[name*="end"]', fecha_corte.strftime("%d/%m/%Y"))
            await page.click('button:has-text("Aplicar"), button:has-text("Filtrar"), button:has-text("Buscar")')
            await page.wait_for_timeout(2000)

            async with page.expect_download(timeout=60000) as dl_info:
                await page.click('button:has-text("Exportar"), button:has-text("Descargar")')
            download = await dl_info.value
            ruta = os.path.join(carpeta_descarga, f"bold_{fecha_inicio}_{fecha_corte}.csv")
            await download.save_as(ruta)

            pagos = parsear_reporte_bold(ruta)
            resultado.update({"ok": True, "pagos": pagos, "archivo": ruta,
                              "total_pagos": len(pagos), "total_neto": sum(p["valor_neto"] for p in pagos)})
        except Exception as e:
            resultado["error"] = str(e)
        finally:
            await browser.close()
    return resultado

def parsear_reporte_bold(ruta_csv):
    import csv, re
    pagos = []
    with open(ruta_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            valor_str = row.get("Valor neto", row.get("Monto", row.get("Total", "0")))
            valor_neto = float(re.sub(r"[^\d.]", "", valor_str or "0") or 0)
            fecha_str = row.get("Fecha", row.get("Fecha de pago", ""))
            try:
                from datetime import datetime
                fecha = datetime.strptime(fecha_str.strip(), "%d/%m/%Y") if fecha_str else None
            except Exception:
                fecha = None
            pagos.append({
                "plataforma": "bold",
                "fecha_pago": fecha,
                "valor_neto": valor_neto,
                "referencia": row.get("ID", row.get("Referencia", "")),
                "metodo_pago": row.get("Medio de pago", row.get("Tipo tarjeta", "default")).lower(),
                "descripcion": row.get("Descripcion", ""),
            })
    return pagos
