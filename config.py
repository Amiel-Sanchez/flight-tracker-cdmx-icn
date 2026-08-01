"""
Configuración del rastreador de vuelos CDMX -> Seúl (ICN).

Edita estos valores según tus necesidades. No pongas API keys aquí:
esas van como "secrets" de GitHub (ver README.md).
"""

import datetime

# --- Ruta ---
ORIGIN = "MEX"          # Ciudad de México
DESTINATION = "ICN"     # Incheon, Seúl

# --- Ventana de fechas objetivo ---
# Define el rango de meses/días dentro del cual quieres comparar precios.
# Verano 2027 (junio-agosto).
TARGET_RANGE_START = datetime.date(2027, 2, 1)
TARGET_RANGE_END = datetime.date(2027, 10, 31)

# Duración del viaje (noches en Seúl) que quieres comparar.
# 14-18 noches.
TRIP_LENGTHS_DAYS = [14, 16, 18]

# Cada cuántos días generar una fecha de salida candidata dentro del rango.
# Con 3 días de intervalo se generan más combinaciones (más preciso, gasta más cuota).
# Con 7 días se generan menos (más barato de correr, revisa cuota disponible).
DATE_STEP_DAYS = 3

# --- Cuánto revisar por corrida (para no gastar la cuota gratuita de golpe) ---
# El script guarda un "puntero" (rotation_state.json) y en cada corrida
# solo consulta este número de combinaciones nuevas, avanzando la próxima vez.
COMBOS_PER_RUN_SERPAPI = 6   # SerpApi: 250 free/mes -> ~8/día es seguro
# Ignav: 1,000 requests gratis EN TOTAL (no se renuevan cada mes). Con 3/día
# te duran ~330 días (todo el año hasta tu viaje). Después de agotarse, son
# $2 USD por cada 1,000 requests adicionales — prácticamente nada si decides
# seguir corriéndolo, pero mejor estirar el free tier lo más posible.
COMBOS_PER_RUN_IGNAV = 3

# --- Preferencia de escalas ---
# "any"    -> trae todo y lo guardamos con la columna stops para comparar tú mismo
# "direct" -> solo vuelos directos
STOPS_PREFERENCE = "any"

# --- Alertas ---
# Te avisa por Telegram si encuentra un precio igual o menor a este umbral (MXN).
# Tu presupuesto ideal es 20,000-25,000 MXN; se puso el umbral en 22,000
# (parte baja/media del rango) para que te avise de las mejores oportunidades.
# Súbelo a 25000 si quieres más alertas (todo lo que entre en tu presupuesto máximo).
PRICE_ALERT_THRESHOLD_MXN = 22000

CURRENCY = "MXN"

# --- Rutas de almacenamiento ---
DB_PATH = "data/flights.db"
ROTATION_STATE_PATH = "data/rotation_state.json"
