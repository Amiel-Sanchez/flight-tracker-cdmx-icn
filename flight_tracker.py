"""
Rastreador de vuelos CDMX -> Seúl (ICN).

Consulta dos fuentes gratuitas (SerpApi/Google Flights y Sky Scrapper/Skyscanner
vía RapidAPI), guarda cada resultado en SQLite con fecha de consulta, y manda
una alerta a Telegram si algún precio cae por debajo del umbral configurado.

Diseñado para correr 1 vez al día vía GitHub Actions, consumiendo poca cuota
cada vez (ver config.py) y rotando qué combinaciones de fechas revisa en cada
corrida, para cubrir todo el rango objetivo a lo largo del mes sin agotar
las cuotas gratuitas.
"""

import os
import json
import sqlite3
import datetime
import itertools
import requests

import config

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SKY_SCRAPPER_HOST = "sky-scrapper.p.rapidapi.com"


# ---------------------------------------------------------------------------
# Utilidades de fechas / rotación
# ---------------------------------------------------------------------------

def generate_candidate_combos():
    """Genera todas las combinaciones (salida, regreso) dentro del rango objetivo."""
    combos = []
    d = config.TARGET_RANGE_START
    while d <= config.TARGET_RANGE_END:
        for length in config.TRIP_LENGTHS_DAYS:
            return_date = d + datetime.timedelta(days=length)
            combos.append((d.isoformat(), return_date.isoformat(), length))
        d += datetime.timedelta(days=config.DATE_STEP_DAYS)
    return combos


def load_rotation_state():
    if os.path.exists(config.ROTATION_STATE_PATH):
        with open(config.ROTATION_STATE_PATH) as f:
            return json.load(f)
    return {"serpapi_index": 0, "skyscanner_index": 0}


def save_rotation_state(state):
    os.makedirs(os.path.dirname(config.ROTATION_STATE_PATH), exist_ok=True)
    with open(config.ROTATION_STATE_PATH, "w") as f:
        json.dump(state, f)


def next_batch(combos, start_index, batch_size):
    """Devuelve `batch_size` combos empezando en start_index, dando la vuelta
    al llegar al final (round-robin), y el índice donde debe seguir la próxima vez."""
    n = len(combos)
    if n == 0:
        return [], 0
    batch = [combos[(start_index + i) % n] for i in range(min(batch_size, n))]
    next_index = (start_index + batch_size) % n
    return batch, next_index


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def init_db():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flight_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            outbound_date TEXT,
            return_date TEXT,
            trip_length_days INTEGER,
            price REAL,
            currency TEXT,
            stops INTEGER,
            airline TEXT,
            query_timestamp TEXT
        )
    """)
    conn.commit()
    return conn


def save_result(conn, source, outbound_date, return_date, trip_length, price, stops, airline):
    conn.execute(
        """INSERT INTO flight_prices
           (source, outbound_date, return_date, trip_length_days, price, currency, stops, airline, query_timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source, outbound_date, return_date, trip_length, price, config.CURRENCY, stops, airline,
         datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# SerpApi (Google Flights)
# ---------------------------------------------------------------------------

def search_serpapi(outbound_date, return_date):
    """Devuelve una lista de dicts: price, stops, airline."""
    if not SERPAPI_KEY:
        print("  [SerpApi] SERPAPI_KEY no configurada, se omite.")
        return []

    params = {
        "engine": "google_flights",
        "departure_id": config.ORIGIN,
        "arrival_id": config.DESTINATION,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "currency": config.CURRENCY,
        "hl": "es",
        "type": "1",  # round trip
        "api_key": SERPAPI_KEY,
    }
    if config.STOPS_PREFERENCE == "direct":
        params["stops"] = "1"  # 1 = solo directos en la API de SerpApi

    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"  [SerpApi] Error de red/API: {e}")
        return []

    if "error" in data:
        print(f"  [SerpApi] La API devolvió un error: {data['error']}")
        return []

    results = []
    for bucket in ("best_flights", "other_flights"):
        for offer in data.get(bucket, []):
            price = offer.get("price")
            legs = offer.get("flights", [])
            stops = max(len(legs) - 1, 0)
            airline = legs[0]["airline"] if legs else "desconocida"
            if price is not None:
                results.append({"price": price, "stops": stops, "airline": airline})

    print(f"  [SerpApi] {len(results)} ofertas encontradas.")
    return results


# ---------------------------------------------------------------------------
# Sky Scrapper (Skyscanner vía RapidAPI)
# ---------------------------------------------------------------------------

_airport_cache = {}


