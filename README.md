# Rastreador de vuelos CDMX → Seúl (ICN)

Consulta SerpApi (Google Flights) e Ignav (fare search dedicada) todos los
días, guarda el historial de precios en SQLite dentro del mismo repo, y te avisa por
Telegram cuando encuentra un precio por debajo de tu umbral.

## 1. Crea el repositorio en GitHub

Sube esta carpeta tal cual a un repo **privado** (recomendado, para no exponer tu
historial de búsquedas ni rutas de viaje) en GitHub.

## 2. Consigue las API keys gratuitas

**SerpApi** (250 búsquedas/mes gratis):
1. Crea cuenta en https://serpapi.com/users/sign_up
2. Copia tu API key desde el dashboard.

**Ignav** (1,000 requests gratis, total — no se renuevan cada mes):
1. Crea cuenta en https://ignav.com/signup
2. Copia tu API key desde el dashboard.
3. Después de agotar el free tier, cuesta $2 USD por cada 1,000 requests
   adicionales (solo se cobran las exitosas) — muy barato si decides seguir.

## 3. Crea tu bot de Telegram

1. Habla con **@BotFather** en Telegram, manda `/newbot` y sigue las instrucciones.
2. Te dará un **token** (algo como `123456:ABC-...`) — guárdalo.
3. Manda cualquier mensaje a tu bot recién creado.
4. Entra a `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` en el navegador y
   busca el campo `"chat":{"id": ...}` — ese número es tu **chat_id**.

## 4. Configura los secrets en GitHub

En tu repo: **Settings → Secrets and variables → Actions → New repository secret**,
agrega estos cuatro:

| Nombre | Valor |
|---|---|
| `SERPAPI_KEY` | tu API key de SerpApi |
| `IGNAV_API_KEY` | tu API key de Ignav |
| `TELEGRAM_BOT_TOKEN` | el token de tu bot |
| `TELEGRAM_CHAT_ID` | tu chat id |

## 5. Ajusta `config.py` a tu viaje

Edita `TARGET_RANGE_START`, `TARGET_RANGE_END`, `TRIP_LENGTHS_DAYS` y
`PRICE_ALERT_THRESHOLD_MXN` según tus fechas objetivo y tu presupuesto.

## 6. Actívalo

El workflow (`.github/workflows/track_flights.yml`) ya está configurado para correr
todos los días automáticamente. También puedes correrlo manualmente:
**pestaña Actions → Track flight prices → Run workflow**.

## 7. Revisa el historial

Los precios se van guardando en `data/flights.db` (SQLite). Puedes abrirlo con
cualquier visor de SQLite (por ejemplo la extensión "SQLite Viewer" de VS Code) o
pedirme más adelante que te arme un dashboard/gráfica a partir de esos datos.

## Notas importantes

- **Cuotas**: el script solo consulta un lote pequeño de combinaciones de fechas
  cada día (configurable en `COMBOS_PER_RUN_SERPAPI` / `COMBOS_PER_RUN_IGNAV`)
  y va rotando cuáles revisa, para cubrir todo tu rango de fechas a lo largo del
  mes sin agotar la cuota gratuita. Recuerda que el free tier de Ignav es un
  total único (1,000 requests), no mensual — a 3/día te duran ~330 días.
- **Fragilidad**: SerpApi replica datos de Google Flights, así que si un día
  falla sin razón aparente, probablemente cambió algo en ese servicio — no es
  necesariamente un error en el script.
- **Repo privado**: recomendado para que tu historial de búsquedas no sea público.
