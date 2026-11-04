"""API（06 API 仕様）のテスト。FastAPI の TestClient で、形とエラーを確かめる。"""

import pytest
from fastapi.testclient import TestClient

from tadori.api.app import create_app, open_url
from tadori.ingest.importer import import_history
from tests.fixtures.make_fake_history import build

LENS_TITLE = "GitHub - textlens/lens: Text recognition for all"


@pytest.fixture
def client(tmp_path):
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    build(history)
    db = tmp_path / "tadori.db"
    import_history(history, db)
    return TestClient(create_app(db))


@pytest.fixture
def empty_client():
    return TestClient(create_app())


def _lens_ocr(client):
    """OCR の調べ物の中の Lens の点。"""
    nodes = client.get("/api/graph").json()["nodes"]
    first = min((n for n in nodes if n["title"] == LENS_TITLE), key=lambda n: n["first_visit_at"])
    return first


def test_not_imported(empty_client):
    status = empty_client.get("/api/status").json()
    assert status == {"imported": False, "visits": 0, "pages": 0, "sessions": 0, "range": None,
                      "last_import_at": None}
    res = empty_client.get("/api/graph")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_imported"


def test_status(client):
    status = client.get("/api/status").json()
    assert status["imported"] is True
    assert status["sessions"] == 4
    assert set(status["range"]) == {"from", "to"}
    assert status["range"]["from"] < status["range"]["to"]


def test_sessions(client):
    sessions = client.get("/api/sessions").json()
    assert [s["color_index"] for s in sessions] == [0, 1, 2, 3]
    assert sessions[2]["started_at"] == 1760270520000
    assert set(sessions[0]) == {"id", "name", "started_at", "ended_at", "color_index", "page_count"}
    # 期間で絞る（10/12 0時 JST 以降に重なる調べ物は OCR と表組の2つ）
    later = client.get("/api/sessions", params={"from": 1760194800000}).json()
    assert [s["id"] for s in later] == [sessions[2]["id"], sessions[3]["id"]]


def test_graph_shape(client):
    graph = client.get("/api/graph").json()
    assert set(graph) == {"range", "sessions", "nodes", "edges", "concepts"}
    node = _lens_ocr(client)
    assert node["id"] == f"s{node['session_id']}-p{node['page_id']}"
    assert node["url"] == "https://github.com/textlens/lens"
    assert node["branch_count"] == 3
    assert node["visits"] == 2
    assert node["first_visit_at"] == 1760272800000
    assert {e["kind"] for e in graph["edges"]} == {"nav", "past"}
    # 同じページを別の調べ物で開いたつながり（表組の調べ物の Lens → OCR の Lens）
    past = [e for e in graph["edges"] if e["kind"] == "past" and e["target"] == node["id"]]
    assert [(e["concept"], e["count"]) for e in past] == [(None, None)]
    assert node["past_count"] == 1
    assert graph["concepts"] == []


