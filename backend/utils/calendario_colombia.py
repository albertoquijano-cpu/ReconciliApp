from datetime import date, datetime, timedelta
import holidays

def get_festivos_colombia(year):
    return set(holidays.Colombia(years=year).keys())

def es_dia_habil(fecha):
    if fecha.weekday() >= 5:
        return False
    return fecha not in get_festivos_colombia(fecha.year)

def siguiente_dia_habil(fecha):
    siguiente = fecha + timedelta(days=1)
    while not es_dia_habil(siguiente):
        siguiente += timedelta(days=1)
    return siguiente

def sumar_dias_habiles(fecha_inicio, dias):
    fecha = fecha_inicio
    habiles_contados = 0
    while habiles_contados < dias:
        fecha += timedelta(days=1)
        if es_dia_habil(fecha):
            habiles_contados += 1
    return fecha

def sumar_dias_calendario(fecha_inicio, dias):
    fecha = fecha_inicio + timedelta(days=dias)
    while not es_dia_habil(fecha):
        fecha += timedelta(days=1)
    return fecha

def calcular_fecha_pago_esperada(fecha_venta, plataforma):
    from backend.modules.credenciales import PLAZOS_DIAS
    dias = PLAZOS_DIAS.get(plataforma, 2)
    if plataforma in ("addi", "sistecredito"):
        return sumar_dias_calendario(fecha_venta, dias)
    return sumar_dias_habiles(fecha_venta, dias)

def calcular_mora(fecha_esperada, fecha_real):
    if isinstance(fecha_esperada, datetime):
        fecha_esperada = fecha_esperada.date()
    if isinstance(fecha_real, datetime):
        fecha_real = fecha_real.date()
    return (fecha_real - fecha_esperada).days

def dias_habiles_entre(fecha_inicio, fecha_fin):
    if fecha_inicio > fecha_fin:
        return 0
    count = 0
    current = fecha_inicio
    while current <= fecha_fin:
        if es_dia_habil(current):
            count += 1
        current += timedelta(days=1)
    return count
