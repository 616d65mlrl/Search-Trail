"""読んだ訪問を解析用のデータベースへ入れる（FR-01、FR-02、FR-03、FR-16）。

差分取り込み: import_runs に残した「最後の Chrome 訪問ID」より新しい訪問だけを読む。
取り込まない訪問は skipped_visits に、来た元の手がかりだけを残す。
同期された訪問は synced=1 で保存し、使うかどうかは解析と画面で決める。
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from tadori.analyze.pipeline import analyze
from tadori.db.connection import connect
from tadori.ingest.chrome import ChromeVisit, copy_history, read_visits
from tadori.ingest.exclude import refresh_page_exclusions, skip_reason
from tadori.ingest.normalize import normalize_term, normalize_url


@dataclass(frozen=True)
class ImportResult:
    added_visits: int
    skipped_visits: int
    last_chrome_visit_id: int


def last_imported_visit_id(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COALESCE(MAX(last_chrome_visit_id), 0) FROM import_runs").fetchone()[0]


def _page_id(con: sqlite3.Connection, key: str, domain: str, title: str | None) -> int:
    con.execute(
        "INSERT INTO pages (url_norm, title, domain) VALUES (?, ?, ?) ON CONFLICT(url_norm) DO NOTHING",
        (key, title, domain),
    )
    if title:
        # タイトルは新しい訪問のものを優先する
        con.execute("UPDATE pages SET title = ? WHERE url_norm = ?", (title, key))
    return con.execute("SELECT id FROM pages WHERE url_norm = ?", (key,)).fetchone()[0]


def _store(con: sqlite3.Connection, v: ChromeVisit) -> None:
    norm = normalize_url(v.url)
    page_id = _page_id(con, norm.key, norm.domain, v.title)
    cur = con.execute(
        """
        INSERT INTO visits (chrome_visit_id, page_id, visited_at, duration_ms, transition_core,
                            transition_flags, chrome_from_visit, chrome_opener_visit, synced)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (v.chrome_visit_id, page_id, v.visited_at, v.duration_ms, v.transition & 0xFF,
         v.transition & ~0xFF, v.from_visit, v.opener_visit, int(v.synced)),
    )
    # 検索語は Chrome の記録（keyword_search_terms）を優先し、無ければ URL から取り出したものを使う。
    # どちらも URL 単位なので、そのページで初めての訪問にだけつける
    term = v.search_term or norm.search_term
    if term:
        already = con.execute(
            "SELECT 1 FROM search_terms s JOIN visits w ON w.id = s.visit_id WHERE w.page_id = ?",
            (page_id,),
        ).fetchone()
        if not already:
            con.execute(
                "INSERT INTO search_terms (visit_id, term, term_norm) VALUES (?, ?, ?)",
                (cur.lastrowid, term, normalize_term(term)),
            )


def _skip(con: sqlite3.Connection, v: ChromeVisit, reason: str) -> None:
    con.execute(
        "INSERT INTO skipped_visits (chrome_visit_id, chrome_from_visit, chrome_opener_visit, reason)"
        " VALUES (?, ?, ?, ?)",
        (v.chrome_visit_id, v.from_visit, v.opener_visit, reason),
    )


# 履歴から作った表（選び直したときに空にする）。除外リスト・除外語・同義語は設定なので残す
HISTORY_TABLES = (
    "past_links", "page_concepts", "concepts", "search_terms", "visits", "sessions",
    "pages", "skipped_visits", "import_runs",
)


def import_history(history_path: Path, db: Path | sqlite3.Connection, *, replace: bool = False) -> ImportResult:
    """History を差分で取り込む。元の History は書き換えない。
    db は開いている接続（API のメモリの中のデータベース）か、ファイルの場所（テスト用）。
    replace=True なら、前に取り込んだ履歴を消してから全部を取り込む（History を読めたときだけ消す）。"""
    started_at = int(time.time() * 1000)
    own = not isinstance(db, sqlite3.Connection)
    con = connect(db) if own else db
    try:
        last_id = 0 if replace else last_imported_visit_id(con)
        # ignore_cleanup_errors: Windows で一時ファイルの削除が遅れても取り込みは失敗にしない
        with tempfile.TemporaryDirectory(prefix="tadori-", ignore_cleanup_errors=True) as tmp:
            visits = read_visits(copy_history(history_path, Path(tmp)), after_id=last_id)

        added = skipped = 0
        with con:  # 全部入るか、何も入らないか（途中で失敗しても半端に残さない）
            if replace:
                for table in HISTORY_TABLES:
                    con.execute(f"DELETE FROM {table}")
            for v in visits:
                reason = skip_reason(v)
                if reason:
                    _skip(con, v, reason)
                    skipped += 1
                else:
                    _store(con, v)
                    added += 1
            refresh_page_exclusions(con)
            analyze(con)
            new_last_id = max((v.chrome_visit_id for v in visits), default=last_id)
            con.execute(
                "INSERT INTO import_runs (started_at, last_chrome_visit_id, added_visits) VALUES (?, ?, ?)",
                (started_at, new_last_id, added),
            )
        return ImportResult(added_visits=added, skipped_visits=skipped, last_chrome_visit_id=new_last_id)
    finally:
        if own:
            con.close()
