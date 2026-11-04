"""調べ物の自動命名と手での修正（FR-12）のテスト。"""

import sqlite3
from contextlib import closing
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tadori.api.app import create_app
from tadori.ingest.importer import import_history
from tests.fixtures.make_fake_history import JST, LINK, SINGLE, TYPED, FakeVisit, build


@pytest.fixture
def imported(tmp_path):
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    build(history)
    db = tmp_path / "tadori.db"
    import_history(history, db)
    return history, db


def _names(db):
    with closing(sqlite3.connect(db)) as con:
        return [r[0] for r in con.execute("SELECT name FROM sessions ORDER BY started_at")]


def test_sessions_are_named_by_first_search_term(imported):
    _, db = imported
    assert _names(db) == ["python 辞書", "websocket python", "OCR 作り方", "表組 可視化 python"]


def test_session_without_search_is_named_by_top_concept(tmp_path):
    """検索の無い調べ物は、重みの合計がいちばん大きい概念で名づける。"""
    def visit(key, minute, url, title, **kw):
        return FakeVisit(key, datetime(2025, 9, 1, 10, minute, tzinfo=JST), url, title, LINK | SINGLE, **kw)

    visits = [
        FakeVisit("a", datetime(2025, 9, 1, 10, 0, tzinfo=JST), "https://example.com/aiohttp-1", "aiohttp の基本",
                  TYPED | SINGLE),
        visit("b", 1, "https://example.com/aiohttp-2", "aiohttp でルーティング", from_key="a"),
        visit("c", 2, "https://example.com/flask", "flask と aiohttp", from_key="b"),
        visit("d", 3, "https://example.com/flask-2", "flask 入門", from_key="c"),
    ]
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    build(history, visits)
    db = tmp_path / "tadori.db"
    import_history(history, db)
    assert _names(db) == ["aiohttp"]  # aiohttp は3ページ、flask は2ページ


def test_rename_and_reset_via_api(imported):
    history, db = imported
    client = TestClient(create_app(db))
    session = client.get("/api/sessions").json()[2]
    assert session["name"] == "OCR 作り方"

    res = client.patch(f"/api/sessions/{session['id']}", json={"name": "  OCR  "})
    assert res.status_code == 200
    assert res.json()["name"] == "OCR"

    # 取り込み直しても、手で直した名前は残る
    import_history(history, db)
    assert _names(db)[2] == "OCR"

    # 空欄を送ると自動の名前に戻る
    assert client.patch(f"/api/sessions/{session['id']}", json={"name": ""}).json()["name"] == "OCR 作り方"
    import_history(history, db)
    assert _names(db)[2] == "OCR 作り方"

    assert client.patch("/api/sessions/999", json={"name": "x"}).status_code == 404
