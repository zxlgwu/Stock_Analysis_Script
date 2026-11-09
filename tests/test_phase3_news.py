from datetime import datetime, timezone

from stock_agent.core.config import Settings
from stock_agent.core.models import RawArticle, Relation, Security
from stock_agent.db.repository import Database
from stock_agent.ingest.news.finnhub import FinnhubNews
from stock_agent.ingest.news.gdelt import GdeltNews
from stock_agent.ingest.news.rss import RssNews
from stock_agent.ingest.news.sec_edgar import Edgar8K, critical_item_types
from stock_agent.jobs.news import collect_articles
from stock_agent.processing.dedupe import cluster_vectors
from stock_agent.processing.entity_linking import link_entities, mentioned_tickers
from stock_agent.processing.normalize import canonicalize_url, drop_exact_duplicates, to_stored
from stock_agent.processing.prefilter import is_low_value

_FINNHUB = [
    {
        "datetime": 1762470000,
        "headline": "Apple Inc. raises services guidance",
        "summary": "Services growth stays above the prior outlook.",
        "url": "https://news.example.com/aapl?utm_source=wire",
        "related": "AAPL",
    }
]

_SEC = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>8-K - Apple Inc. (0000320193) (Filer)</title>
    <link href="https://www.sec.gov/Archives/edgar/data/320193/example.htm"/>
    <updated>2026-11-06T21:00:00-05:00</updated>
    <summary>Item 4.02 Non-Reliance on Previously Issued Financial Statements</summary>
  </entry>
