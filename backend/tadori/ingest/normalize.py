"""URL の正規化（FR-03、04 アルゴリズムの「URL 正規化のルール」）。

同じページを指す URL を、1つの書き方（鍵）に揃える。検索結果ページは
`search:検索語` という鍵にし、検索エンジンや余計な引数の違いを無視する。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

# 消す追跡用の引数。utm_ で始まるものも消す
TRACKING_PARAMS = {"fbclid", "gclid", "ref", "si"}
TRACKING_PREFIXES = ("utm_",)

# 意味のある引数だけを残すサイト（ホスト → 残す引数の名前）
SITE_KEEP_PARAMS: dict[str, set[str]] = {
    "youtube.com": {"v"},
    "www.youtube.com": {"v"},
    "m.youtube.com": {"v"},
}

# 検索結果ページの見分け方（ホストの形、パス、検索語の引数名）
SEARCH_ENGINES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"^(www\.)?google\.[a-z.]+$"), "/search", "q"),
    (re.compile(r"^(www\.)?bing\.com$"), "/search", "q"),
    (re.compile(r"^(html\.)?duckduckgo\.com$"), "/", "q"),
    (re.compile(r"^search\.yahoo\.co\.jp$"), "/search", "p"),
]

DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class NormalizedUrl:
    key: str  # pages.url_norm に入れる値
    domain: str
    search_term: str | None = None  # 検索結果ページのときだけ、URL から取り出した検索語


def normalize_term(term: str) -> str:
    """検索語の表記ゆれを揃える（全角英数字を半角に、小文字に、空白を1つに）。"""
    return " ".join(unicodedata.normalize("NFKC", term).lower().split())


def _is_tracking(name: str) -> bool:
    return name in TRACKING_PARAMS or name.startswith(TRACKING_PREFIXES)


def normalize_url(url: str) -> NormalizedUrl:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()

    if scheme not in DEFAULT_PORTS:
        # http(s) 以外（file: など）は、# 以降を消すだけにする
        return NormalizedUrl(urlunsplit(parts._replace(fragment="")), host)

    query = parse_qsl(parts.query, keep_blank_values=True)

    path = parts.path or "/"
    for pattern, search_path, param in SEARCH_ENGINES:
        if pattern.match(host) and path.rstrip("/") == search_path.rstrip("/"):
            raw = next((v for k, v in query if k == param), "")
            term = normalize_term(raw)
            if term:
                return NormalizedUrl(f"search:{term}", host, raw.strip())

    # http と https は同じとみなし、https に揃える。標準のポート番号は書かない
    netloc = host
    if parts.port and parts.port not in DEFAULT_PORTS.values():
        netloc = f"{host}:{parts.port}"

    keep = SITE_KEEP_PARAMS.get(host)
    query = [(k, v) for k, v in query if (k in keep if keep is not None else not _is_tracking(k))]
    # 名前順に並べる（同じ名前の引数どうしは、元の順番を保つ）
    query.sort(key=lambda kv: kv[0])

    if path != "/":
        path = path.rstrip("/") or "/"

    key = urlunsplit(("https", netloc, path, urlencode(query, quote_via=quote), ""))
    return NormalizedUrl(key, host)
