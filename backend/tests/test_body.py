"""ページ本文の取得（FR-14）のテスト。

外部へは通信しない。API は偽の取得関数で、本物の取得関数は 127.0.0.1 の小さなサーバーで確かめる。
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from tadori.api.app import create_app
from tadori.ingest.body import BodyError, MAX_BODY_CONCEPTS, fetch_text, html_to_text
from tadori.ingest.importer import import_history
from tests.fixtures.make_fake_history import build

LENS_URL = "https://github.com/textlens/lens"
LENS_TITLE = "GitHub - textlens/lens: Text recognition for all"
LENS_HTML = """
<html><head><title>lens</title><style>.python { color: red }</style><script>var aiohttp = 1</script></head>
<body><h1>Lens</h1><p>Lens is written in Python and runs on aiohttp.</p>
<p>Python と aiohttp で、ブラウザでも動く。Python の WebSocket 対応。</p></body></html>
"""


def test_html_to_text_skips_script_and_style():
    text = html_to_text(LENS_HTML)
    assert "Lens is written in Python" in text
    assert "color: red" not in text
    assert "var aiohttp" not in text


@pytest.fixture
def setup(tmp_path):
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    build(history)
    db = tmp_path / "tadori.db"
    import_history(history, db)
    calls: list[str] = []

    def fake_fetch(url: str) -> str:
        calls.append(url)
        if "fail" in url:
            raise BodyError("ページを取得できませんでした: テスト")
        return html_to_text(LENS_HTML)

    client = TestClient(create_app(db, fetcher=fake_fetch))
    nodes = client.get("/api/graph").json()["nodes"]
    return client, nodes, calls


def _page_id(nodes, title):
    return next(n["page_id"] for n in nodes if n["title"] == title)


def test_fetch_adds_body_concepts_and_past_links(setup):
    client, nodes, calls = setup
    lens = min((n for n in nodes if n["title"] == LENS_TITLE), key=lambda n: n["first_visit_at"])
    before = client.get(f"/api/nodes/{lens['id']}").json()
    assert before["concepts"] == []

    res = client.post(f"/api/pages/{lens['page_id']}/fetch")
    assert res.status_code == 200
    assert calls == [LENS_URL]
    # 2回以上出た言葉（python、aiohttp）が概念になる。既存の概念の表示名を使う
    assert set(res.json()["concepts"]) >= {"python", "aiohttp"}
    assert len(res.json()["concepts"]) <= MAX_BODY_CONCEPTS

    after = client.get(f"/api/nodes/{lens['id']}").json()
    assert {"python", "aiohttp"} <= set(after["concepts"])
    # 本文の概念で、前の調べ物（Python 入門、WebSocket）とつながる
    concepts = {p["concept"] for p in after["past_links"] if p["relation"] == "past"}
    assert concepts & {"python", "aiohttp"}


def test_fetch_is_refused_for_search_excluded_and_unknown_pages(setup):
    client, nodes, calls = setup
    search = _page_id(nodes, "OCR 作り方 - Google 検索")
    assert client.post(f"/api/pages/{search}/fetch").json()["error"]["code"] == "not_fetchable"
    assert client.post("/api/pages/9999/fetch").status_code == 404

    client.post("/api/exclusions", json={"pattern": "github.com"})
    lens = _page_id(nodes, LENS_TITLE)
    assert client.post(f"/api/pages/{lens}/fetch").json()["error"]["code"] == "excluded"
    # 断ったときは、外へ取りに行っていない
    assert calls == []


def test_fetch_interval(setup):
    """取得と取得の間を空ける。すぐに次を頼むと 429 で断る。"""
    client, nodes, calls = setup
    first = _page_id(nodes, "ScanApp")
    second = _page_id(nodes, "Plotly")
    assert client.post(f"/api/pages/{first}/fetch").status_code == 200
    res = client.post(f"/api/pages/{second}/fetch")
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_requests"
    assert len(calls) == 1


def test_fetch_failure(tmp_path):
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    build(history)
    db = tmp_path / "tadori.db"
    import_history(history, db)

    def failing(url: str) -> str:
        raise BodyError("ページを取得できませんでした: テスト")

    client = TestClient(create_app(db, fetcher=failing))
    page = client.get("/api/graph").json()["nodes"][1]["page_id"]
    res = client.post(f"/api/pages/{page}/fetch")
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "fetch_failed"


# --- 本物の取得関数を、自分の PC の中だけのサーバーで確かめる ---

class _Handler(BaseHTTPRequestHandler):
    routes = {
        "/utf8": ("text/html; charset=utf-8", "<p>表組の可視化</p>".encode("utf-8")),
        "/sjis": ("text/html", '<meta charset="shift_jis"><p>表組の可視化</p>'.encode("shift_jis")),
        "/image": ("image/png", b"\x89PNG"),
    }

    def do_GET(self):  # noqa: N802
        if self.path not in self.routes:
            self.send_error(404)
            return
        content_type, body = self.routes[self.path]
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_fetch_text_reads_html_with_charset(local_server):
    assert fetch_text(f"{local_server}/utf8") == "表組の可視化"
    # 文字コードがヘッダーに無いときは、meta タグから読む
    assert fetch_text(f"{local_server}/sjis") == "表組の可視化"


def test_fetch_text_rejects_non_html_and_errors(local_server):
    with pytest.raises(BodyError, match="HTML のページではありません"):
        fetch_text(f"{local_server}/image")
    with pytest.raises(BodyError, match="取得できませんでした"):
        fetch_text(f"{local_server}/missing")