</feed>
"""

_GDELT = {
    "articles": [
        {
            "url": "https://example.com/tariff",
            "title": "New tariff on imported chips",
            "seendate": "20261106T210000Z",
        }
    ]
}

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Fed holds interest rates</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/example.htm</link>
    <description>The Committee left the policy rate unchanged.</description>
    <pubDate>Fri, 06 Nov 2026 21:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


def test_each_source_parses_a_recorded_payload():
    finnhub = FinnhubNews.parse(_FINNHUB)[0]
    assert finnhub.tickers == ("AAPL",)
    assert finnhub.title.startswith("Apple")
    assert canonicalize_url(finnhub.url) == "https://news.example.com/aapl"

    filing = Edgar8K.parse(_SEC, {"320193": "AAPL"})[0]
    assert filing.source == "sec_edgar_8k"
    assert filing.tickers == ("AAPL",)
    assert "4.02" in filing.body

    gdelt = GdeltNews.parse(_GDELT)[0]
    assert gdelt.source == "gdelt"
    assert gdelt.published_at == datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc)

    rss = RssNews.parse(_RSS)[0]
    assert rss.source == "rss"
    assert rss.title == "Fed holds interest rates"


def test_sec_filings_are_kept_when_the_company_is_outside_the_universe():
    class _Response:
        text = _SEC

        def raise_for_status(self):
            return None

    class _Session:
        def get(self, *args, **kwargs):
            return _Response()

    articles = Edgar8K(_Session()).fetch(datetime(2026, 11, 1, tzinfo=timezone.utc), [])
    assert len(articles) == 1
    assert articles[0].tickers == ()
    assert "Apple Inc." in articles[0].title


def test_exact_duplicates_and_near_duplicates():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    raw = RawArticle("finnhub", "https://news.example.com/a", "Same story", "Body", now)
    stored = to_stored(raw, now)
    assert drop_exact_duplicates([stored, stored], set()) == [stored]
    assert drop_exact_duplicates([stored], {stored.content_hash}) == []
    groups = cluster_vectors(
        ["a", "b", "c"],
        [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]],
        threshold=0.9,
    )
    assert groups[0][:2] == ["a", "b"]
    assert ["c"] in groups


def test_prefilter_keeps_filings_and_drops_recaps():
    assert is_low_value("5 stocks to watch this week", "", "finnhub")[0] is True
    assert is_low_value("Market recap: stocks to watch", "Item 4.02", "sec_edgar_8k")[0] is False


def test_rss_parses_feeds_with_a_byte_order_mark():
    feed = (
        "\ufeff<?xml version=\"1.0\" encoding=\"utf-8\"?><rss><channel><item>"
        "<title>Fed holds rates</title><link>https://example.com/fed</link>"
        "<pubDate>Fri, 06 Nov 2026 18:00:00 GMT</pubDate></item></channel></rss>"
    )
    assert RssNews.parse(feed)[0].title == "Fed holds rates"
    assert RssNews.parse(feed.encode("utf-8"))[0].body == "Fed holds rates"


def test_article_text_keeps_story_paragraphs():
    from stock_agent.ingest.news.article_text import extract_text

    page = (
        "<html><nav><p>Markets Business Investing Tech Politics Video Watchlist</p></nav>"
        "<article><p>Delta raised its holiday outlook as corporate travel demand recovered.</p>"
        "<p>Subscribe to our newsletter for the latest updates every morning.</p>"
        "<p>Higher premium-cabin sales lifted unit revenue by four percent.</p></article></html>"
    )
    text = extract_text(page)
    assert "corporate travel demand" in text
    assert "premium-cabin" in text
    assert "newsletter" not in text


def test_each_source_keeps_its_own_window(tmp_path):
    from datetime import timedelta

    from stock_agent.jobs.news import _source_since

    db = Database(tmp_path / "test.db")
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    fresh = to_stored(RawArticle("rss", "https://example.com/a", "Fresh", "Body", now - timedelta(hours=1)), now)
    db.upsert_articles([fresh])
    assert _source_since(db, "rss", now) == now - timedelta(hours=7)
    assert _source_since(db, "sec_edgar_8k", now) == now - timedelta(days=7)
    db.close()


def test_priority_ranks_company_news_above_personal_finance():
    from stock_agent.processing.priority import story_priority

    company = story_priority(
        "Delta raises outlook", "Airline demand improved.", "rss", [("DAL", "mentioned")]
    )
    personal = story_priority(
        "I'm 55 and my husband inherited money. Should I buy an annuity?", "", "rss", []
    )
    cover = story_priority(
        "8-K - Example Corp", "Item 5.02: Departure of Directors. Item 9.01: Exhibits", "sec_edgar_8k", []
    )
    results = story_priority(
        "8-K - Example Corp", "Item 2.02: Results of Operations", "sec_edgar_8k", [("EX", "mentioned")]
    )
    assert company > personal
    assert results > cover


def test_exchange_suffix_is_not_a_us_ticker():
    securities = [
        Security("DE", "NYSE", "Deere & Company", sector="Industrials"),
        Security("AAPL", "NASDAQ", "Apple Inc.", sector="Information Technology"),
        Security("T", "NYSE", "AT&T"),
        Security("TGT", "NYSE", "Target Corporation"),
        Security("ORCL", "NYSE", "Oracle Corporation"),
        Security("DAL", "NYSE", "Delta Air Lines"),
        Security("NOW", "NYSE", "ServiceNow"),
        Security("JNJ", "NYSE", "Johnson & Johnson"),
        Security("JCI", "NYSE", "Johnson Controls"),
        Security("XYZ", "NYSE", "Block, Inc."),
    ]
    assert mentioned_tickers("Zalando (ZAL . DE) grew its wholesale business.", securities) == []
    assert mentioned_tickers("8-K - Local Bounti Corporation/DE (0001840780) (Filer)", securities) == []
    assert mentioned_tickers("Neutral Exide ; target of Rs 381 : Motilal Oswal", securities) == []
    assert mentioned_tickers("Meet the Oracle of Uga and Nigeria Warren Buffett", securities) == []
    assert mentioned_tickers("Deere & Company raised its equipment outlook.", securities) == ["DE"]
    assert mentioned_tickers("Why AT & T Stock Slumped in October", securities) == ["T"]
    assert mentioned_tickers("Delta SkyMiles American Express credit card current offers", securities) == ["DAL"]
    waste = [Security("WM", "NYSE", "Waste Management")]
    assert mentioned_tickers("Dont waste the LDC graduation extension", waste) == []
    assert mentioned_tickers("Democrats identified tariffs as a main target following the election.", securities) == []
    assert mentioned_tickers("Abdul El-Sayed told MS NOW's Morning Joe Thursday.", securities) == []
    assert mentioned_tickers("Republicans used the filibuster to block legislation.", securities) == []
    assert mentioned_tickers("Kit Johnson, a senior tax manager, commented on tariffs.", securities) == []
    assert mentioned_tickers("Target Corporation cut its holiday outlook.", securities) == ["TGT"]
    assert mentioned_tickers("Johnson & Johnson raised pharmaceutical guidance.", securities) == ["JNJ"]
    filing = link_entities(
        "8-K - Dutch Bros Inc. Item 7.01: Regulation FD Disclosure",
        [Security("JPM", "NYSE", "JPMorgan Chase", sector="Financials")],
        [],
    )
    assert filing == []


def test_filing_cik_links_only_the_filer():
    securities = [
        Security("FOXA", "NASDAQ", "Fox Corporation (Class A)", cik="0001754301"),
        Security("FOX", "NASDAQ", "Fox Corporation (Class B)", cik="0001754301"),
        Security("TRV", "NYSE", "Travelers Companies (The)", cik="0000086312"),
    ]
    assert mentioned_tickers("8-K - Fox Corp (0001754301) (Filer). Item 5.02", securities) == ["FOXA"]
    lookalikes = [
        Security("DLR", "NYSE", "Digital Realty Trust"),
        Security("O", "NYSE", "Realty Income Corporation"),
    ]
    assert mentioned_tickers("8-K - Hawkeye Digital, Inc. (0001750777) (Filer)", lookalikes) == []
    assert mentioned_tickers("8-K - ACRES Commercial Realty Corp. (0001332551) (Filer)", lookalikes) == []


def test_outside_firm_pulls_in_its_customers_and_rivals():
    securities = [
        Security("AAPL", "NASDAQ", "Apple Inc.", industry="Technology Hardware"),
        Security("HPQ", "NYSE", "HP Inc.", industry="Technology Hardware"),
        Security("KO", "NYSE", "Coca-Cola Company", industry="Soft Drinks"),
        Security("CRWD", "NASDAQ", "CrowdStrike", sector="Information Technology"),
        Security("JPM", "NYSE", "JPMorgan Chase", sector="Financials"),
    ]
    foxconn = link_entities("India visits a Foxconn facility to discuss electronics.", securities, [])
    assert ("AAPL", "expanded") in foxconn
    assert ("HPQ", "expanded") in foxconn
    assert all(ticker != "KO" for ticker, _link in foxconn)
    cyber = link_entities("AI cyber resilience and the trust gap", securities, [])
    assert ("CRWD", "exposure") in cyber
    banks = link_entities("Here is how these 6 big bank stocks make their money", securities, [])
    assert ("JPM", "exposure") in banks


def test_macro_story_adds_exposed_companies():
    securities = [
        Security("XOM", "NYSE", "Exxon Mobil Corporation", sector="Energy"),
        Security("AAPL", "NASDAQ", "Apple Inc.", sector="Information Technology"),
    ]
    links = link_entities("Brent crude oil price jumped after the supply cut.", securities, [])
    assert ("XOM", "exposure") in links
    assert all(ticker != "AAPL" for ticker, _link in links)


def test_same_industry_peer_is_a_candidate():
    securities = [
        Security("NVDA", "NASDAQ", "NVIDIA Corporation", sector="Information Technology", industry="Semiconductors"),
        Security("AMD", "NASDAQ", "Advanced Micro Devices", sector="Information Technology", industry="Semiconductors"),
        Security("KO", "NYSE", "Coca-Cola Company", sector="Consumer Staples", industry="Soft Drinks"),
    ]
    links = link_entities("NVIDIA Corporation raised its data-center outlook.", securities, [])
    assert ("NVDA", "mentioned") in links
    assert ("AMD", "exposure") in links
    assert all(ticker != "KO" for ticker, _link in links)


def test_entity_linking_expands_suppliers():
    securities = [
        Security("NVDA", "NASDAQ", "NVIDIA Corporation"),
        Security("AVGO", "NASDAQ", "Broadcom Inc."),
    ]
    relations = [
        Relation("AVGO", "NVDA", "supplier_of", evidence="10-K", confidence=0.7, dst_ticker="NVDA")
    ]
    links = link_entities("NVIDIA Corporation increased chip orders.", securities, relations)
    assert ("NVDA", "mentioned") in links
    assert ("AVGO", "expanded") in links


def test_critical_filing_detector_and_daily_store(tmp_path):
    assert critical_item_types("8-K", "Item 4.02 non-reliance on prior financials") == ["non_reliance"]
    settings = Settings.load()
    from dataclasses import replace

    settings = replace(
        settings,
        root=tmp_path,
        database_path=tmp_path / "test.db",
        critical_filings=True,
    )
    db = Database(settings.database_path)
    db.sync_universe("sp500", [Security("AAPL", "NASDAQ", "Apple Inc.", cik="0000320193")], datetime(2026, 11, 6).date())

    class _Source:
        name = "sec_edgar_8k"

        def fetch(self, since, securities):
            return Edgar8K.parse(_SEC, {"320193": "AAPL"})

    first = collect_articles(
        settings,
        db,
        db.active_members("sp500"),
        [_Source()],
        since=datetime(2026, 11, 1, tzinfo=timezone.utc),
        now=datetime(2026, 11, 7, tzinfo=timezone.utc),
    )
    second = collect_articles(
        settings,
        db,
        db.active_members("sp500"),
        [_Source()],
        since=datetime(2026, 11, 1, tzinfo=timezone.utc),
        now=datetime(2026, 11, 7, tzinfo=timezone.utc),
    )
    assert first["stored"] == 1
    assert first["alerts"] == 1
    assert second["stored"] == 0
    stored = db.unclustered_articles()
    assert stored[0].source == "sec_edgar_8k"
    assert "utm_" not in stored[0].url
    db.close()
