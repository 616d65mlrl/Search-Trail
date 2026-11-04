"""架空の Chrome History ファイルを作るスクリプト（07 段階0）。

本物と同じテーブル構造（urls, visits, visit_source, keyword_search_terms）で、
4つの調べ物を再現する。本物の履歴はテストに使わないため、テストは必ずこれを使う。

中身は説明用の例（OCR の Lens から B・C・D に分岐、Python 入門の「辞書とは」など）で、
URL もタイトルもすべて架空のもの。

使い方:
    uv run python -m tests.fixtures.make_fake_history 出力先のパス
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Chrome の時刻は「1601年1月1日（UTC）からのマイクロ秒」（03 データ設計）
CHROME_EPOCH_OFFSET_US = 11_644_473_600_000_000
JST = timezone(timedelta(hours=9))

# transition の下位8ビット（移動の種類）
LINK = 0
TYPED = 1
AUTO_SUBFRAME = 3
GENERATED = 5
RELOAD = 8

# transition の上位ビット（補足の印）
FORWARD_BACK = 0x01000000
CHAIN_START = 0x10000000
CHAIN_END = 0x20000000
SERVER_REDIRECT = 0x80000000
# 転送でない普通の移動では、Chrome は「連なりの最初で最後」の両方の印をつける
SINGLE = CHAIN_START | CHAIN_END

# visit_source.source の値。0 = 他の端末から同期された訪問
SOURCE_SYNCED = 0

# 本物の History にある列名と型に合わせる（読む側が使う列だけ）
SCHEMA = """
CREATE TABLE urls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url LONGVARCHAR,
  title LONGVARCHAR,
  visit_count INTEGER DEFAULT 0 NOT NULL,
  typed_count INTEGER DEFAULT 0 NOT NULL,
  last_visit_time INTEGER NOT NULL,
  hidden INTEGER DEFAULT 0 NOT NULL
);
CREATE TABLE visits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url INTEGER NOT NULL,
  visit_time INTEGER NOT NULL,
  from_visit INTEGER,
  transition INTEGER DEFAULT 0 NOT NULL,
  segment_id INTEGER,
  visit_duration INTEGER DEFAULT 0 NOT NULL,
  incremented_omnibox_typed_score BOOLEAN DEFAULT FALSE NOT NULL,
  opener_visit INTEGER
);
CREATE TABLE visit_source (
  id INTEGER PRIMARY KEY,
  source INTEGER NOT NULL
);
CREATE TABLE keyword_search_terms (
  keyword_id INTEGER NOT NULL,
  url_id INTEGER NOT NULL,
  term LONGVARCHAR NOT NULL,
  normalized_term LONGVARCHAR NOT NULL
);
"""


@dataclass(frozen=True)
class FakeVisit:
    key: str  # テストから訪問を名指しするための名前
    at: datetime  # 日本時間で書き、保存時に UTC へ直す
    url: str
    title: str
    transition: int
    from_key: str | None = None  # from_visit（リンク元）
    opener_key: str | None = None  # opener_visit（新しいタブの開き元）
    duration_s: int = 30
    search_term: str | None = None  # アドレスバーでの検索語
    hidden: bool = False
    synced: bool = False


def _t(month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(2025, month, day, hour, minute, tzinfo=JST)


def _google(q: str) -> str:
    # 検索結果ページには、正規化で消えるべき余計な引数（sca_esv）もつけておく
    return f"https://www.google.com/search?q={q.replace(' ', '+')}&sca_esv=a1b2c3"


VISITS: list[FakeVisit] = [
    # --- 調べ物1「Python 入門」（9/3）: 検索から始まり、戻るボタンと新しいタブを含む
    FakeVisit("r0", _t(9, 3, 20, 0), _google("python 辞書"), "python 辞書 - Google 検索",
              GENERATED | SINGLE, search_term="python 辞書"),
    FakeVisit("r1", _t(9, 3, 20, 1), "https://docs.python.jp/book-ja/ch04-01-what-is-dict.html",
              "辞書とは？ - The Python Programming Language 日本語版", LINK | SINGLE, from_key="r0", duration_s=420),
    FakeVisit("r2", _t(9, 3, 20, 9), "https://docs.python.jp/book-ja/ch04-02-variables-and-assignment.html",
              "変数と代入 - The Python Programming Language 日本語版", LINK | SINGLE, from_key="r1", duration_s=300),
    # 戻るボタンで r1 に戻った訪問。新しい枝にせず、訪問回数だけ増やす
    FakeVisit("r3", _t(9, 3, 20, 15), "https://docs.python.jp/book-ja/ch04-01-what-is-dict.html",
              "辞書とは？ - The Python Programming Language 日本語版", LINK | SINGLE | FORWARD_BACK,
              from_key="r2"),
    # 新しいタブで開いた訪問（from_visit はなく、opener_visit だけがある）
    FakeVisit("r4", _t(9, 3, 20, 17), "https://docs.python.jp/python-by-example-ja/",
              "Python By Example 日本語版", LINK | SINGLE, opener_key="r1", duration_s=600),

    # --- 調べ物2「WebSocket」（9/20）: 追跡用の引数、再読み込み、埋め込みを含む
    FakeVisit("w0", _t(9, 20, 14, 0), _google("websocket python"), "websocket python - Google 検索",
              GENERATED | SINGLE, search_term="websocket python"),
    FakeVisit("w1", _t(9, 20, 14, 1), "https://github.com/aio-libs/aiohttp",
              "GitHub - aio-libs/aiohttp: A cross-platform, safe, pure-Python HTTP library.", LINK | SINGLE,
              from_key="w0", duration_s=180),
    FakeVisit("w2", _t(9, 20, 14, 5), "https://tutorials.github.io/learn-aiohttp/?utm_source=github&utm_medium=readme",
              "Introduction | Learn Aiohttp", LINK | SINGLE, from_key="w1", duration_s=900),
    # 埋め込み動画の自動読み込み。除外される
    FakeVisit("w2s", _t(9, 20, 14, 5), "https://www.youtube.com/embed/abc123",
              "", AUTO_SUBFRAME | SINGLE, from_key="w2", hidden=True),
    # 再読み込み。新しい訪問として数えず、滞在時間だけ足す
    FakeVisit("w3", _t(9, 20, 14, 20), "https://tutorials.github.io/learn-aiohttp/?utm_source=github&utm_medium=readme",
              "Introduction | Learn Aiohttp", RELOAD | SINGLE, from_key="w2", duration_s=240),
    FakeVisit("w4", _t(9, 20, 14, 26), "https://www.w3.org/TR/websocket/",
              "WebSocket", LINK | SINGLE, from_key="w1", duration_s=360),

    # --- 調べ物3「OCR」（10/12）: Lens から B・C・D に分岐する中心の例
    FakeVisit("g0", _t(10, 12, 21, 2), _google("OCR 作り方"), "OCR 作り方 - Google 検索",
              GENERATED | SINGLE, search_term="OCR 作り方"),
    FakeVisit("g1", _t(10, 12, 21, 5), "https://www.scanapp.example/ja",
              "ScanApp", LINK | SINGLE, from_key="g0", duration_s=600),
    # 短縮 URL からの転送。転送の最後（Lens）だけを残し、来た元は g1 を引き継ぐ
    FakeVisit("g2r", _t(10, 12, 21, 40), "https://t.co/lensocr",
              "", LINK | CHAIN_START, from_key="g1", duration_s=0),
    FakeVisit("g2", _t(10, 12, 21, 40), "https://github.com/textlens/lens",
              "GitHub - textlens/lens: Text recognition for all", LINK | SERVER_REDIRECT | CHAIN_END,
              from_key="g2r", duration_s=420),
    # 分岐 B: リンクをたどる。URL の # 以降は正規化で消える
    FakeVisit("g3", _t(10, 12, 21, 48), "https://zenn.dev/example/articles/document-ocr#install",
              "書類をOCR化する", LINK | SINGLE, from_key="g2", duration_s=540),
    FakeVisit("g4", _t(10, 12, 21, 58), "https://github.com/textlens/lens",
              "GitHub - textlens/lens: Text recognition for all", LINK | SINGLE | FORWARD_BACK,
              from_key="g3"),
    # 分岐 C: 新しいタブで開く
    FakeVisit("g5", _t(10, 12, 22, 0), "https://plotly.io/",
              "Plotly", LINK | SINGLE, opener_key="g2", duration_s=300),
    # 分岐 D: リンクをたどる
    FakeVisit("g6", _t(10, 12, 22, 7), "https://github.com/dashcore/dash/",
              "GitHub - dashcore/dash: Dash is a next generation Web App Framework", LINK | SINGLE,
              from_key="g2", duration_s=240),
    # from_visit も opener_visit も欠けたリンク。3分以内の直前の訪問（g6）を来た元と推定する
    FakeVisit("g7", _t(10, 12, 22, 9), "https://dash.dev/book/",
              "Introduction - The Dash Book", LINK | SINGLE, duration_s=480),
    # ブラウザ内部のページ。除外される
    FakeVisit("gx", _t(10, 12, 22, 20), "chrome://settings/", "設定", TYPED | SINGLE),
    # スマホから同期された訪問。初期設定では除外される
    FakeVisit("gs", _t(10, 12, 22, 30), "https://news.example.com/", "ニュース", TYPED | SINGLE,
              synced=True),
    # 2日後、開きっぱなしの Plotly のタブから続けた訪問。空き時間に関係なく調べ物3に入る
    FakeVisit("g8", _t(10, 14, 21, 50), "https://plotly.io/docs/getting-started/what-is-plotly",
              "What is Plotly? - Plotly", LINK | SINGLE, from_key="g5", duration_s=200),

    # --- 調べ物4「表組の可視化」（10/14）: 30分以上空いて始まる。調べ物3と同じページ（Plotly）を再訪
    FakeVisit("p0", _t(10, 14, 22, 40), _google("表組 可視化 python"), "表組 可視化 python - Google 検索",
              GENERATED | SINGLE, search_term="表組 可視化 python"),
    FakeVisit("p1", _t(10, 14, 22, 42), "https://zenn.dev/example/articles/table-viewer",
              "Python で表組ビューアを作る", LINK | SINGLE, from_key="p0", duration_s=600),
    # 検索結果からのリンクなのに from_visit が欠けた訪問。直前の検索（p0、8分前）を来た元と推定する
    FakeVisit("p1b", _t(10, 14, 22, 48), "https://github.com/plotly-io/plotly",
              "GitHub - plotly-io/plotly", LINK | SINGLE, duration_s=120),
    FakeVisit("p2", _t(10, 14, 22, 55), "https://plotly.io/",
              "Plotly", LINK | SINGLE, from_key="p1", duration_s=120),
    FakeVisit("p3", _t(10, 14, 22, 58), "https://github.com/textlens/lens",
              "GitHub - textlens/lens: Text recognition for all", TYPED | SINGLE, duration_s=60),
]


def to_chrome_time(at: datetime) -> int:
    """日時を Chrome の時刻（1601年起点のマイクロ秒）に直す。"""
    unix_us = int(at.astimezone(timezone.utc).timestamp()) * 1_000_000
    return unix_us + CHROME_EPOCH_OFFSET_US


def to_signed32(transition: int) -> int:
    """本物の Chrome と同じく、transition を符号付き32ビット整数として保存する形に直す。"""
    return transition - (1 << 32) if transition & 0x80000000 else transition


def build(path: Path, visits: list[FakeVisit] = VISITS) -> dict[str, int]:
    """架空の History を path に作り、訪問の名前から Chrome 訪問ID への対応を返す。"""
    path = Path(path)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        url_ids: dict[str, int] = {}
        visit_ids: dict[str, int] = {}
        for v in visits:
            if v.url not in url_ids:
                cur = con.execute(
                    "INSERT INTO urls (url, title, last_visit_time, hidden) VALUES (?, ?, 0, ?)",
                    (v.url, v.title, int(v.hidden)),
                )
                url_ids[v.url] = cur.lastrowid
            url_id = url_ids[v.url]
            when = to_chrome_time(v.at)
            cur = con.execute(
                "INSERT INTO visits (url, visit_time, from_visit, transition, visit_duration, opener_visit)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    url_id,
                    when,
                    visit_ids[v.from_key] if v.from_key else 0,  # Chrome は「なし」を 0 で持つ
                    to_signed32(v.transition),
                    v.duration_s * 1_000_000,
                    visit_ids[v.opener_key] if v.opener_key else 0,
                ),
            )
            visit_ids[v.key] = cur.lastrowid
            con.execute(
                "UPDATE urls SET title = ?, visit_count = visit_count + 1, last_visit_time = ?,"
                " typed_count = typed_count + ? WHERE id = ?",
                (v.title or None, when, int(v.transition & 0xFF == TYPED), url_id),
            )
            if v.synced:
                con.execute("INSERT INTO visit_source (id, source) VALUES (?, ?)",
                            (visit_ids[v.key], SOURCE_SYNCED))
            if v.search_term:
                con.execute(
                    "INSERT INTO keyword_search_terms (keyword_id, url_id, term, normalized_term)"
                    " VALUES (2, ?, ?, ?)",
                    (url_id, v.search_term, v.search_term.lower()),
                )
        con.commit()
    finally:
        con.close()
    return visit_ids


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("使い方: python -m tests.fixtures.make_fake_history 出力先のパス")
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    ids = build(out)
    print(f"{sys.argv[1]} に {len(ids)} 件の訪問を書き出しました")


if __name__ == "__main__":
    main()
