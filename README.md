# CSP Radar

Private cash-secured put scanner. It ranks optimal CSP candidates by premium edge, assignment quality, liquidity, and event cleanliness.

Cash required is shown, but never used to filter or rank.

Default delta band is `-0.35` to `-0.05`, which includes puts under 0.15 absolute delta while still skipping near-zero lotto contracts.

## Preferred data stack

- Tradier: options chains, quotes, Greeks.
- Finnhub: earnings calendar.
- FMP/Polygon later: fundamentals, IV rank, broader market universe.

## Environment

```bash
export TRADIER_TOKEN=...
export FINNHUB_API_KEY=...
```

## Run scanner

```bash
cp config.example.yaml config.yaml
python -m csp_radar.scanner --config config.yaml
```

## Run dashboard

Alpaca bridge mode uses the existing Investor paper credentials when present and keeps the app read-only.

```bash
python -m csp_radar.dashboard --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

Dashboard endpoints:

- `GET /api/reports` — list saved scans.
- `GET /api/report` — latest summarized scan.
- `POST /api/scan` — run a fresh market-data scan and save reports. No trades are placed.


## Internet deployment

This repo is ready for Render/Railway/Fly-style deployment as a private read-only web dashboard.

Recommended Render setup:

1. Connect this GitHub repo to Render as a Web Service.
2. Build command: `pip install -r requirements.txt`
3. Start command: `python -m csp_radar.dashboard --host 0.0.0.0 --port $PORT`
4. Set environment variables in the host dashboard, not in GitHub:
   - `CSP_DASHBOARD_USER`
   - `CSP_DASHBOARD_PASSWORD`
   - `ALPACA_API_KEY`
   - `ALPACA_SECRET_KEY`
   - `ALPACA_DATA_BASE_URL=https://data.alpaca.markets/v2`
   - optional: `FINNHUB_API_KEY`

Security note: GitHub Pages is static and cannot safely hold broker/data API keys. Use a backend host with environment variables for live scans.
