from datetime import timedelta
import json

from test_pipeline import FRIDAY_EVENING, FakeFetcher, frame, universe

from idxquant.daily import main
from idxquant.store import Store


def run_daily(tmp_path, fetcher, now=FRIDAY_EVENING):
    args = ["--data", str(tmp_path / "db.sqlite"), "--out", str(tmp_path / "site")]
    return main(args, fetcher=fetcher, now=now, stocks=universe(["AAAA"]))


def today(tmp_path):
    return json.loads((tmp_path / "site" / "api" / "today.json").read_text(encoding="utf-8"))


def test_successful_refresh_exports_the_site(tmp_path):
    assert run_daily(tmp_path, FakeFetcher({"AAAA": frame(1)})) == 0
    assert today(tmp_path)["data_date"] == "2026-10-30"


def test_failed_refresh_still_exports_the_last_good_result(tmp_path):
    run_daily(tmp_path, FakeFetcher({"AAAA": frame(1)}))
    assert run_daily(tmp_path, FakeFetcher({})) == 1
    assert today(tmp_path)["data_date"] == "2026-10-30"
    assert today(tmp_path)["warnings"]


def test_first_run_with_no_data_fails_but_exports_an_empty_site(tmp_path):
    assert run_daily(tmp_path, FakeFetcher({})) == 1
    assert today(tmp_path)["picks"] == []


def test_database_is_kept_between_runs(tmp_path):
    run_daily(tmp_path, FakeFetcher({"AAAA": frame(1)}))
    assert Store(tmp_path / "db.sqlite").latest_snapshot()["data_date"] == "2026-10-30"


class Untouchable(FakeFetcher):
    """Fails the test if the refresh asks Yahoo for anything."""

    def fetch_prices(self, ticker, years=10):
        raise AssertionError("A run with nothing to do shouldn't fetch prices")


def run_scheduled(tmp_path, fetcher, now):
    args = ["--data", str(tmp_path / "db.sqlite"), "--out", str(tmp_path / "site"), "--if-due"]
    return main(args, fetcher=fetcher, now=now, stocks=universe(["AAAA"]))


def test_a_backup_run_skips_when_todays_final_data_is_saved(tmp_path, capsys):
    run_daily(tmp_path, FakeFetcher({"AAAA": frame(1)}))
    assert run_scheduled(tmp_path, Untouchable({}), FRIDAY_EVENING + timedelta(hours=2)) == 0
    assert "Already up to date" in capsys.readouterr().out
    assert today(tmp_path)["data_date"] == "2026-10-30"


def test_a_scheduled_run_refreshes_when_nothing_is_saved_yet(tmp_path):
    assert run_scheduled(tmp_path, FakeFetcher({"AAAA": frame(1)}), FRIDAY_EVENING) == 0
    assert today(tmp_path)["data_date"] == "2026-10-30"


def test_a_scheduled_run_after_midnight_still_catches_up(tmp_path):
    run_daily(tmp_path, FakeFetcher({"AAAA": frame(1)}), now=FRIDAY_EVENING - timedelta(days=1))
    late = FRIDAY_EVENING + timedelta(hours=8)  # 02:00 WIB on Saturday, as when GitHub starts a run hours late
    assert run_scheduled(tmp_path, FakeFetcher({"AAAA": frame(1)}), late) == 0
    assert today(tmp_path)["data_date"] == "2026-10-30"
