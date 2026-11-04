"""画面とサーバーの受け渡し口（06 API 仕様）。

サーバーは 127.0.0.1 でだけ待ち受ける（NFR-02、cli.py の serve）。
閲覧履歴と解析結果はメモリの中のデータベースにだけ置き、ファイルには保存しない。
History は画面で利用者が選んだファイルを受け取り、その場所（パス）はサーバーに届かない。
エラーは {"error": {"code": "…", "message": "…"}} の形で返す。

このファイルでは `from __future__ import annotations` を使わない。型の注釈が文字列になると、
create_app の中で定義した依存（Depends(db)）を FastAPI が解決できなくなるため。
"""

import re
import sqlite3
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI, File, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from tadori.analyze.graph import Graph, Node, PastLink, build_graph, load_past_links
from tadori.analyze.naming import name_sessions, rename_session
from tadori.analyze.past_links import link_past
from tadori.analyze.pipeline import analyze
from tadori.api import models as m
from tadori.db.connection import MEMORY, connect
from tadori.ingest.body import MIN_INTERVAL_S, BodyError, Fetcher, body_words, fetch_text, store_body_concepts
from tadori.ingest.chrome import COMPANION_SUFFIXES, HistoryError
from tadori.ingest.exclude import refresh_page_exclusions
from tadori.ingest.importer import import_history

NODE_ID = re.compile(r"^s(\d+)-p(\d+)$")
LONG_SESSION = 15  # 今回と過去で、これを超える調べ物はつながりのある点とその前後だけを返す
SAME_PAGE = "同じページ"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def open_url(url_norm: str) -> str:
    """点をダブルクリックしたときに開く URL。検索の鍵は Google 検索の URL に戻す。"""
    if url_norm.startswith("search:"):
        return "https://www.google.com/search?q=" + quote_plus(url_norm.removeprefix("search:"))
    return url_norm


def _graph_node(n: Node) -> m.GraphNode:
    return m.GraphNode(
        id=n.id, session_id=n.session_id, page_id=n.page_id, title=n.title, domain=n.domain,
        url=open_url(n.url_norm), visits=n.visits, first_visit_at=n.first_visit_at,
        branch_count=n.branch_count, past_count=n.past_count,
    )


def _parse_node_id(node_id: str) -> tuple[int, int]:
    match = NODE_ID.match(node_id)
    if not match:
        raise ApiError(400, "bad_request", f"点の ID の形が正しくありません: {node_id}")
    return int(match[1]), int(match[2])


