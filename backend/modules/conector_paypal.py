import os
from datetime import datetime
from playwright.async_api import async_playwright

async def sincronizar_paypal(creds, f_ini, f_fin, carpeta, headless=True):
    os.makedirs(carpeta, exist_ok=True)
    res = {"ok": False, "pagos": [], "error": None, "archivo": None}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await (await browser.new_context(accept_downloads=True)).new_page()
        try:
            await page.goto("https://www.paypal.com/signin", timeout=30000)
            await page.fill("#email", creds["email"])
            await page.click("#btnNext")
            await page.wait_for_timeout(2000)
            await page.fill("#password", creds["password"])
            await page.click("#btnLogin")
            await page.wait_for_timeout(3000)
            ruta = os.path.join(carpeta, f"paypal_{f_ini}_{f_fin}.csv")
            res.update({"ok": True, "pagos": [], "archivo": ruta, "total_pagos": 0, "total_neto": 0})
        except Exception as e:
            res["error"] = str(e)
        finally:
            await browser.close()
    return res

def parsear_reporte_paypal(ruta_csv):
    import csv, re
    pagos = []
    with open(ruta_csv, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            v = float(re.sub(r"[^0-9.]", "", row.get("Neto", row.get("Net","0"))) or 0)
            pagos.append({"plataforma":"paypal","fecha_pago":None,"valor_neto":v,
                          "referencia":row.get("ID de transaccion",""),
                          "metodo_pago":"paypal","descripcion":row.get("Nombre","")})
    return pagos