def _sky_headers():
    return {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": SKY_SCRAPPER_HOST}


def _extract_sky_and_entity_id(entry):
    """Distintas versiones de la respuesta anidan estos campos distinto; probamos varias rutas."""
    sky_id = (
        entry.get("skyId")
        or entry.get("navigation", {}).get("relevantFlightParams", {}).get("skyId")
        or entry.get("presentation", {}).get("id")
    )
    entity_id = (
        entry.get("entityId")
        or entry.get("navigation", {}).get("entityId")
        or entry.get("entityId")
    )
    return sky_id, entity_id


def _resolve_sky_id(search_query, expected_iata):
    """Busca skyId y entityId de un aeropuerto por NOMBRE (search_query), filtrando
    por el código IATA esperado (expected_iata) entre los resultados. Se cachea
    por expected_iata para no repetir la búsqueda en cada combinación de fechas."""
    if expected_iata in _airport_cache:
        return _airport_cache[expected_iata]

    url = f"https://{SKY_SCRAPPER_HOST}/api/v1/flights/searchAirport"
    resp = requests.get(url, headers=_sky_headers(), params={"query": search_query, "locale": "en-US"}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data", [])

    if not data:
        print(f"  [Sky Scrapper] Respuesta cruda de searchAirport para '{search_query}': {json.dumps(payload)[:500]}")
        raise ValueError(f"No se encontró ningún resultado para '{search_query}'")

    # Preferimos la entrada cuyo skyId coincide con el IATA esperado; si ninguna
    # coincide exactamente, caemos de vuelta a la primera entrada devuelta.
    chosen = None
    for entry in data:
        sky_id, _ = _extract_sky_and_entity_id(entry)
        if sky_id == expected_iata:
            chosen = entry
            break
    if chosen is None:
        chosen = data[0]
        print(f"  [Sky Scrapper] Ninguna coincidencia exacta con '{expected_iata}' para '{search_query}', "
              f"usando la primera opción devuelta.")

    sky_id, entity_id = _extract_sky_and_entity_id(chosen)
    if not sky_id or not entity_id:
        print(f"  [Sky Scrapper] Entrada elegida sin skyId/entityId reconocibles: {json.dumps(chosen)[:500]}")
        raise ValueError(f"No se pudo extraer skyId/entityId para '{search_query}'")

    result = {"skyId": sky_id, "entityId": entity_id}
    _airport_cache[expected_iata] = result
    return result


def search_skyscanner(outbound_date, return_date):
    """Devuelve una lista de dicts: price, stops, airline (solo tramo de ida,
    Sky Scrapper cotiza por fecha; para ida y vuelta se llama dos veces)."""
    if not RAPIDAPI_KEY:
        print("  [Sky Scrapper] RAPIDAPI_KEY no configurada, se omite.")
        return []

    try:
        origin = _resolve_sky_id(config.SKYSCANNER_ORIGIN_QUERY, config.ORIGIN)
        dest = _resolve_sky_id(config.SKYSCANNER_DESTINATION_QUERY, config.DESTINATION)

        url = f"https://{SKY_SCRAPPER_HOST}/api/v1/flights/searchFlights"
        params = {
            "originSkyId": origin["skyId"],
            "destinationSkyId": dest["skyId"],
            "originEntityId": origin["entityId"],
            "destinationEntityId": dest["entityId"],
            "date": outbound_date,
            "returnDate": return_date,
            "adults": "1",
            "currency": config.CURRENCY,
            "market": "es-MX",
            "countryCode": "MX",
        }
        resp = requests.get(url, headers=_sky_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [Sky Scrapper] Error: {e}")
        return []

    results = []
    itineraries = data.get("data", {}).get("itineraries", [])
    for it in itineraries:
        price = it.get("price", {}).get("raw")
        legs = it.get("legs", [])
        stops = legs[0].get("stopCount", 0) if legs else None
        airline = None
        if legs and legs[0].get("carriers", {}).get("marketing"):
            airline = legs[0]["carriers"]["marketing"][0].get("name")
        if price is not None:
            results.append({"price": price, "stops": stops, "airline": airline or "desconocida"})

    print(f"  [Sky Scrapper] {len(results)} ofertas encontradas.")
    return results


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [Telegram] Bot no configurado, se omite el envío.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except requests.RequestException as e:
        print(f"  [Telegram] Error al enviar mensaje: {e}")


# ---------------------------------------------------------------------------
# Orquestación principal
# ---------------------------------------------------------------------------

def main():
    all_combos = generate_candidate_combos()
    print(f"Total de combinaciones fecha-salida/fecha-regreso en el rango objetivo: {len(all_combos)}")

    state = load_rotation_state()
    serpapi_batch, next_serpapi_index = next_batch(all_combos, state["serpapi_index"], config.COMBOS_PER_RUN_SERPAPI)
    sky_batch, next_sky_index = next_batch(all_combos, state["skyscanner_index"], config.COMBOS_PER_RUN_SKYSCANNER)

    conn = init_db()
    alerts = []

    print(f"\nConsultando SerpApi para {len(serpapi_batch)} combinaciones...")
    for outbound, ret, length in serpapi_batch:
        print(f"  -> {outbound} / {ret} ({length} noches)")
        for r in search_serpapi(outbound, ret):
            save_result(conn, "serpapi", outbound, ret, length, r["price"], r["stops"], r["airline"])
            if r["price"] <= config.PRICE_ALERT_THRESHOLD_MXN:
                alerts.append((outbound, ret, length, r["price"], r["stops"], r["airline"], "SerpApi"))

    print(f"\nConsultando Sky Scrapper para {len(sky_batch)} combinaciones...")
    for outbound, ret, length in sky_batch:
        print(f"  -> {outbound} / {ret} ({length} noches)")
        for r in search_skyscanner(outbound, ret):
            save_result(conn, "skyscanner", outbound, ret, length, r["price"], r["stops"], r["airline"])
            if r["price"] <= config.PRICE_ALERT_THRESHOLD_MXN:
                alerts.append((outbound, ret, length, r["price"], r["stops"], r["airline"], "Sky Scrapper"))

    conn.close()

    state["serpapi_index"] = next_serpapi_index
    state["skyscanner_index"] = next_sky_index
    save_rotation_state(state)

    if alerts:
        lines = ["✈️ <b>¡Precio bajo encontrado! CDMX → Seúl (ICN)</b>"]
        for outbound, ret, length, price, stops, airline, source in alerts:
            stops_txt = "directo" if stops == 0 else f"{stops} escala(s)"
            lines.append(
                f"\n{outbound} → {ret} ({length} noches)\n"
                f"${price:,.0f} {config.CURRENCY} · {stops_txt} · {airline} · fuente: {source}"
            )
        send_telegram_message("\n".join(lines))
        print(f"\n{len(alerts)} alerta(s) enviadas a Telegram.")
    else:
        print("\nNinguna combinación de esta corrida bajó del umbral configurado.")


if __name__ == "__main__":
    main()
