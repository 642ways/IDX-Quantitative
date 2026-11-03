import json

from idxquant.api import methods_payload, results_payload, today_payload
from idxquant.export import export_site
from idxquant.store import Store


def snapshot():
    return {
        "run_date": "2026-11-03",
        "data_date": "2026-11-03",
        "ran_at": "2026-11-03T18:05:00+07:00",
        "picks": [{"ticker": "BBCA", "kind": "long", "entry_high": 1000, "target": 1300, "stop": 750, "rank": 1}],
        "stocks": {"BBCA": {"ticker": "BBCA", "plays": []}, "ADRO": {"ticker": "ADRO", "plays": []}},
        "regime": {"label": "Stressed"},
        "market_type": {"label": "Panic"},
        "backtest": {"short": {"trades": 4}},
        "skipped": [],
        "warnings": [],
    }


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def exported(tmp_path, with_snapshot=True):
    store = Store(tmp_path / "db.sqlite")
    if with_snapshot:
        store.save_snapshot("2026-11-03", snapshot())
    out = tmp_path / "site"
    export_site(store, out)
    return store, out


def test_today_matches_what_the_server_would_send(tmp_path):
    store, out = exported(tmp_path)
    assert read(out / "api" / "today.json") == today_payload(store.latest_snapshot())


def test_today_is_never_shown_as_refreshing(tmp_path):
    _, out = exported(tmp_path)
    assert read(out / "api" / "today.json")["refreshing"] is False


def test_results_and_methods_are_exported(tmp_path):
    store, out = exported(tmp_path)
    assert read(out / "api" / "results.json") == results_payload(store)
    assert read(out / "api" / "methods.json") == methods_payload()


def test_every_stock_gets_its_own_page(tmp_path):
    _, out = exported(tmp_path)
    assert read(out / "api" / "stock" / "BBCA.json")["ticker"] == "BBCA"
    assert (out / "api" / "stock" / "ADRO.json").exists()


def test_page_is_switched_to_static_mode(tmp_path):
    _, out = exported(tmp_path)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert '<meta name="idx-mode" content="static">' in page
    assert "Model output, not personal advice" in page


def test_scripts_and_styles_are_copied(tmp_path):
    _, out = exported(tmp_path)
    for name in ("app.js", "methods.js", "style.css"):
        assert (out / "static" / name).exists()


def test_vercel_only_builds_the_site_branch(tmp_path):
    _, out = exported(tmp_path)
    config = read(out / "vercel.json")
    assert "site" in config["ignoreCommand"]


def test_empty_database_still_exports_a_working_site(tmp_path):
    _, out = exported(tmp_path, with_snapshot=False)
    assert read(out / "api" / "today.json")["picks"] == []
    assert list((out / "api" / "stock").iterdir()) == []


def test_exporting_again_removes_stocks_that_left_the_list(tmp_path):
    store, out = exported(tmp_path)
    smaller = snapshot()
    del smaller["stocks"]["ADRO"]
    store.save_snapshot("2026-11-04", smaller | {"run_date": "2026-11-04", "data_date": "2026-11-04"})
    export_site(store, out)
    assert not (out / "api" / "stock" / "ADRO.json").exists()


def test_exported_json_is_strict(tmp_path):
    _, out = exported(tmp_path)
    for path in (out / "api").rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda name: (_ for _ in ()).throw(ValueError(name)))
