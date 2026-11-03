"""Writes the app as a static website: the same pages, reading daily JSON files instead of a server."""
import json
from pathlib import Path
import shutil

from idxquant.api import STATIC, methods_payload, results_payload, today_payload

SERVER_MODE = '<meta name="idx-mode" content="server">'
STATIC_MODE = '<meta name="idx-mode" content="static">'
VERCEL_CONFIG = {
    # Vercel builds every pushed branch, so anything but the site branch is skipped
    "ignoreCommand": '[ "$VERCEL_GIT_COMMIT_REF" != "site" ]',
    "headers": [
        {
            "source": "/api/(.*)",
            "headers": [{"key": "Cache-Control", "value": "public, max-age=0, must-revalidate"}],
        }
    ],
}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")


def export_site(store, out: Path) -> None:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out / "static")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    (out / "index.html").write_text(page.replace(SERVER_MODE, STATIC_MODE), encoding="utf-8")

    snapshot = store.latest_snapshot()
    api = out / "api"
    _write_json(api / "today.json", today_payload(snapshot))
    _write_json(api / "results.json", results_payload(store))
    _write_json(api / "methods.json", methods_payload())
    (api / "stock").mkdir(parents=True, exist_ok=True)
    for ticker, stock in (snapshot or {}).get("stocks", {}).items():
        _write_json(api / "stock" / f"{ticker}.json", stock)
    _write_json(out / "vercel.json", VERCEL_CONFIG)
