"""取り込まない訪問の判定と、除外リストとの照合（FR-16）のテスト。"""

import pytest

from tadori.ingest.chrome import ChromeVisit
from tadori.ingest.exclude import matches_exclusion, skip_reason


def _visit(url, transition=0, hidden=False):
    return ChromeVisit(
        chrome_visit_id=1, url_id=1, url=url, title=None, hidden=hidden, visited_at=0,
        duration_ms=0, transition=transition, from_visit=None, opener_visit=None,
        synced=False, search_term=None,
    )


@pytest.mark.parametrize(
    ("visit", "reason"),
    [
        (_visit("https://example.com/"), None),
        (_visit("https://www.youtube.com/embed/x", transition=3), "subframe"),
        (_visit("https://example.com/frame", transition=4 | 0x30000000), "subframe"),
        (_visit("chrome://settings/"), "internal"),
        (_visit("chrome-extension://abc/popup.html"), "internal"),
        (_visit("about:blank"), "internal"),
        (_visit("https://accounts.example.com/rotate", hidden=True), "hidden"),
        # ローカルのファイル（PDF など）は調べ物の一部になりうるので取り込む
        (_visit("file:///C:/docs/a.pdf"), None),
    ],
)
def test_skip_reason(visit, reason):
    assert skip_reason(visit) == reason


@pytest.mark.parametrize(
    ("pattern", "domain", "url_norm", "expected"),
    [
        # ドメインそのもの
        ("mail.google.com", "mail.google.com", "https://mail.google.com/mail/u/0", True),
        ("mail.google.com", "www.google.com", "https://www.google.com/", False),
        # *. はそのドメイン自身と、その下のすべて
        ("*.bank.example", "bank.example", "https://bank.example/", True),
        ("*.bank.example", "www.bank.example", "https://www.bank.example/login", True),
        ("*.bank.example", "notbank.example", "https://notbank.example/", False),
        # 大文字で書いても一致する
        ("Mail.Google.com", "mail.google.com", "https://mail.google.com/", True),
        # / を含む型は「ドメイン/パス」として比べる。スキームは書いても書かなくてもよい
        ("example.com/private/*", "example.com", "https://example.com/private/a", True),
        ("https://example.com/private/*", "example.com", "https://example.com/private/a", True),
        ("example.com/private/*", "example.com", "https://example.com/public/a", False),
        # 空の行は何にも一致しない
        ("  ", "example.com", "https://example.com/", False),
    ],
)
def test_matches_exclusion(pattern, domain, url_norm, expected):
    assert matches_exclusion(pattern, domain, url_norm) is expected
