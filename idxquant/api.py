"""Serves the latest snapshot to the page. Refreshes run in a background thread."""
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from idxquant import pipeline
from idxquant.config import CONFIG
from idxquant.factors import MIN_SECTOR_SIZE
from idxquant.history import price_history
from idxquant.pipeline import WIB
from idxquant.plays import SHORT_BREAKOUT_DAYS, SHORT_TREND_DAYS

STATIC = Path(__file__).with_name("static")
RETRY_AFTER = timedelta(minutes=10)
SCHEDULE_SECONDS = 600
EMPTY = {
    "data_date": None,
    "ran_at": None,
    "picks": [],
    "stocks": {},
    "regime": None,
    "market_type": None,
    "concentration": None,
    "rotation": None,
    "diffusion": None,
    "backtest": None,
    "skipped": [],
    "warnings": [],
}


class Refresher:
    def __init__(self, store, runner):
        self.store = store
        self.runner = runner
        self.lock = threading.Lock()
        self.running = False
        self.warnings: list[str] = []
        self.last_attempt: datetime | None = None

    def start(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.last_attempt = datetime.now(WIB)
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self) -> None:
        try:
            self.warnings = self.runner(self.store).get("warnings", [])
        except Exception as error:
            self.warnings = [f"Refresh failed ({error}). Showing the last good result."]
        finally:
            with self.lock:
                self.running = False

    def recently_tried(self) -> bool:
        return self.last_attempt is not None and datetime.now(WIB) - self.last_attempt < RETRY_AFTER

    def refresh_if_due(self) -> None:
        due = pipeline.needs_refresh(datetime.now(WIB), self.store.latest_snapshot())
        if due and not self.recently_tried():
            self.start()


def today_payload(snapshot: dict | None, warnings: list[str] | None = None, refreshing: bool = False) -> dict:
    snapshot = snapshot or EMPTY
    return {key: snapshot.get(key) for key in EMPTY} | {
        "warnings": warnings or snapshot["warnings"],
        "refreshing": refreshing,
    }


def stock_payload(store, snapshot: dict | None, ticker: str) -> dict | None:
    """The stock's page with its price history, read from the saved prices up to the results date."""
    page = (snapshot or EMPTY)["stocks"].get(ticker)
    if page is None:
        return None
    return page | {"history": price_history(store.load_prices(ticker), until=snapshot.get("data_date"))}


def results_payload(store) -> dict:
    snapshots = store.all_snapshots()
    latest = snapshots[-1] if snapshots else EMPTY
    tickers = {pick["ticker"] for snapshot in snapshots for pick in snapshot["picks"]}
    prices = {ticker: store.load_prices(ticker) for ticker in tickers}
    return {
        "regime": latest.get("regime"),
        "market_type": latest.get("market_type"),
        "backtest": latest.get("backtest"),
        "backtest_at": latest.get("backtest_at"),
        "models": latest.get("models"),
        "diffusion": latest.get("diffusion"),
        "track_record": pipeline.track_record(snapshots, prices),
        "skipped": latest.get("skipped", []),
        "universe_size": latest.get("universe_size"),
    }


def methods_payload() -> dict:
    return asdict(CONFIG) | {
        "min_sector_size": MIN_SECTOR_SIZE,
        "short_trend_days": SHORT_TREND_DAYS,
        "short_breakout_days": SHORT_BREAKOUT_DAYS,
    }


def _start_schedule(refresher: Refresher, seconds: float) -> threading.Event:
    """Keeps the data fresh when nobody has the page open."""
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            try:
                refresher.refresh_if_due()
            except Exception:
                pass  # A failed check mustn't end the schedule, and the next one tries again
            stop.wait(seconds)

    threading.Thread(target=watch, daemon=True).start()
    return stop


def create_app(
    store,
    runner=pipeline.run,
    auto_refresh: bool = True,
    limit_refresh: bool = False,
    scheduled: bool = False,
    schedule_seconds: float = SCHEDULE_SECONDS,
) -> FastAPI:
    app = FastAPI(title="IDX Quant", docs_url=None, redoc_url=None, openapi_url=None)
    refresher = Refresher(store, runner)
    if scheduled:
        app.state.stop_schedule = _start_schedule(refresher, schedule_seconds)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/today")
    def today():
        if auto_refresh:
            refresher.refresh_if_due()
        return today_payload(store.latest_snapshot(), refresher.warnings, refresher.running)

    @app.get("/api/stock/{ticker}")
    def stock(ticker: str):
        page = stock_payload(store, store.latest_snapshot(), ticker)
        if page is None:
            raise HTTPException(status_code=404, detail="Stock not in today's list")
        return page

    @app.get("/api/results")
    def results():
        return results_payload(store)

    @app.post("/api/refresh")
    def refresh():
        if limit_refresh and refresher.recently_tried():
            return {"started": False}
        return {"started": refresher.start()}

    @app.get("/api/refresh/status")
    def refresh_status():
        return {"running": refresher.running}

    @app.get("/api/methods")
    def methods():
        return methods_payload()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
