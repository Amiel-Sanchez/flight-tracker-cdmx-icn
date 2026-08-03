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
# Todo 2027: conforme pase el tiempo, las aerolíneas irán abriendo más meses
# para reserva (normalmente ~11-12 meses de anticipación), así que aunque hoy
# muchas combinaciones de fin de año todavía no tengan resultados, el mismo
# script las va a ir encontrando solo según avance el calendario.
TARGET_RANGE_START = datetime.date(2027, 1, 1)
TARGET_RANGE_END = datetime.date(2027, 12, 31)

# Duración del viaje (noches en Seúl) que quieres comparar.
# 10-14 noches.
TRIP_LENGTHS_DAYS = [10, 12, 14]

# Cada cuántos días generar una fecha de salida candidata dentro del rango.
# Con 3 días de intervalo se generan más combinaciones (más preciso, gasta más cuota).
# Con 7 días se generan menos (más barato de correr, revisa cuota disponible).
DATE_STEP_DAYS = 5

# --- Cuánto revisar por corrida (para no gastar la cuota gratuita de golpe) ---
# El script guarda un "puntero" (rotation_state.json) y en cada corrida
# solo consulta este número de combinaciones nuevas, avanzando la próxima vez.
# Con 219 combinaciones totales (todo 2027):
COMBOS_PER_RUN_SERPAPI = 8   # SerpApi: ciclo completo cada ~28 días. 8/día = 240/mes,
                             # dentro del límite gratis de 250/mes (con margen).
# Ignav: 1,000 requests gratis EN TOTAL (no se renuevan cada mes).
# Con 32/día, ciclo completo cada ~7 días. Free tier dura ~31 días; después
# son $2 USD por cada 1,000 adicionales (~$17.20 USD estimados hasta la
# fecha del viaje, ~300 días) — aceptado explícitamente por el usuario.
COMBOS_PER_RUN_IGNAV = 32

# --- Preferencia de escalas ---
# Escalas MÁXIMAS permitidas. Las ofertas con más escalas que esto ni
# siquiera se piden a las APIs (ni se guardan, ni generan alertas).
#   None -> cualquier número de escalas (sin filtro)
#   0    -> solo vuelos directos
#   1    -> máximo 1 escala (descarta itinerarios de 2+ escalas)
#   2    -> máximo 2 escalas
MAX_STOPS = 1

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
