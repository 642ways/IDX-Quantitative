from datetime import datetime, timedelta, timezone

import pytest

from idxquant import news
from idxquant.config import CONFIG

WIB = timezone(timedelta(hours=7))
NOW = datetime(2026, 11, 8, 18, 0, tzinfo=WIB)


def item(title, days_ago=1, source="Contoh"):
    published = (NOW - timedelta(days=days_ago)).astimezone(timezone.utc)
    return {"title": title, "source": source, "link": "https://example.com/x", "published": published.isoformat()}


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Saham AAAA melonjak 8% setelah laba tumbuh", 1),
        ("Asing borong saham AAAA, inflow Rp 200 miliar", 1),
        ("Saham AAAA anjlok, asing jadi top net sell", -1),
        ("OJK jatuhkan denda terkait kasus saham AAAA", -1),
        ("AAAA umumkan jadwal RUPS tahunan", 0),
        ("Saham AAAA tidak naik meski laba tumbuh", 0),
        ("Harga saham AAAA belum pulih", -1),
    ],
)
def test_tone_reads_the_direction_of_a_headline(title, expected):
    assert news.tone(title) == expected


def test_a_two_sided_headline_is_read_for_the_stock_it_names():
    title = "Asing borong BBBB dan lepas AAAA pekan ini"
    assert news.tone(title, "AAAA", "Contoh") == -1
    assert news.tone(title, "BBBB", "Lain") == 1


def test_the_market_falling_does_not_count_against_a_stock_only_mentioned_nearby():
    assert news.tone("IHSG berpotensi melemah, pantau saham AAAA hari ini", "AAAA", "Contoh") == 0


def test_a_recommendation_list_reads_as_positive_for_each_stock_in_it():
    assert news.tone("Rekomendasi saham hari ini: BBBB, AAAA, CCCC", "AAAA", "Contoh") == 1


def test_a_cut_price_target_reads_as_negative():
    assert news.tone("Analis pangkas target harga saham AAAA", "AAAA", "Contoh") == -1


def test_only_headlines_naming_the_stock_are_kept():
    items = [
        item("Saham AAAA menguat di sesi pertama"),
        item("Contoh Makmur Abadi raup laba besar"),
        item("Lima saham pilihan analis pekan ini"),
    ]
    found = news.summarise(items, "AAAA", "Contoh Makmur Abadi", NOW)
    assert [headline["title"] for headline in found["items"]] == ["Saham AAAA menguat di sesi pertama", "Contoh Makmur Abadi raup laba besar"]


def test_a_ticker_inside_another_word_does_not_count():
    found = news.summarise([item("Saham AAAAB naik tajam")], "AAAA", "Contoh", NOW)
    assert found is None


def test_the_same_story_from_two_outlets_counts_once():
    items = [item("Saham AAAA menguat 3 persen", source="Satu"), item("Saham AAAA Menguat 3 Persen", source="Dua")]
    assert news.summarise(items, "AAAA", "Contoh", NOW)["count"] == 1


def test_only_the_recent_window_counts_toward_the_tone():
    items = [item("Saham AAAA melonjak", days_ago=1), item("Saham AAAA anjlok", days_ago=CONFIG.news_days + 2)]
    found = news.summarise(items, "AAAA", "Contoh", NOW)
    assert found["count"] == 1
    assert found["positive"] == 1 and found["negative"] == 0
    assert found["tone"] == pytest.approx(1.0)


def test_tone_balances_rising_and_falling_headlines():
    items = [item("Saham AAAA melonjak"), item("Saham AAAA menguat lagi"), item("Saham AAAA anjlok"), item("AAAA gelar RUPS")]
    found = news.summarise(items, "AAAA", "Contoh", NOW)
    assert (found["positive"], found["negative"], found["neutral"]) == (2, 1, 1)
    assert found["tone"] == pytest.approx(0.25)


def test_newest_headlines_come_first_and_the_list_is_capped():
    items = [item(f"Saham AAAA naik hari ke-{n}", days_ago=n / 10) for n in range(20)]
    found = news.summarise(items, "AAAA", "Contoh", NOW)
    assert len(found["items"]) == news.MAX_ITEMS
    assert found["items"][0]["title"] == "Saham AAAA naik hari ke-0"


def test_source_suffix_is_removed_from_the_title():
    assert news.clean_title("Saham AAAA naik - Kontan", "Kontan") == "Saham AAAA naik"


def test_no_headlines_give_nothing():
    assert news.summarise([], "AAAA", "Contoh", NOW) is None