def _parse_ids(text: str | None) -> list[int] | None:
    if text is None or text == "":
        return None
    try:
        return [int(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise ApiError(400, "bad_request", f"調べ物の ID は数字をカンマで区切って指定してください: {text}")


def _node_info(con: sqlite3.Connection, ids: list[str]) -> dict[str, tuple[str | None, int, str | None, int]]:
    """点の ID → (ページのタイトル, 調べ物の ID, 調べ物の名前, 調べ物の開始時刻)。"""
    info = {}
    for nid in ids:
        session_id, page_id = _parse_node_id(nid)
        row = con.execute(
            "SELECT p.title, s.id, s.name, s.started_at FROM pages p, sessions s WHERE p.id = ? AND s.id = ?",
            (page_id, session_id),
        ).fetchone()
        if row:
            info[nid] = row
    return info


def _session_of(nid: str) -> int:
    return _parse_node_id(nid)[0]


def _session_graph(con: sqlite3.Connection, node_id: str) -> tuple[Graph, Node]:
    session_id, _ = _parse_node_id(node_id)
    graph = build_graph(con, session_ids=[session_id])
    node = graph.nodes.get(node_id)
    if node is None:
        raise ApiError(404, "not_found", f"点が見つかりません: {node_id}")
    return graph, node


def _save_uploads(files: list[UploadFile], dest_dir: Path) -> Path:
    """画面で選んだ History（と、あれば History-wal など）を一時フォルダへ書き出し、History の場所を返す。
    名前の終わりが -wal / -journal のものを付属のファイルとみなし、それ以外の1つを History とみなす。"""
    def suffix(name: str) -> str | None:
        return next((s for s in COMPANION_SUFFIXES if name.endswith(s)), None)

    mains = [f for f in files if f.filename and suffix(f.filename) is None]
    if len(mains) != 1:
        raise ApiError(400, "bad_request", "History ファイルを1つ選んでください（History-wal は一緒に選んでもかまいません）")
    dest = dest_dir / "History"
    for f in files:
        sfx = suffix(f.filename or "")
        with open(dest if sfx is None else dest.with_name(dest.name + sfx), "wb") as out:
            while chunk := f.file.read(1024 * 1024):
                out.write(chunk)
    return dest


def create_app(db_path: Path | None = None, fetcher: Fetcher | None = None,
               static_dir: Path | None = None) -> FastAPI:
    """db_path を省略すると、メモリの中だけのデータベースで動く（ふだんの使い方）。テストではファイルを渡せる。
    fetcher は本文の取得（POST /api/pages/{id}/fetch）に使う関数。省略時は本物の通信。テストでは偽物を渡す。
    static_dir は組み立て済みの画面（frontend/dist）。渡すと、画面も同じサーバーから配る（tadori start）。"""
    fetch = fetcher or fetch_text
    # 接続は1本だけにして、問い合わせを1つずつ順番に通す（メモリの中のデータベースは接続ごとに別物になるため）。
    # FastAPI は、依存と各エンドポイントを別々のスレッドで動かすことがあるので、スレッドの確認を外す
    con_shared = connect(db_path if db_path is not None else MEMORY, check_same_thread=False)
    con_lock = threading.Lock()
    fetch_lock = threading.Lock()
    last_fetch = [float("-inf")]  # 最後に本文を取得した時刻（間隔を空けるため）
    app = FastAPI(title="Search-Trail", version="0.1.0")

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        return _error(e.status, e.code, e.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, e: RequestValidationError) -> JSONResponse:
        return _error(400, "bad_request", f"引数が正しくありません: {e.errors()}")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, e: StarletteHTTPException) -> JSONResponse:
        return _error(e.status_code, "not_found" if e.status_code == 404 else "http_error", str(e.detail))

    @app.middleware("http")
    async def _no_store(request: Request, call_next):
        # 閲覧履歴を含む返事を、ブラウザのキャッシュ（ディスク）に残させない
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def db() -> Iterator[sqlite3.Connection]:
        with con_lock:
            yield con_shared

    def imported_db(con: Annotated[sqlite3.Connection, Depends(db)]) -> sqlite3.Connection:
        if con.execute("SELECT 1 FROM import_runs LIMIT 1").fetchone() is None:
            raise ApiError(409, "not_imported", "まだ履歴を取り込んでいません。画面で History ファイルを選んでください")
        return con

    Db = Annotated[sqlite3.Connection, Depends(imported_db)]
    From = Annotated[int | None, Query(alias="from")]

    @app.get("/api/status", response_model=m.Status)
    def status(con: Annotated[sqlite3.Connection, Depends(db)]) -> m.Status:
        visits, first, last = con.execute(
            "SELECT COUNT(*), MIN(visited_at), MAX(visited_at) FROM visits WHERE session_id IS NOT NULL"
        ).fetchone()
        last_import = con.execute("SELECT MAX(started_at) FROM import_runs").fetchone()[0]
        return m.Status(
            imported=last_import is not None,
            visits=visits,
            pages=con.execute("SELECT COUNT(*) FROM pages WHERE excluded = 0").fetchone()[0],
            sessions=con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            range=m.Range(from_=first, to=last) if visits else None,
            last_import_at=last_import,
        )

    @app.get("/api/sessions", response_model=list[m.Session])
    def sessions(con: Db, from_: From = None, to: int | None = None) -> list[m.Session]:
        # 期間と重なる調べ物（始まりが期間の終わりより前、終わりが期間の始まり以降）
        rows = con.execute(
            """
            SELECT s.id, s.name, s.started_at, s.ended_at, s.color_index, COUNT(DISTINCT v.page_id)
            FROM sessions s JOIN visits v ON v.session_id = s.id
            WHERE (? IS NULL OR s.ended_at >= ?) AND (? IS NULL OR s.started_at < ?)
            GROUP BY s.id ORDER BY s.started_at
            """,
            (from_, from_, to, to),
        ).fetchall()
        return [m.Session(id=r[0], name=r[1], started_at=r[2], ended_at=r[3], color_index=r[4], page_count=r[5])
                for r in rows]

    @app.patch("/api/sessions/{session_id}", response_model=m.Session)
    def patch_session(con: Db, session_id: int, body: m.SessionNameIn) -> m.Session:
        if con.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
            raise ApiError(404, "not_found", f"調べ物が見つかりません: {session_id}")
        with con:
            rename_session(con, session_id, body.name)
        return next(s for s in sessions(con) if s.id == session_id)

    @app.get("/api/graph", response_model=m.GraphResponse)
    def graph(con: Db, from_: From = None, to: int | None = None, sessions: str | None = None,
              concepts: bool = False) -> m.GraphResponse:
        g = build_graph(con, from_ms=from_, to_ms=to, session_ids=_parse_ids(sessions))
        session_ids = sorted({n.session_id for n in g.nodes.values()})
        rows = con.execute(
            f"SELECT id, name, started_at, color_index FROM sessions WHERE id IN ({','.join('?' * len(session_ids))})"
            " ORDER BY started_at",
            session_ids,
        ).fetchall() if session_ids else []
        times = [t for n in g.nodes.values() for t, _ in n.visit_times]

        # 「概念も点にする」（FR-13）: 表示中のページの概念と、ページ → 概念の線
        concept_items: list[m.GraphConcept] = []
        mention_edges: list[m.GraphEdge] = []
        if concepts and g.nodes:
            page_ids = sorted({n.page_id for n in g.nodes.values()})
            rows_pc = con.execute(
                f"SELECT DISTINCT pc.page_id, c.id, c.label FROM page_concepts pc JOIN concepts c ON c.id = pc.concept_id"
                f" WHERE pc.page_id IN ({','.join('?' * len(page_ids))})",
                page_ids,
            ).fetchall()
            nodes_of_page: dict[int, list[str]] = {}
            for n in g.nodes.values():
                nodes_of_page.setdefault(n.page_id, []).append(n.id)
            labels: dict[int, str] = {}
            pages_of: dict[int, set[int]] = {}
            for page_id, concept_id, label in rows_pc:
                labels[concept_id] = label
                pages_of.setdefault(concept_id, set()).add(page_id)
                for nid in nodes_of_page[page_id]:
                    mention_edges.append(m.GraphEdge(source=nid, target=f"c{concept_id}", kind="mention"))
            concept_items = [m.GraphConcept(id=f"c{cid}", label=labels[cid], page_count=len(pages_of[cid]))
                             for cid in sorted(labels, key=lambda c: (-len(pages_of[c]), labels[c]))]

        return m.GraphResponse(
            range=m.Range(from_=from_ if from_ is not None else min(times, default=None),
                          to=to if to is not None else max(times, default=None)),
            sessions=[m.GraphSession(id=r[0], name=r[1], started_at=r[2], color_index=r[3]) for r in rows],
            nodes=[_graph_node(n) for n in sorted(g.nodes.values(), key=lambda n: (n.first_visit_at, n.id))],
            edges=[
                m.GraphEdge(
                    source=e.source, target=e.target, kind=e.kind,
                    count=e.count if e.kind == "nav" else None,
                    concept=e.concept, score=round(e.score, 3) if e.score is not None else None,
                )
                for e in g.edges
            ] + mention_edges,
            concepts=concept_items,
        )

    @app.get("/api/nodes/{node_id}", response_model=m.NodeDetail, response_model_exclude_none=False)
    def node_detail(con: Db, node_id: str) -> m.NodeDetail:
        g, node = _session_graph(con, node_id)
        edge = g.parent_edge(node_id)
        links = [link for link in load_past_links(con) if node_id in (link.new, link.old)]
        others = [(link.old if link.new == node_id else link.new, link) for link in links]
        info = _node_info(con, [other for other, _ in others])
        concepts = [r[0] for r in con.execute(
            "SELECT c.label FROM page_concepts pc JOIN concepts c ON c.id = pc.concept_id WHERE pc.page_id = ?"
            " GROUP BY c.id ORDER BY MAX(pc.weight) DESC, c.label",
            (node.page_id,),
        )]
        return m.NodeDetail(
            node=m.NodeSummary(id=node.id, title=node.title, visits=node.visits),
            parent=m.ParentRef(id=edge.source, title=g.nodes[edge.source].title, reason=edge.reason)
            if edge else None,
            children=[m.ChildRef(id=c.id, title=c.title, letter=letter) for c, letter in g.children(node_id)],
            past_links=[
                m.PastLinkRef(
                    id=other, title=info[other][0], session_id=info[other][1], session_name=info[other][2],
                    session_started_at=info[other][3], concept=link.concept,
                    relation="past" if link.new == node_id else "later",
                )
                for other, link in others
                if other in info
            ],
            concepts=concepts,
            visits=[m.VisitTime(visited_at=t, duration_ms=d) for t, d in node.visit_times],
        )

    @app.get("/api/sessions/{session_id}/tangle", response_model=m.TangleResponse)
    def tangle(con: Db, session_id: int) -> m.TangleResponse:
        row = con.execute("SELECT id, name FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise ApiError(404, "not_found", f"調べ物が見つかりません: {session_id}")
        g = build_graph(con, session_ids=[session_id])

        # 木を、深さ優先・時刻順に並べる（同じ点を2回並べないよう、通った点を覚える）
        has_parent = {e.target for e in g.edges}
        roots = sorted((n for n in g.nodes.values() if n.id not in has_parent), key=lambda n: n.first_visit_at)
        tree: list[m.TangleTreeItem] = []
        seen: set[str] = set()

        def walk(n: Node, depth: int) -> None:
            if n.id in seen:
                return
            seen.add(n.id)
            tree.append(m.TangleTreeItem(id=n.id, depth=depth))
            for child, _ in g.children(n.id):
                walk(child, depth + 1)

        for root in roots:
            walk(root, 0)
        # 輪になっていて出発点が無い点も、取りこぼさず最後に並べる
        for n in sorted(g.nodes.values(), key=lambda n: n.first_visit_at):
            walk(n, 0)

        # この調べ物の点と、別の調べ物の点を結ぶ「橋」（過去とのつながり）
        bridges: list[tuple[str, str, PastLink]] = []
        for link in load_past_links(con):
            if _session_of(link.new) == session_id and _session_of(link.old) != session_id:
                bridges.append((link.new, link.old, link))
            elif _session_of(link.old) == session_id and _session_of(link.new) != session_id:
                bridges.append((link.old, link.new, link))

        started_at = con.execute("SELECT started_at FROM sessions WHERE id = ?", (session_id,)).fetchone()[0]
        others: list[m.TangleOther] = []
        for other_id in sorted({_session_of(o) for _, o, _ in bridges}):
            srow = con.execute("SELECT id, name, started_at FROM sessions WHERE id = ?", (other_id,)).fetchone()
            linked = {o for _, o, _ in bridges if _session_of(o) == other_id}
            items = sorted(build_graph(con, session_ids=[other_id]).nodes.values(), key=lambda n: n.first_visit_at)
            if len(items) > LONG_SESSION:
                # 長い調べ物は、つながりのある点とその前後だけにする
                items = [n for i, n in enumerate(items)
                         if any(items[j].id in linked for j in (i - 1, i, i + 1) if 0 <= j < len(items))]
            others.append(m.TangleOther(
                session=m.TangleOtherSession(id=srow[0], name=srow[1], started_at=srow[2],
                                             relation="past" if srow[2] < started_at else "later"),
                nodes=[m.TangleOtherNode(id=n.id, title=n.title, linked=n.id in linked) for n in items],
            ))
        others.sort(key=lambda o: o.session.started_at)

        return m.TangleResponse(
            session=m.TangleSessionRef(id=row[0], name=row[1]),
            tree=tree,
            others=others,
            bridges=[m.TangleBridge(from_=mine, to=other, kind="past", label=link.concept or SAME_PAGE)
                     for mine, other, link in bridges],
        )

    @app.get("/api/search", response_model=list[m.SearchHit])
    def search(con: Db, q: Annotated[str, Query(min_length=1)],
               limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[m.SearchHit]:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = con.execute(
            r"""
            SELECT v.session_id, v.page_id, p.title, p.domain, MIN(v.visited_at), MAX(v.visited_at)
            FROM visits v JOIN pages p ON p.id = v.page_id
            WHERE v.session_id IS NOT NULL
              AND (p.title LIKE ? ESCAPE '\' OR p.url_norm LIKE ? ESCAPE '\')
            GROUP BY v.session_id, v.page_id
            ORDER BY MAX(v.visited_at) DESC
            LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
        return [m.SearchHit(id=f"s{r[0]}-p{r[1]}", title=r[2], domain=r[3], session_id=r[0], first_visit_at=r[4])
                for r in rows]

    @app.post("/api/import", response_model=m.ImportResult)
    def run_import(con: Annotated[sqlite3.Connection, Depends(db)],
                   files: Annotated[list[UploadFile], File()]) -> m.ImportResult:
        """画面で選んだ History を取り込む。前に取り込んだ履歴とは入れ替える。
        受け取ったファイルは一時フォルダに書き出して読み、読み終えたらすぐに消す。"""
        with tempfile.TemporaryDirectory(prefix="tadori-", ignore_cleanup_errors=True) as tmp:
            history = _save_uploads(files, Path(tmp))
            try:
                result = import_history(history, con, replace=True)
            except HistoryError as e:
                raise ApiError(400, "import_failed", str(e))
        return m.ImportResult(added_visits=result.added_visits, skipped_visits=result.skipped_visits)

    @app.post("/api/pages/{page_id}/fetch", response_model=m.BodyResult)
    def fetch_body(con: Db, page_id: int) -> m.BodyResult:
        """指定したページの本文を取得し、概念を足す（FR-14）。PC の外へ通信する唯一の処理（NFR-01）。"""
        row = con.execute("SELECT url_norm, excluded FROM pages WHERE id = ?", (page_id,)).fetchone()
        if row is None:
            raise ApiError(404, "not_found", f"ページが見つかりません: {page_id}")
        url, excluded = row
        if excluded:
            raise ApiError(400, "excluded", "除外リストに入っているページは取得しません")
        if not url.startswith(("http://", "https://")):
            raise ApiError(400, "not_fetchable", "このページ（検索結果やローカルのファイルなど）は取得できません")
        # 相手のサーバーに負担をかけないよう、取得の間隔を空ける（失敗した取得も数える）
        with fetch_lock:
            wait = MIN_INTERVAL_S - (time.monotonic() - last_fetch[0])
            if wait > 0:
                raise ApiError(429, "too_many_requests", f"{wait:.0f} 秒ほど待ってから、もう一度試してください")
            last_fetch[0] = time.monotonic()
        try:
            text = fetch(url)
        except BodyError as e:
            raise ApiError(502, "fetch_failed", str(e))
        with con:
            labels = store_body_concepts(con, page_id, body_words(con, text))
            link_past(con)
            name_sessions(con)
        return m.BodyResult(page_id=page_id, concepts=labels)

    @app.get("/api/exclusions", response_model=list[m.Exclusion])
    def list_exclusions(con: Annotated[sqlite3.Connection, Depends(db)]) -> list[m.Exclusion]:
        return [m.Exclusion(id=r[0], pattern=r[1]) for r in con.execute("SELECT id, pattern FROM exclusions ORDER BY id")]

    def _reanalyze(con: sqlite3.Connection) -> None:
        # 除外リストが変わると、来た元と調べ物の分け方も変わる
        refresh_page_exclusions(con)
        analyze(con)

    @app.post("/api/exclusions", response_model=m.Exclusion, status_code=201)
    def add_exclusion(con: Annotated[sqlite3.Connection, Depends(db)], body: m.ExclusionIn) -> m.Exclusion:
        pattern = body.pattern.strip()
        if not pattern:
            raise ApiError(400, "bad_request", "除外する条件が空です")
        with con:
            cur = con.execute("INSERT INTO exclusions (pattern) VALUES (?)", (pattern,))
            _reanalyze(con)
        return m.Exclusion(id=cur.lastrowid, pattern=pattern)

    @app.delete("/api/exclusions", status_code=204)
    def delete_exclusion(con: Annotated[sqlite3.Connection, Depends(db)],
                         pattern: Annotated[str, Query(min_length=1)]) -> Response:
        with con:
            deleted = con.execute("DELETE FROM exclusions WHERE pattern = ?", (pattern.strip(),)).rowcount
            if not deleted:
                raise ApiError(404, "not_found", f"除外リストにありません: {pattern}")
            _reanalyze(con)
        return Response(status_code=204)

    if static_dir is not None:
        # /api 以外は画面のファイル。API の道筋を先に登録してあるので、そちらが優先される
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app
