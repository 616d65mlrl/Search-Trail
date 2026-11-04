"""URL 正規化（FR-03）のテスト。04 アルゴリズムの表の例をそのまま使う。"""

import pytest

from tadori.ingest.normalize import normalize_term, normalize_url


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # スキームとホストを小文字にし、http と https を同じとみなす
        ("HTTP://Zenn.dev/a", "https://zenn.dev/a"),
        ("http://zenn.dev/a", "https://zenn.dev/a"),
        # # 以降を消す
        ("https://github.com/textlens/lens#install", "https://github.com/textlens/lens"),
        # 追跡用の引数を消す
        ("https://example.com/a?utm_source=x&utm_medium=y", "https://example.com/a"),
        ("https://example.com/a?fbclid=1&gclid=2&ref=top&si=abc", "https://example.com/a"),
        # 残った引数を名前順に並べる
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        ("https://example.com/a?b=2&utm_source=x&a=1", "https://example.com/a?a=1&b=2"),
        # 末尾の / を消す（ルートは残す）
        ("https://example.com/lens/", "https://example.com/lens"),
        ("https://example.com/", "https://example.com/"),
        ("https://example.com", "https://example.com/"),
        # 標準のポート番号は書かない。それ以外は残す
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://127.0.0.1:8765/api", "https://127.0.0.1:8765/api"),
        # パスの大文字小文字は変えない（サイトによっては意味がある）
        ("https://github.com/aio-libs/AIOHTTP", "https://github.com/aio-libs/AIOHTTP"),
        # YouTube は v だけ残す
        ("https://www.youtube.com/watch?v=abc&list=PL1&t=30s", "https://www.youtube.com/watch?v=abc"),
    ],
)
def test_normalize_rules(before, after):
    assert normalize_url(before).key == after


@pytest.mark.parametrize(
    ("url", "key", "term"),
    [
        ("https://www.google.com/search?q=OCR&sca=abc", "search:ocr", "OCR"),
        ("https://www.google.co.jp/search?q=%E8%A1%A8%E7%B5%84+%E5%8F%AF%E8%A6%96%E5%8C%96",
         "search:表組 可視化", "表組 可視化"),
        ("https://www.bing.com/search?q=Python+%E8%BE%9E%E6%9B%B8&form=QBLH",
         "search:python 辞書", "Python 辞書"),
        ("https://duckduckgo.com/?q=aiohttp", "search:aiohttp", "aiohttp"),
        ("https://search.yahoo.co.jp/search?p=OCR", "search:ocr", "OCR"),
    ],
)
def test_search_pages_become_search_keys(url, key, term):
    norm = normalize_url(url)
    assert (norm.key, norm.search_term) == (key, term)


def test_search_engine_without_term_is_a_normal_page():
    # 検索語の無い google.com/search は、普通のページとして扱う
    assert normalize_url("https://www.google.com/search").key == "https://www.google.com/search"


def test_google_other_pages_are_not_search():
    assert normalize_url("https://www.google.com/maps?q=tokyo").key == "https://www.google.com/maps?q=tokyo"


def test_domain_is_lowercase_host():
    assert normalize_url("HTTPS://Zenn.DEV/a").domain == "zenn.dev"


def test_non_http_urls_only_drop_fragment():
    assert normalize_url("file:///C:/docs/a.pdf#page=3").key == "file:///C:/docs/a.pdf"


def test_normalize_term():
    # 全角英数字を半角に、小文字に、空白を1つに
    assert normalize_term("  ＯＣＲ　 作り方 ") == "ocr 作り方"
