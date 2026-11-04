"""指定したページの本文を取得し、概念の材料にする（FR-14、04 アルゴリズムの「本文（段階3）」）。

Search-Trail で唯一、PC の外へ通信する処理（NFR-01）。画面で明示的に実行したページだけを取りに行く。
相手のサーバーに負担をかけないよう、取得の間隔を空け、大きさと待ち時間に上限を設ける。
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from tadori.analyze.concepts import load_dictionaries, normalize, split_words

BODY_WEIGHT = 0.4
MAX_BODY_CONCEPTS = 15
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT_S = 10
MIN_INTERVAL_S = 3.0  # 取得と取得の間をこれ以上空ける
USER_AGENT = "Search-Trail/0.1 (personal browsing-history viewer; fetches only pages the user asks for)"

# 1つのページ（URL）から本文の文字列を取ってくる関数。テストでは偽物に差し替える
Fetcher = Callable[[str], str]


class BodyError(Exception):
    """利用者に見せるための、本文取得の失敗。"""


class _TextExtractor(HTMLParser):
    """HTML から、画面に表示される文字だけを取り出す（script や style の中身は捨てる）。"""

    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


def fetch_text(url: str) -> str:
    """本物の取得。HTML とテキストだけを、大きさと待ち時間の上限つきで読む。"""
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"})
    try:
        with urlopen(req, timeout=TIMEOUT_S) as res:
            content_type = res.headers.get_content_type()
            if content_type not in ("text/html", "text/plain", "application/xhtml+xml"):
                raise BodyError(f"HTML のページではありません（{content_type}）")
            raw = res.read(MAX_BYTES + 1)[:MAX_BYTES]
            charset = res.headers.get_content_charset()
    except BodyError:
        raise
    except Exception as e:  # 通信の失敗はまとめて利用者向けの言葉にする
        raise BodyError(f"ページを取得できませんでした: {e}") from e

    if charset is None:
        match = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', raw[:4096], re.IGNORECASE)
        charset = match.group(1).decode("ascii") if match else "utf-8"
    try:
        text = raw.decode(charset, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    return html_to_text(text) if content_type != "text/plain" else text


def body_words(con: sqlite3.Connection, text: str) -> list[tuple[str, str]]:
    """本文によく出る言葉を、(正規化した形, 表示名) で多い順に返す。2回以上出たものだけ。"""
    stopwords, synonyms = load_dictionaries(con)
    counts: Counter[str] = Counter()
    surfaces: dict[str, Counter[str]] = {}
    for word in split_words(text):
        norm = normalize(word)
        norm = synonyms.get(norm, norm)
        if len(norm) < 2 or norm in stopwords or norm.replace(".", "").isdigit():
            continue
        counts[norm] += 1
        surfaces.setdefault(norm, Counter())[word] += 1
    return [
        (norm, surfaces[norm].most_common(1)[0][0])
        for norm, n in counts.most_common()
        if n >= 2
    ][:MAX_BODY_CONCEPTS]


def store_body_concepts(con: sqlite3.Connection, page_id: int, words: list[tuple[str, str]]) -> list[str]:
    """本文由来の概念を、そのページの概念として保存し直す。保存した表示名を返す。"""
    con.execute("DELETE FROM page_concepts WHERE page_id = ? AND source = 'body'", (page_id,))
    labels = []
    for norm, surface in words:
        # すでにある概念は表示名を変えない（タイトルや検索語での表記を優先する）
        con.execute(
            "INSERT INTO concepts (label, label_norm) VALUES (?, ?) ON CONFLICT(label_norm) DO NOTHING",
            (surface, norm),
        )
        concept_id, label = con.execute(
            "SELECT id, label FROM concepts WHERE label_norm = ?", (norm,)
        ).fetchone()
        con.execute(
            "INSERT INTO page_concepts (page_id, concept_id, source, weight) VALUES (?, ?, 'body', ?)",
            (page_id, concept_id, BODY_WEIGHT),
        )
        labels.append(label)
    con.execute("DELETE FROM concepts WHERE id NOT IN (SELECT concept_id FROM page_concepts)")
    return labels
