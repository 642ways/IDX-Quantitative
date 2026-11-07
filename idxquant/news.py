"""Recent news headlines for each stock from Google News, with a rough tone read from the words used.

The tone counts words, it doesn't understand sentences: a headline with more rising words (naik,
menguat, borong) than falling ones (turun, anjlok, denda) reads as positive. It's shown as a rough guide
beside the headlines themselves, which link to the original articles.
"""
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from idxquant.config import CONFIG

FEED_URL = "https://news.google.com/rss/search"
SEARCH_DAYS = 14
MAX_ITEMS = 8
TIMEOUT_SECONDS = 15

# Words in Indonesian market headlines, by the direction they point. Stems are listed in the forms used.
POSITIVE = {
    "naik", "menaik", "kenaikan", "menguat", "penguatan", "melonjak", "lonjakan", "melejit", "meroket", "melesat",
    "terbang", "rebound", "pulih", "bangkit", "hijau", "cuan", "untung", "keuntungan", "tumbuh", "pertumbuhan",
    "raup", "borong", "memborong", "akumulasi", "diakumulasi", "serok", "diserok", "inflow", "buy", "beli",
    "buyback", "dividen", "tebar", "jagokan", "positif", "optimistis", "optimis", "menarik", "tertinggi",
    "outperform", "upgrade", "melambung", "berbalik", "ditopang", "topang", "surplus", "ekspansi",
    "rekomendasi", "rekomendasikan", "direkomendasikan", "gain", "koleksi", "dikoleksi", "mengoleksi",
    "penopang", "gainers", "bullish", "tancap",
}
NEGATIVE = {
    "turun", "menurun", "penurunan", "melemah", "pelemahan", "lemah", "anjlok", "rontok", "ambles", "ambrol",
    "merosot", "terjun", "terkoreksi", "koreksi", "tertekan", "tekanan", "merah", "jatuh", "longsor", "belur",
    "lepas", "dilepas", "jual", "sell", "outflow", "rugi", "kerugian", "merugi", "denda", "kasus", "gugatan",
    "digugat", "sanksi", "suspensi", "suspend", "gagal", "pailit", "bangkrut", "negatif", "pesimistis", "waspada",
    "terendah", "downgrade", "dihajar", "petaka", "ancaman", "terpuruk", "ambruk", "defisit", "batal", "boncos",
    "melepas", "pangkas", "dipangkas", "memangkas", "losers", "bearish", "tertunduk", "minggir",
}
NEGATORS = {"tidak", "tak", "belum", "bukan"}
NEGATION_REACH = 2  # A negator flips the next sentiment word within this many words
# Words that make a clause about the whole market, not the stock it happens to mention
MARKET_WORDS = {"ihsg", "indeks", "lq45", "kompas100", "idx30", "idx80", "bursa"}
# Headlines join two stories with punctuation, or with "dan" before a new action ("borong BBCA dan lepas GOTO")
_ACTION = "|".join(sorted(POSITIVE | NEGATIVE))
CLAUSE_BREAK = re.compile(rf"[,;:!?|]|\s(?:saat|di tengah|meski|namun|tapi|sementara)\s|\sdan\s(?=(?:{_ACTION})\b)", re.IGNORECASE)
OTHER_TICKER = re.compile(r"(?<![A-Za-z0-9])[A-Z]{4}(?![A-Za-z0-9])")


def clean_title(title: str, source: str | None) -> str:
    """Google appends " - Outlet" to each title."""
    if source and title.endswith(f" - {source}"):
        return title[: -len(source) - 3].strip()
    return title.strip()


def _score(text: str) -> int:
    """Rising words minus falling ones, with a negator flipping the next one ("tidak naik")."""
    score, flip_until = 0, -1
    for position, word in enumerate(re.findall(r"[a-z]+", text.lower())):
        if word in NEGATORS:
            flip_until = position + NEGATION_REACH
            continue
        direction = 1 if word in POSITIVE else -1 if word in NEGATIVE else 0
        if direction and position <= flip_until:
            direction, flip_until = -direction, -1
        score += direction
    return score


def _about_something_else(clause: str, ticker: str) -> bool:
    words = set(re.findall(r"[a-z0-9]+", clause.lower()))
    return bool(words & MARKET_WORDS) or any(found != ticker for found in OTHER_TICKER.findall(clause))


def tone(title: str, ticker: str | None = None, name: str | None = None) -> int:
    """+1 if the headline leans positive for the stock, -1 if negative, 0 if neither or balanced.

    With a ticker, the clauses that name the stock are read first. If they carry no direction, the rest of
    the headline counts, except clauses about the whole market or another stock.
    """
    if ticker is None:
        score = _score(title)
    else:
        clauses = [clause for clause in CLAUSE_BREAK.split(title) if clause and clause.strip()]
        own = [clause for clause in clauses if _mentions(clause, ticker, name or ticker)]
        score = sum(_score(clause) for clause in own)
        if score == 0:
            rest = [c for c in clauses if c not in own and not _about_something_else(c, ticker)]
            score = sum(_score(clause) for clause in rest)
    return (score > 0) - (score < 0)


def fetch_headlines(ticker: str, name: str) -> list[dict] | None:
    """Headlines from the last two weeks that Google News matched to the ticker. None if the feed fails."""
    query = urllib.parse.urlencode({"q": f'"{ticker}" saham when:{SEARCH_DAYS}d', "hl": "id", "gl": "ID", "ceid": "ID:id"})
    request = urllib.request.Request(f"{FEED_URL}?{query}", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            root = ET.fromstring(response.read())
    except Exception:
        return None
    items = []
    for entry in root.findall("./channel/item"):
        try:
            published = parsedate_to_datetime(entry.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        source = entry.findtext("source")
        items.append(
            {
                "title": clean_title(entry.findtext("title") or "", source),
                "source": source,
                "link": entry.findtext("link"),
                "published": published.isoformat(),
            }
        )
    return items


def _mentions(title: str, ticker: str, name: str) -> bool:
    """Tickers are matched in capitals only, since some are ordinary words in lower case (BUMI, AUTO, BANK)."""
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])", title)) or name.lower() in title.lower()


def _story(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def summarise(items: list[dict] | None, ticker: str, name: str, now: datetime, cfg=CONFIG) -> dict | None:
    if not items:
        return None
    since = now - timedelta(days=cfg.news_days)
    seen, kept = set(), []
    for entry in sorted(items, key=lambda e: e["published"], reverse=True):
        published = datetime.fromisoformat(entry["published"])
        story = _story(entry["title"])
        if published < since or story in seen or not _mentions(entry["title"], ticker, name):
            continue
        seen.add(story)
        kept.append(entry | {"tone": tone(entry["title"], ticker, name)})
    if not kept:
        return None
    positive = sum(1 for entry in kept if entry["tone"] > 0)
    negative = sum(1 for entry in kept if entry["tone"] < 0)
    return {
        "count": len(kept),
        "positive": positive,
        "negative": negative,
        "neutral": len(kept) - positive - negative,
        "tone": (positive - negative) / len(kept),
        "days": cfg.news_days,
        "items": kept[:MAX_ITEMS],
    }
