"""Starts IDX Quant. Locally it opens the browser, and on a server it follows the environment settings."""
from pathlib import Path
import sys
import threading
import warnings
import webbrowser

# Lets the system Python run the app when the .venv launcher can't start on this PC
LOCAL_PACKAGES = Path(__file__).parent / ".venv" / "Lib" / "site-packages"
if LOCAL_PACKAGES.is_dir():
    sys.path.insert(0, str(LOCAL_PACKAGES))

import uvicorn

from idxquant.api import create_app
from idxquant.settings import load_settings
from idxquant.store import Store


def main() -> None:
    warnings.simplefilter("ignore")  # yfinance is noisy under pandas 3
    settings = load_settings()
    app = create_app(Store(settings.data_path), limit_refresh=settings.is_server, scheduled=settings.is_server)
    if not settings.is_server:
        threading.Timer(1.0, webbrowser.open, [f"http://{settings.host}:{settings.port}"]).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
