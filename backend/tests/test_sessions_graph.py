"""調べ物の分割と、点と線の集計（FR-05、FR-06）のテスト。"""

import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

from tadori.analyze.graph import build_graph
from tadori.analyze.sessions import split_sessions
from tadori.db.connection import connect
from tadori.ingest.importer import import_history
from tests.fixtures.make_fake_history import JST, build

LENS = "https://github.com/textlens/lens"


@pytest.fixture
def imported(tmp_path):
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    ids = build(history)
    db = tmp_path / "tadori.db"
    import_history(history, db)
    return history, db, ids


def _session_of(db, ids):
    """訪問の名前 → 調べ物の ID。"""
    name_of = {chrome_id: key for key, chrome_id in ids.items()}
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute("SELECT chrome_visit_id, session_id FROM visits").fetchall()
    return {name_of[c]: s for c, s in rows}


def _graph(db, **kwargs):
    with closing(sqlite3.connect(db)) as con:
        return build_graph(con, **kwargs)


def _by_url(graph, url, session_id=None):
    found = [n for n in graph.nodes.values()
             if n.url_norm == url and (session_id is None or n.session_id == session_id)]
    assert len(found) == 1, found
    return found[0]


def test_visits_split_into_four_sessions(imported):
    _, db, ids = imported
    s = _session_of(db, ids)
    groups = {
        "Python 入門": ["r0", "r1", "r2", "r3", "r4"],
        "WebSocket": ["w0", "w1", "w2", "w3", "w4"],
        # g8 は2日後だが、開きっぱなしのタブからの続きなので同じ調べ物
        "OCR": ["g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"],
        # p0 は直前の訪問（g8）から50分空いたので新しい調べ物。p3 は来た元がないが3分後なので同じ調べ物
        "表組の可視化": ["p0", "p1", "p1b", "p2", "p3"],
    }
    for name, keys in groups.items():
        assert len({s[k] for k in keys}) == 1, name
    assert len({s[keys[0]] for keys in groups.values()}) == 4
    # 同期された訪問は調べ物に入らない
    assert s["gs"] is None


def test_sessions_table(imported):
    _, db, ids = imported
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            "SELECT started_at, color_index, root_visit_id FROM sessions ORDER BY started_at"
        ).fetchall()
        root_chrome_ids = [
            con.execute("SELECT chrome_visit_id FROM visits WHERE id = ?", (r[2],)).fetchone()[0] for r in rows
        ]
    assert [r[1] for r in rows] == [0, 1, 2, 3]  # 色は開始時刻の順
    assert root_chrome_ids == [ids["r0"], ids["w0"], ids["g0"], ids["p0"]]
    # OCR の開始時刻が 06 API 仕様の例と一致する
    assert rows[2][0] == 1760270520000


def test_lens_branches_to_b_c_d(imported):
    """段階1の完了条件: Lens から B、C、D に分岐する。"""
    _, db, _ = imported
    graph = _graph(db)
    lens = _by_url(graph, LENS, session_id=_by_url(graph, "search:ocr 作り方").session_id)

    assert lens.branch_count == 3
    assert lens.visits == 2  # 戻るボタンで1回戻ってきた分を含む
    assert lens.first_visit_at == 1760272800000  # 06 API 仕様の例と一致
    assert [(n.title, letter) for n, letter in graph.children(lens.id)] == [
        ("書類をOCR化する", "B"),
        ("Plotly", "C"),
        ("GitHub - dashcore/dash: Dash is a next generation Web App Framework", "D"),
    ]
    assert graph.parent(lens.id).title == "ScanApp"


def test_edges_and_counts(imported):
    _, db, _ = imported
    graph = _graph(db)
    titles = {(graph.nodes[e.source].title, graph.nodes[e.target].title) for e in graph.edges}

    # 戻るボタンの訪問は線を作らない（書類をOCR化 → Lens の逆向きの線はない）
    assert ("書類をOCR化する", "GitHub - textlens/lens: Text recognition for all") not in titles
    assert ("変数と代入 - The Python Programming Language 日本語版",
            "辞書とは？ - The Python Programming Language 日本語版") not in titles
    # 正しい向きの線はある
    assert ("GitHub - textlens/lens: Text recognition for all", "書類をOCR化する") in titles
    # 転送の途中（t.co）は点にならない
    assert not any(n.domain == "t.co" for n in graph.nodes.values())

    # 再読み込みは訪問回数に数えず、滞在時間だけ足す
    aiohttp = _by_url(graph, "https://tutorials.github.io/learn-aiohttp")
    assert aiohttp.visits == 1
    assert aiohttp.duration_ms == (900 + 240) * 1000

    # 分岐点は、違うページへの線が2本以上ある点だけ
    branch_titles = sorted(n.title for n in graph.nodes.values() if n.branch_count)
    assert branch_titles == sorted([
        "辞書とは？ - The Python Programming Language 日本語版",  # 変数と代入、Python By Example
        "GitHub - aio-libs/aiohttp: A cross-platform, safe, pure-Python HTTP library.",  # Learn Aiohttp、WebSocket
        "GitHub - textlens/lens: Text recognition for all",
        "表組 可視化 python - Google 検索",  # 表組ビューア、plotly-io/plotly（検索からの推定）
    ])


def test_same_page_in_two_sessions_is_two_nodes(imported):
    _, db, _ = imported
    graph = _graph(db)
    lens_nodes = [n for n in graph.nodes.values() if n.url_norm == LENS]
    assert len(lens_nodes) == 2
    assert len({n.session_id for n in lens_nodes}) == 2


def test_graph_filters_by_period_and_session(imported):
    _, db, _ = imported
    oct12 = int(datetime(2025, 10, 12, tzinfo=JST).timestamp() * 1000)
    oct13 = int(datetime(2025, 10, 13, tzinfo=JST).timestamp() * 1000)
    graph = _graph(db, from_ms=oct12, to_ms=oct13)
    # 10/14 の続き（What is Plotly?）は期間の外
    assert {n.session_id for n in graph.nodes.values()} == {_by_url(graph, LENS).session_id}
    assert not any("what-is-plotly" in n.url_norm for n in graph.nodes.values())

    session_id = _by_url(graph, LENS).session_id
    only = _graph(db, session_ids=[session_id])
    assert {n.session_id for n in only.nodes.values()} == {session_id}


def test_session_ids_and_manual_names_survive_reimport(imported, tmp_path):
    """取り込み直しても、同じ出発点の調べ物は同じ ID と手で直した名前を保つ。"""
    history, db, ids = imported
    before = _session_of(db, ids)
    with closing(connect(db)) as con:
        con.execute("UPDATE sessions SET name = 'OCR', name_is_manual = 1 WHERE id = ?", (before["g0"],))
        split_sessions(con)
        con.commit()
    import_history(history, db)

    assert _session_of(db, ids) == before
    with closing(sqlite3.connect(db)) as con:
        assert con.execute("SELECT name, name_is_manual FROM sessions WHERE id = ?",
                           (before["g0"],)).fetchone() == ("OCR", 1)


def test_gap_is_configurable(imported):
    """空き時間の区切りを変えられる。10時間にすると、来た元のない p0 も OCR に入る。"""
    _, db, ids = imported
    with closing(connect(db)) as con:
        split_sessions(con, gap_ms=10 * 60 * 60 * 1000)
        con.commit()
    s = _session_of(db, ids)
    assert s["p0"] == s["g0"]
