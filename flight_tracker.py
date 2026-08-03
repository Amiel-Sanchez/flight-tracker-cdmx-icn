"""
Rastreador de vuelos CDMX -> Seúl (ICN).

Consulta dos fuentes gratuitas (SerpApi/Google Flights e Ignav, ambas APIs
de fare search dedicadas), guarda cada resultado en SQLite con fecha de
consulta, y manda una alerta a Telegram si algún precio cae por debajo del
umbral configurado.

Diseñado para correr 1 vez al día vía GitHub Actions, consumiendo poca cuota
cada vez (ver config.py) y rotando qué combinaciones de fechas revisa en cada
corrida, para cubrir todo el rango objetivo a lo largo del mes sin agotar
las cuotas gratuitas.
"""

import os
import json
import time
import sqlite3
import datetime
import itertools
import requests

import config

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
IGNAV_API_KEY = os.environ.get("IGNAV_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


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
            state = json.load(f)
            # Compatibilidad si el archivo viejo todavía tiene skyscanner_index
            if "ignav_index" not in state:
                state["ignav_index"] = state.pop("skyscanner_index", 0)
            return state
    return {"serpapi_index": 0, "ignav_index": 0}


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


def save_result(conn, source, outbound_date, return_date, trip_length, price, stops, airline, currency=None):
    conn.execute(
        """INSERT INTO flight_prices
           (source, outbound_date, return_date, trip_length_days, price, currency, stops, airline, query_timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source, outbound_date, return_date, trip_length, price, currency or config.CURRENCY, stops, airline,
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
    # Mapeo de MAX_STOPS al parámetro "stops" de SerpApi:
    # 0="cualquiera" (default), 1="solo directos", 2="1 escala o menos", 3="2 escalas o menos"
    stops_param_map = {0: "1", 1: "2", 2: "3"}
    if config.MAX_STOPS in stops_param_map:
        params["stops"] = stops_param_map[config.MAX_STOPS]

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
            if config.MAX_STOPS is not None and stops > config.MAX_STOPS:
                continue
            if price is not None:
                results.append({"price": price, "stops": stops, "airline": airline})

    print(f"  [SerpApi] {len(results)} ofertas encontradas.")
    return results


# ---------------------------------------------------------------------------
# Sky Scrapper (Skyscanner vía RapidAPI)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ignav (fare search dedicada)
# ---------------------------------------------------------------------------

def search_ignav(outbound_date, return_date):
    """Devuelve una lista de dicts: price, stops, airline."""
    if not IGNAV_API_KEY:
        print("  [Ignav] IGNAV_API_KEY no configurada, se omite.")
        return []

    body = {
        "origin": config.ORIGIN,
        "destination": config.DESTINATION,
        "departure_date": outbound_date,
        "return_date": return_date,
        "adults": 1,
        "market": "MX",  # controla moneda/localización de los resultados (MXN para México)
    }
    if config.MAX_STOPS is not None:
        body["max_stops"] = config.MAX_STOPS

    try:
        resp = requests.post(
            "https://ignav.com/api/fares/round-trip",
            headers={"X-Api-Key": IGNAV_API_KEY, "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        if not resp.ok:
            print(f"  [Ignav] {resp.status_code} en la solicitud. Respuesta: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"  [Ignav] Error de red/API: {e}")
        return []

    results = []
    for it in data.get("itineraries", []):
        price = it.get("price", {}).get("amount")
        price_currency = it.get("price", {}).get("currency", config.CURRENCY)
        outbound_leg = it.get("outbound", {})
        stops = max(len(outbound_leg.get("segments", [])) - 1, 0)
        airline = outbound_leg.get("carrier", "desconocida")
        if config.MAX_STOPS is not None and stops > config.MAX_STOPS:
            continue
        if price is not None:
            results.append({"price": price, "currency": price_currency, "stops": stops, "airline": airline})

    print(f"  [Ignav] {len(results)} ofertas encontradas.")
    return results


def generate_summary_report(conn):
    """Genera data/resumen.md con las ofertas más baratas encontradas hasta ahora,
    para poder revisarlas directo en GitHub sin herramientas de SQLite."""
    cur = conn.cursor()

    total_rows = cur.execute("SELECT COUNT(*) FROM flight_prices").fetchone()[0]

    cheapest = cur.execute("""
        SELECT source, outbound_date, return_date, trip_length_days, price, currency,
               stops, airline, query_timestamp
        FROM flight_prices
        ORDER BY price ASC
        LIMIT 15
    """).fetchall()

    latest_run = cur.execute("SELECT MAX(query_timestamp) FROM flight_prices").fetchone()[0]

    lines = [
        "# Resumen de precios — CDMX → Seúl (ICN)",
        "",
        f"Última actualización: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"Total de consultas guardadas en el historial: {total_rows}",
        f"Última corrida con datos: {latest_run or 'N/A'}",
        f"Umbral de alerta configurado: ${config.PRICE_ALERT_THRESHOLD_MXN:,.0f} {config.CURRENCY}",
        "",
        "## Las 15 ofertas más baratas encontradas hasta ahora",
        "",
        "| Precio | Salida | Regreso | Noches | Escalas | Aerolínea | Fuente | Consultado |",
        "|---|---|---|---|---|---|---|---|",
    ]

    if not cheapest:
        lines.append("| _Todavía no hay datos guardados_ | | | | | | | |")
    else:
        for row in cheapest:
            source, outbound, ret, length, price, currency, stops, airline, ts = row
            stops_txt = "directo" if stops == 0 else f"{stops} escala(s)" if stops is not None else "?"
            ts_short = ts[:16].replace("T", " ") if ts else ""
            lines.append(
                f"| ${price:,.0f} {currency} | {outbound} | {ret} | {length} | {stops_txt} | "
                f"{airline} | {source} | {ts_short} |"
            )

    with open("data/resumen.md", "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\ndata/resumen.md actualizado ({total_rows} registros en el historial total).")


def export_json_for_dashboard(conn):
    """Genera docs/data.json con todo el historial, para el dashboard filtrable
    en docs/index.html (publicado vía GitHub Pages)."""
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT source, outbound_date, return_date, trip_length_days, price, currency,
               stops, airline, query_timestamp
        FROM flight_prices
        ORDER BY query_timestamp DESC
    """).fetchall()

    records = [
        {
            "source": r[0], "outbound_date": r[1], "return_date": r[2],
            "trip_length_days": r[3], "price": r[4], "currency": r[5],
            "stops": r[6], "airline": r[7], "query_timestamp": r[8],
        }
        for r in rows
    ]

    payload = {
        "meta": {
            "origin": config.ORIGIN,
            "destination": config.DESTINATION,
            "threshold": config.PRICE_ALERT_THRESHOLD_MXN,
            "currency": config.CURRENCY,
            "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        },
        "records": records,
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w") as f:
        json.dump(payload, f, ensure_ascii=False)

    print(f"docs/data.json actualizado ({len(records)} registros).")


def export_dashboard_json(conn):
    """Genera docs/data.json con todo el historial, para que la página de
    GitHub Pages (docs/index.html) lo lea y permita filtrar desde el navegador."""
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT source, outbound_date, return_date, trip_length_days, price, currency,
               stops, airline, query_timestamp
        FROM flight_prices
        ORDER BY query_timestamp DESC
    """).fetchall()

    payload = {
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "rows": [
            {
                "source": r[0], "outbound_date": r[1], "return_date": r[2],
                "trip_length_days": r[3], "price": r[4], "currency": r[5],
                "stops": r[6], "airline": r[7], "query_timestamp": r[8],
            }
            for r in rows
        ],
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w") as f:
        json.dump(payload, f)

    print(f"docs/data.json actualizado ({len(rows)} registros).")


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
    ignav_batch, next_ignav_index = next_batch(all_combos, state["ignav_index"], config.COMBOS_PER_RUN_IGNAV)

    conn = init_db()
    alerts = []

    print(f"\nConsultando SerpApi para {len(serpapi_batch)} combinaciones...")
    for outbound, ret, length in serpapi_batch:
        print(f"  -> {outbound} / {ret} ({length} noches)")
        for r in search_serpapi(outbound, ret):
            save_result(conn, "serpapi", outbound, ret, length, r["price"], r["stops"], r["airline"])
            if r["price"] <= config.PRICE_ALERT_THRESHOLD_MXN:
                alerts.append((outbound, ret, length, r["price"], r["stops"], r["airline"], "SerpApi"))

    print(f"\nConsultando Ignav para {len(ignav_batch)} combinaciones...")
    for outbound, ret, length in ignav_batch:
        print(f"  -> {outbound} / {ret} ({length} noches)")
        for r in search_ignav(outbound, ret):
            save_result(conn, "ignav", outbound, ret, length, r["price"], r["stops"], r["airline"], r["currency"])
            if r["currency"] == config.CURRENCY and r["price"] <= config.PRICE_ALERT_THRESHOLD_MXN:
                alerts.append((outbound, ret, length, r["price"], r["stops"], r["airline"], "Ignav"))

    generate_summary_report(conn)
    export_dashboard_json(conn)
    conn.close()

    state["serpapi_index"] = next_serpapi_index
    state["ignav_index"] = next_ignav_index
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