def test_graph_filters(client):
    sessions = client.get("/api/sessions").json()
    sid = sessions[2]["id"]
    graph = client.get("/api/graph", params={"sessions": str(sid)}).json()
    assert {n["session_id"] for n in graph["nodes"]} == {sid}
    assert [s["id"] for s in graph["sessions"]] == [sid]

    res = client.get("/api/graph", params={"sessions": "a,b"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "bad_request"


def test_node_detail(client):
    lens = _lens_ocr(client)
    detail = client.get(f"/api/nodes/{lens['id']}").json()
    assert detail["node"] == {"id": lens["id"], "title": LENS_TITLE, "visits": 2}
    assert detail["parent"]["title"] == "ScanApp"
    assert detail["parent"]["reason"] == "from_visit"
    assert [(c["title"].split(":")[0], c["letter"]) for c in detail["children"]] == [
        ("書類をOCR化する", "B"), ("Plotly", "C"), ("GitHub - dashcore/dash", "D"),
    ]
    # 後の調べ物（表組の可視化）で同じページを開いている
    assert [(p["title"], p["concept"], p["relation"]) for p in detail["past_links"]] == [
        (LENS_TITLE, None, "later"),
    ]
    assert detail["past_links"][0]["session_started_at"] > 1760272800000
    assert detail["concepts"] == []  # 「lens」は1ページにしか出ないので概念にならない
    assert detail["visits"][0] == {"visited_at": 1760272800000, "duration_ms": 420_000}


def test_node_detail_past_links_and_concepts(client):
    nodes = client.get("/api/graph").json()["nodes"]
    search = next(n for n in nodes if n["title"] == "表組 可視化 python - Google 検索")
    detail = client.get(f"/api/nodes/{search['id']}").json()
    # 「python」で、Python 入門と WebSocket の検索ページにつながる（1つの古い調べ物につき1本）
    assert sorted((p["title"], p["concept"], p["relation"]) for p in detail["past_links"]) == [
        ("python 辞書 - Google 検索", "python", "past"),
        ("websocket python - Google 検索", "python", "past"),
    ]
    assert set(detail["concepts"]) == {"python", "表組"}


def test_node_detail_estimated_parent(client):
    """推定で決めた来た元は、決め方（time）が詳細に出る。"""
    nodes = client.get("/api/graph").json()["nodes"]
    book = next(n for n in nodes if n["title"] == "Introduction - The Dash Book")
    assert client.get(f"/api/nodes/{book['id']}").json()["parent"]["reason"] == "time"


def test_node_errors(client):
    assert client.get("/api/nodes/abc").json()["error"]["code"] == "bad_request"
    res = client.get("/api/nodes/s999-p1")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_tangle(client):
    lens = _lens_ocr(client)
    tangle = client.get(f"/api/sessions/{lens['session_id']}/tangle").json()
    assert tangle["session"]["id"] == lens["session_id"]
    nodes = {n["id"]: n["title"] for n in client.get("/api/graph").json()["nodes"]}
    tree = [(nodes[t["id"]].split(" - ")[0].split(":")[0], t["depth"]) for t in tangle["tree"]]
    # 深さ優先・時刻順。Lens の下に B（書類）、C（Plotly とその続き）、D（dash とその本）
    assert tree == [
        ("OCR 作り方", 0),
        ("ScanApp", 1),
        ("GitHub", 2),  # Lens
        ("書類をOCR化する", 3),
        ("Plotly", 3),
        ("What is Plotly?", 4),
        ("GitHub", 3),  # dash
        ("Introduction", 4),  # The Dash Book
    ]
    # 後の調べ物（表組の可視化）とつながっている
    assert [(o["session"]["relation"], len(o["nodes"])) for o in tangle["others"]] == [("later", 5)]
    linked = {n["title"] for n in tangle["others"][0]["nodes"] if n["linked"]}
    assert linked == {"Plotly", "GitHub - plotly-io/plotly", LENS_TITLE}
    bridges = sorted((nodes[b["from"]].split(" - ")[0], nodes[b["to"]].split(" - ")[0], b["label"])
                     for b in tangle["bridges"])
    assert bridges == [
        ("GitHub", "GitHub", "同じページ"),  # Lens どうし
        ("Plotly", "GitHub", "Plotly"),  # Plotly → plotly-io/plotly
        ("Plotly", "Plotly", "同じページ"),
    ]
    assert client.get("/api/sessions/999/tangle").status_code == 404


def test_search(client):
    hits = client.get("/api/search", params={"q": "lens"}).json()
    # Lens はOCR と表組の2つの調べ物にあり、新しい順に並ぶ
    assert [h["title"] for h in hits] == [LENS_TITLE, LENS_TITLE]
    assert hits[0]["first_visit_at"] > hits[1]["first_visit_at"]
    # 日本語のタイトルでも探せる。% や _ はそのままの文字として扱う
    assert [h["title"] for h in client.get("/api/search", params={"q": "辞書"}).json()][0].startswith("辞書とは")
    assert client.get("/api/search", params={"q": "%"}).json() == []
    assert client.get("/api/search", params={"q": ""}).status_code == 400


def test_exclusions_roundtrip(client):
    assert client.get("/api/exclusions").json() == []

    res = client.post("/api/exclusions", json={"pattern": " github.com "})
    assert res.status_code == 201
    assert res.json()["pattern"] == "github.com"
    assert [e["pattern"] for e in client.get("/api/exclusions").json()] == ["github.com"]
    # 除外したページは点にならない
    assert not any(n["domain"] == "github.com" for n in client.get("/api/graph").json()["nodes"])

    assert client.delete("/api/exclusions", params={"pattern": "github.com"}).status_code == 204
    assert any(n["domain"] == "github.com" for n in client.get("/api/graph").json()["nodes"])
    assert client.delete("/api/exclusions", params={"pattern": "github.com"}).status_code == 404
    assert client.post("/api/exclusions", json={"pattern": "  "}).status_code == 400


def test_open_url():
    assert open_url("search:ocr 作り方") == "https://www.google.com/search?q=ocr+%E4%BD%9C%E3%82%8A%E6%96%B9"
    assert open_url("https://plotly.io/") == "https://plotly.io/"


def test_concurrent_requests_on_real_server(tmp_path):
    """画面は詳細と今回と過去を同時に問い合わせる。本物のサーバーで並行しても失敗しない。

    TestClient ではスレッドの使い方が本物と違い、この不具合が再現しないため uvicorn を起動する。
    """
    import json
    import socket
    import threading
    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    import uvicorn

    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    build(history)
    db = tmp_path / "tadori.db"
    import_history(history, db)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(db), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        base = f"http://127.0.0.1:{port}"

        def get(path):
            try:
                with urllib.request.urlopen(base + path) as res:
                    return res.status, json.loads(res.read())
            except urllib.error.HTTPError as e:
                return e.code, None

        nodes = get("/api/graph")[1]["nodes"]
        lens = min((n for n in nodes if n["title"] == LENS_TITLE), key=lambda n: n["first_visit_at"])
        paths = [f"/api/nodes/{lens['id']}", f"/api/sessions/{lens['session_id']}/tangle"] * 20
        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = [code for code, _ in pool.map(get, paths)]
        assert codes == [200] * len(paths)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_graph_with_concepts(client):
    """「概念も点にする」（FR-13）のときだけ、概念と、ページ → 概念の線を返す。"""
    assert client.get("/api/graph").json()["concepts"] == []
    graph = client.get("/api/graph", params={"concepts": "true"}).json()
    concepts = {c["label"]: c for c in graph["concepts"]}
    assert concepts["python"]["page_count"] == 6
    assert concepts["python"]["id"].startswith("c")
    mentions = [e for e in graph["edges"] if e["kind"] == "mention"]
    titles = {n["id"]: n["title"] for n in graph["nodes"]}
    python_pages = {titles[e["source"]] for e in mentions if e["target"] == concepts["python"]["id"]}
    assert "Python By Example 日本語版" in python_pages
    # 調べ物で絞ると、その中のページの概念だけになる
    sid = client.get("/api/sessions").json()[2]["id"]  # OCR
    labels = {c["label"] for c in client.get("/api/graph", params={"concepts": "true", "sessions": sid}).json()["concepts"]}
    assert labels == {"OCR", "Plotly", "Dash"}


def _upload(history, *extra):
    """画面の「History を選ぶ」と同じ形（ファイルの中身と名前だけ。場所は送らない）で送る。"""
    files = [("files", ("History", history.read_bytes(), "application/octet-stream"))]
    files += [("files", (name, data, "application/octet-stream")) for name, data in extra]
    return files


def test_import_from_screen(tmp_path, monkeypatch):
    """画面で選んだ History を、メモリの中だけに取り込む。ファイルは何も残さない。"""
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    build(history)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    client = TestClient(create_app())
    assert client.get("/api/status").json()["imported"] is False
    assert client.get("/api/graph").json()["error"]["code"] == "not_imported"

    res = client.post("/api/import", files=_upload(history, ("History-wal", b"")))
    assert res.status_code == 200
    assert res.json() == {"added_visits": 25, "skipped_visits": 3}
    status = client.get("/api/status").json()
    assert status["imported"] is True
    # 選び直すと入れ替わる（前の履歴に足されない）
    assert client.post("/api/import", files=_upload(history)).json()["added_visits"] == 25
    assert client.get("/api/status").json()["visits"] == status["visits"]
    # 作業フォルダに、データベースなどのファイルを作っていない
    assert list(work.iterdir()) == []


def test_import_errors_keep_previous_history(tmp_path):
    history = tmp_path / "History"
    build(history)
    client = TestClient(create_app())
    client.post("/api/import", files=_upload(history))
    visits = client.get("/api/status").json()["visits"]

    res = client.post("/api/import", files=[("files", ("History", b"not a database", "application/octet-stream"))])
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "import_failed"
    # History を2つ選んだときと、History-wal だけを選んだときは断る
    two = _upload(history, ("History のコピー", history.read_bytes()))
    assert client.post("/api/import", files=two).json()["error"]["code"] == "bad_request"
    wal_only = [("files", ("History-wal", b"", "application/octet-stream"))]
    assert client.post("/api/import", files=wal_only).json()["error"]["code"] == "bad_request"
    # 失敗しても、前に取り込んだ履歴はそのまま
    assert client.get("/api/status").json()["visits"] == visits


def test_responses_are_not_cached(client):
    """閲覧履歴を含む返事を、ブラウザのキャッシュに残させない。"""
    assert client.get("/api/graph").headers["cache-control"] == "no-store"
    assert client.get("/api/status").headers["cache-control"] == "no-store"


def test_serves_built_frontend(tmp_path):
    """tadori start では、組み立て済みの画面も同じサーバーから配る。API が優先される。"""
    (tmp_path / "index.html").write_text("<!doctype html><title>Search-Trail</title>", encoding="utf-8")
    client = TestClient(create_app(static_dir=tmp_path))
    assert "<title>Search-Trail</title>" in client.get("/").text
    assert client.get("/api/status").json()["imported"] is False
    assert client.get("/api/nothing").json()["error"]["code"] == "not_found"
