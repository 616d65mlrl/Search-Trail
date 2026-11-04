"""来た元の決定と転送のまとめ（FR-04）のテスト。"""

import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

from tadori.db.connection import connect
from tadori.ingest.exclude import skip_reason
from tadori.ingest.importer import import_history
from tests.fixtures.make_fake_history import JST, LINK, SINGLE, build, to_chrome_time
from tests.test_exclude import _visit

# 架空の履歴での正解: 訪問 → (来た元, 決め方)。None は出発点
EXPECTED = {
    # 調べ物1「Python 入門」
    "r0": (None, None),
    "r1": ("r0", "from_visit"),
    "r2": ("r1", "from_visit"),
    "r3": ("r2", "from_visit"),  # 戻るボタン。枝にしないのは点と線の集計（FR-06）で扱う
    "r4": ("r1", "opener"),
    # 調べ物2「WebSocket」
    "w0": (None, None),
    "w1": ("w0", "from_visit"),
    "w2": ("w1", "from_visit"),
    "w3": ("w2", "from_visit"),
    "w4": ("w1", "from_visit"),
    # 調べ物3「OCR」
    "g0": (None, None),
    "g1": ("g0", "from_visit"),
    "g2": ("g1", "from_visit"),  # 転送（t.co）を飛ばし、連なりの最初の来た元を引き継ぐ
    "g3": ("g2", "from_visit"),
    "g4": ("g3", "from_visit"),
    "g5": ("g2", "opener"),
    "g6": ("g2", "from_visit"),
    "g7": ("g6", "time"),  # リンク元が欠けている。2分前の dash から来たと推定
    "gs": (None, None),  # 同期された訪問は来た元を決めない
    "g8": ("g5", "from_visit"),  # 2日後でも、開きっぱなしのタブからの続き
    # 調べ物4「表組の可視化」
    "p0": (None, None),
    "p1": ("p0", "from_visit"),
    "p1b": ("p0", "search"),  # リンク元が欠けている。8分前の検索結果から来たと推定
    "p2": ("p1", "from_visit"),
    "p3": (None, None),  # アドレスバーに入力した訪問は出発点
}


def _parents(db, ids):
    """訪問の名前 → (来た元の名前, 決め方) を tadori.db から読む。"""
    name_of = {chrome_id: key for key, chrome_id in ids.items()}
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            """
            SELECT v.chrome_visit_id, p.chrome_visit_id, v.parent_reason
            FROM visits v LEFT JOIN visits p ON p.id = v.parent_visit_id
            """
        ).fetchall()
    return {name_of[c]: (name_of.get(pc), reason) for c, pc, reason in rows}


@pytest.fixture
def imported(tmp_path):
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    ids = build(history)
    db = tmp_path / "tadori.db"
    import_history(history, db)
    return history, db, ids


def test_parents_follow_priority(imported):
    _, db, ids = imported
    assert _parents(db, ids) == EXPECTED


def test_redirect_chain_keeps_only_last_visit():
    start = 0x10000000
    end = 0x20000000
    server_redirect = 0x80000000
    # 連なりの最初（終わりではない）と途中は取り込まない
    assert skip_reason(_visit("https://t.co/x", transition=LINK | start)) == "redirect"
    assert skip_reason(_visit("https://a.example/", transition=LINK | server_redirect)) == "redirect"
    # 連なりの最後と、転送でない普通の移動は取り込む
    assert skip_reason(_visit("https://b.example/", transition=LINK | server_redirect | end)) is None
    assert skip_reason(_visit("https://c.example/", transition=LINK | SINGLE)) is None
    # 印が何もない訪問（古い Chrome など）も取り込む
    assert skip_reason(_visit("https://d.example/", transition=LINK)) is None


def test_excluded_pages_are_skipped_when_climbing(imported):
    """除外リストに合うページは来た元にせず、その来た元までさかのぼる。"""
    history, db, ids = imported
    with closing(connect(db)) as con:
        # Plotly のトップページだけを除外する（g5 と p2。g8 のドキュメントのページは残る）
        con.execute("INSERT INTO exclusions (pattern) VALUES ('plotly.io/')")
        con.commit()
    # 除外リストを変えたあとの取り込みで、来た元が計算し直される
    import_history(history, db)

    parents = _parents(db, ids)
    assert parents["g5"] == (None, None)  # 除外されたページ自身は来た元を持たない
    # Plotly（除外）から来た訪問は、Plotly を開いた Lens までさかのぼる
    assert parents["g8"] == ("g2", "from_visit")
    assert parents["p2"] == (None, None)  # p2 自身も plotly.io
    # 除外に関係ない訪問は変わらない
    assert parents["g6"] == EXPECTED["g6"]


def test_parent_from_previous_import(imported):
    """差分取り込みで、前回取り込んだ訪問を来た元にできる。"""
    history, db, ids = imported
    with closing(sqlite3.connect(history)) as con:
        at = to_chrome_time(datetime(2025, 10, 20, 9, 0, tzinfo=JST))
        url_id = con.execute(
            "INSERT INTO urls (url, title, last_visit_time) VALUES ('https://example.com/later', 'x', ?)", (at,)
        ).lastrowid
        new_id = con.execute(
            "INSERT INTO visits (url, visit_time, from_visit, transition, visit_duration, opener_visit)"
            " VALUES (?, ?, ?, ?, 0, 0)",
            (url_id, at, ids["g6"], LINK | SINGLE),
        ).lastrowid
        con.commit()

    import_history(history, db)
    parents = _parents(db, {**ids, "later": new_id})
    assert parents["later"] == ("g6", "from_visit")
    assert {k: v for k, v in parents.items() if k != "later"} == EXPECTED
