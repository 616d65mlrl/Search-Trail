"""過去とのつながり（FR-11）のテスト。"""

import math
import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

from tadori.analyze.past_links import MAX_LINKS_PER_NODE
from tadori.db.connection import connect
from tadori.ingest.importer import import_history
from tests.fixtures.make_fake_history import GENERATED, JST, SINGLE, VISITS, FakeVisit, _google, build


def _import(tmp_path, visits=VISITS):
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    ids = build(history, visits)
    db = tmp_path / "tadori.db"
    import_history(history, db)
    return db, ids


def _links(db, ids):
    """(新しい側, 古い側, 概念, 点数) の一覧。訪問は名前で表す。"""
    name = {chrome_id: key for key, chrome_id in ids.items()}
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            """
            SELECT nv.chrome_visit_id, ov.chrome_visit_id, c.label, pl.score FROM past_links pl
            JOIN visits nv ON nv.id = pl.new_visit_id JOIN visits ov ON ov.id = pl.old_visit_id
            LEFT JOIN concepts c ON c.id = pl.concept_id
            """
        ).fetchall()
    return sorted((name[n], name[o], c, s) for n, o, c, s in rows)


def test_links_in_fake_history(tmp_path):
    db, ids = _import(tmp_path)
    links = _links(db, ids)
    assert [(n, o, c) for n, o, c, _ in links] == [
        ("p0", "r0", "python"),  # 表組の検索 → Python 入門の検索
        ("p0", "w0", "python"),  # 表組の検索 → WebSocket の検索（1つの古い調べ物につき1本）
        ("p1", "r0", "python"),
        ("p1", "w0", "python"),
        ("p1b", "g5", "Plotly"),  # plotly-io/plotly → OCR の Plotly（同点なら先に開いたほう）
        ("p2", "g5", None),  # 同じページを別の調べ物で開いた
        ("p3", "g2", None),  # Lens どうし
        ("w0", "r0", "python"),
        ("w1", "r0", "python"),
    ]


def test_score_formula(tmp_path):
    """score = w_n × w_m × log(N / df)。同じページは log(N) + 1 で、どの概念よりも高い。"""
    db, ids = _import(tmp_path)
    with closing(sqlite3.connect(db)) as con:
        total = con.execute(
            "SELECT COUNT(DISTINCT page_id) FROM visits WHERE session_id IS NOT NULL"
        ).fetchone()[0]
        df_python = con.execute(
            "SELECT COUNT(DISTINCT page_id) FROM page_concepts pc JOIN concepts c ON c.id = pc.concept_id"
            " WHERE c.label = 'python'"
        ).fetchone()[0]
    scores = {(n, o): s for n, o, _, s in _links(db, ids)}
    # 検索語どうし（重み 1.0 × 1.0）
    assert scores[("w0", "r0")] == pytest.approx(math.log(total / df_python))
    # タイトル（0.6）と検索語（1.0）
    assert scores[("w1", "r0")] == pytest.approx(0.6 * math.log(total / df_python))
    assert scores[("p3", "g2")] == pytest.approx(math.log(total) + 1)
    assert scores[("p3", "g2")] > max(s for (n, o), s in scores.items() if (n, o) not in {("p2", "g5"), ("p3", "g2")})


def test_links_only_point_to_older_sessions(tmp_path):
    db, ids = _import(tmp_path)
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            "SELECT ns.started_at, os.started_at FROM past_links pl"
            " JOIN visits nv ON nv.id = pl.new_visit_id JOIN sessions ns ON ns.id = nv.session_id"
            " JOIN visits ov ON ov.id = pl.old_visit_id JOIN sessions os ON os.id = ov.session_id"
        ).fetchall()
    assert rows and all(new > old for new, old in rows)


def test_at_most_three_links_per_node(tmp_path):
    """古い調べ物が5つあっても、1つの点からは点数の高い3本まで。"""
    visits = [
        FakeVisit(f"old{i}", datetime(2025, 9, 1 + i, 10, 0, tzinfo=JST), _google(f"python 第{i}回"),
                  f"python 第{i}回 - Google 検索", GENERATED | SINGLE, search_term=f"python 第{i}回")
        for i in range(5)
    ] + [
        FakeVisit("new", datetime(2025, 9, 20, 10, 0, tzinfo=JST), _google("python 総まとめ"),
                  "python 総まとめ - Google 検索", GENERATED | SINGLE, search_term="python 総まとめ"),
    ]
    db, ids = _import(tmp_path, visits)
    from_new = [link for link in _links(db, ids) if link[0] == "new"]
    assert len(from_new) == MAX_LINKS_PER_NODE
    # 点数が同じなら、先に開いた調べ物から選ぶ
    assert [o for _, o, _, _ in from_new] == ["old0", "old1", "old2"]


def test_old_schema_is_migrated(tmp_path):
    """concept_id が NOT NULL だった古い past_links は作り直す。"""
    db = tmp_path / "tadori.db"
    with closing(sqlite3.connect(db)) as con:
        con.execute(
            "CREATE TABLE past_links (id INTEGER PRIMARY KEY, new_visit_id INTEGER NOT NULL,"
            " old_visit_id INTEGER NOT NULL, concept_id INTEGER NOT NULL, score REAL NOT NULL)"
        )
    with closing(connect(db)) as con:
        notnull = {row[1]: row[3] for row in con.execute("PRAGMA table_info(past_links)")}
    assert notnull["concept_id"] == 0
