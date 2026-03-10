import os
from datetime import date, datetime
from playwright.async_api import async_playwright

async def sincronizar_sistecredito(credenciales, fecha_inicio, fecha_corte, carpeta_descarga, headless=True):
    os.makedirs(carpeta_descarga, exist_ok=True)
    resultado = {"ok": False, "pagos": [], "error": None, "archivo": None}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            await page.goto("https://www.sistecredito.com/comercios/login", wait_until="networkidle", timeout=30000)
            await page.fill('input[type="email"], input[name="email"], input[name="usuario"]', credenciales["email"])
            await page.fill('input[type="password"], input[name="password"]', credenciales["password"])
            await page.click('button[type="submit"]')
            await page.wait_for_url("**sistecredito.com/**", timeout=20000)

            await page.goto("https://www.sistecredito.com/comercios/reportes", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            await page.fill('input[placeholder*="inicio"], input[name*="start"]', fecha_inicio.strftime("%d/%m/%Y"))
            await page.fill('input[placeholder*="fin"], input[name*="end"]', fecha_corte.strftime("%d/%m/%Y"))
            await page.click('button:has-text("Aplicar"), button:has-text("Consultar"), button:has-text("Buscar")')
            await page.wait_for_timeout(2000)

            async with page.expect_download(timeout=60000) as dl_info:
                await page.click('button:has-text("Exportar"), button:has-text("Descargar")')
            download = await dl_info.value
            ruta = os.path.join(carpeta_descarga, f"sistecredito_{fecha_inicio}_{fecha_corte}.csv")
            await download.save_as(ruta)

            pagos = parsear_reporte_sistecredito(ruta)
            resultado.update({"ok": True, "pagos": pagos, "archivo": ruta,
                              "total_pagos": len(pagos), "total_neto": sum(p["valor_neto"] for p in pagos)})
        except Exception as e:
            resultado["error"] = str(e)
        finally:
            await browser.close()
    return resultado

def parsear_reporte_sistecredito(ruta_csv):
    import csv, re
    pagos = []
    with open(ruta_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            estado = row.get("Estado", row.get("Status", "")).upper()
            if estado not in ("PAGADO", "PAID", "APROBADO", "LIQUIDADO"):
                continue
            valor_str = row.get("Valor", row.get("Monto", row.get("Total", "0")))
            valor_neto = float(re.sub(r"[^\d.]", "", valor_str or "0") or 0)
            fecha_str = row.get("Fecha de pago", row.get("Fecha liquidacion", row.get("Fecha", "")))
            try:
                fecha = datetime.strptime(fecha_str.strip(), "%d/%m/%Y") if fecha_str else None
            except Exception:
                fecha = None
            fecha_venta_str = row.get("Fecha de compra", row.get("Fecha orden", ""))
            try:
                fecha_venta = datetime.strptime(fecha_venta_str.strip(), "%d/%m/%Y") if fecha_venta_str else None
            except Exception:
                fecha_venta = None
            pagos.append({
                "plataforma": "sistecredito",
                "fecha_pago": fecha,
                "fecha_venta": fecha_venta,
                "valor_neto": valor_neto,
                "referencia": row.get("ID", row.get("Numero orden", row.get("Referencia", ""))),
                "metodo_pago": "sistecredito",
                "descripcion": row.get("Cliente", row.get("Nombre", "")),
            })
    return pagos
