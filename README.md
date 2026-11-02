# IDX Quant

A personal app that ranks Indonesian (IDX80) stocks after each trading day, using factor scores, statistical arbitrage, Monte Carlo simulation and market regime detection. Each pick comes with a playbook.

This is model output, not personal financial advice. It doesn't know your money or risk limits, and it can be wrong. The app has no login, so anyone with its link can open it. Don't publish the link: sharing recommendations publicly or with paying users may fall under Indonesian investment advice rules.

## Run it on your computer

On Windows, double-click `run.bat`. It sets everything up on the first run and opens http://127.0.0.1:8765.

## Run the tests

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
```

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `127.0.0.1` | Address to serve on. The Dockerfile sets `0.0.0.0`. |
| `PORT` | `8765` | Port to serve on. Most hosts set this for you. |
| `DATA_PATH` | `data/idxquant.sqlite` | Database location. The Dockerfile sets `/data/idxquant.sqlite`. |

On any address other than this computer, the app runs in server mode. It refreshes by itself, checking every 10 minutes and fetching new data after 17:00 WIB on weekdays, and the Refresh button runs at most once every 10 minutes.

## Deploy

The app needs one always-on instance and persistent storage. Don't run more than one copy, because they'd share one SQLite database. Plans that sleep when idle or wipe files between restarts won't work.

1. Put the project in a private GitHub repository.
2. Create a service from that repository on a host that builds Dockerfiles. Start with about 1 GB of memory.
3. Attach a persistent volume mounted at `/data`.
4. Set the health check path to `/health`.
5. Run this in the host's shell to confirm Yahoo isn't blocking the server:

   ```bash
   python -m idxquant.check
   ```

6. Open the site and wait for the first fetch to finish. It takes a few minutes.

If the check fails, Yahoo is probably blocking the host's addresses. Try another host or region, or use a paid data source by replacing `idxquant/yahoo.py`, which is the only module that fetches data.

## Keeping it up to date

- **Stock list:** edit `idxquant/universe.csv` by hand when the IDX80 changes. The next change is due after 29 January 2027.
- **Rules:** thresholds are in `idxquant/config.py`.
