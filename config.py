"""
Configuración del rastreador de vuelos CDMX -> Seúl (ICN).

Edita estos valores según tus necesidades. No pongas API keys aquí:
esas van como "secrets" de GitHub (ver README.md).
"""

import datetime

# --- Ruta ---
ORIGIN = "MEX"          # Ciudad de México
DESTINATION = "ICN"     # Incheon, Seúl

# Sky Scrapper (Skyscanner) a veces no resuelve bien buscando solo por código
# IATA ("MEX"), así que para ESE proveedor buscamos por nombre y filtramos por
# el código IATA esperado (ORIGIN/DESTINATION de arriba).
SKYSCANNER_ORIGIN_QUERY = "Mexico City"
SKYSCANNER_DESTINATION_QUERY = "Seoul Incheon"

# --- Ventana de fechas objetivo ---
# Define el rango de meses/días dentro del cual quieres comparar precios.
# Verano 2027 (junio-agosto).
#TARGET_RANGE_START = datetime.date(2027, 6, 1)
TARGET_RANGE_START = datetime.date(2026, 9, 1)

#TARGET_RANGE_END = datetime.date(2027, 8, 31)
TARGET_RANGE_END = datetime.date(2026, 9, 15)

# Duración del viaje (noches en Seúl) que quieres comparar.
# 14-18 noches.
TRIP_LENGTHS_DAYS = [14, 16, 18]

# Cada cuántos días generar una fecha de salida candidata dentro del rango.
# Con 3 días de intervalo se generan más combinaciones (más preciso, gasta más cuota).
# Con 7 días se generan menos (más barato de correr, revisa cuota disponible).
DATE_STEP_DAYS = 5

# --- Cuánto revisar por corrida (para no gastar la cuota gratuita de golpe) ---
# El script guarda un "puntero" (rotation_state.json) y en cada corrida
# solo consulta este número de combinaciones nuevas, avanzando la próxima vez.
COMBOS_PER_RUN_SERPAPI = 6      # SerpApi: 250 free/mes -> ~8/día es seguro
COMBOS_PER_RUN_SKYSCANNER = 3   # RapidAPI Sky Scrapper: 100 free/mes -> ~3/día es seguro

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
