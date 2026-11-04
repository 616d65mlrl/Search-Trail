"""履歴のコピーと差分読み込み（FR-01、FR-02、NFR-06）のテスト。"""

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

from tadori.ingest.chrome import HistoryError, chrome_time_to_unix_ms
from tadori.ingest.importer import import_history
from tests.fixtures.make_fake_history import (
    JST,
    LINK,
    SERVER_REDIRECT,
    SINGLE,
    VISITS,
    build,
    to_chrome_time,
)


# 取り込まない訪問: 埋め込み動画（w2s）、短縮 URL の転送の途中（g2r）、chrome://settings（gx）
SKIPPED_KEYS = {"w2s", "g2r", "gx"}
STORED = len(VISITS) - len(SKIPPED_KEYS)


@pytest.fixture
def history(tmp_path):
    path = tmp_path / "chrome" / "History"
    path.parent.mkdir()
    ids = build(path)
    return path, ids


def _add_visit(con: sqlite3.Connection, url: str, at: datetime) -> None:
    """History に訪問を1件足す（Chrome が新しいページを開いた状態の再現）。"""
    url_id = con.execute(
        "INSERT INTO urls (url, title, last_visit_time) VALUES (?, ?, ?)", (url, "追加", to_chrome_time(at))
    ).lastrowid
    con.execute(
        "INSERT INTO visits (url, visit_time, from_visit, transition, visit_duration, opener_visit)"
        " VALUES (?, ?, 0, ?, 0, 0)",
        (url_id, to_chrome_time(at), LINK | SINGLE),
    )
    con.commit()


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(db, sql, *params):
    with closing(sqlite3.connect(db)) as con:
        return con.execute(sql, params).fetchall()


def test_chrome_time_to_unix_ms():
    at = datetime(2025, 10, 12, 21, 2, tzinfo=JST)
    assert chrome_time_to_unix_ms(to_chrome_time(at)) == 1760270520000


def test_first_import_reads_all_visits(history, tmp_path):
    path, ids = history
    db = tmp_path / "tadori.db"
    result = import_history(path, db)

    assert (result.added_visits, result.skipped_visits) == (STORED, len(SKIPPED_KEYS))
    # 取り込まなかった訪問も含めて、どこまで読んだかを覚える
    assert result.last_chrome_visit_id == max(ids.values())
    assert _rows(db, "SELECT COUNT(*) FROM visits")[0][0] == STORED
    # 同じ URL は1ページにまとまる（Lens は3回訪問されている）
    lens = _rows(db, "SELECT COUNT(*) FROM visits v JOIN pages p ON p.id = v.page_id"
                      " WHERE p.url_norm = 'https://github.com/textlens/lens'")
    assert lens[0][0] == 3


def test_visit_fields_are_converted(history, tmp_path):
    path, ids = history
    db = tmp_path / "tadori.db"
    import_history(path, db)

    def visit(key):
        return _rows(db, "SELECT visited_at, duration_ms, transition_core, transition_flags,"
                         " chrome_from_visit, chrome_opener_visit, synced"
                         " FROM visits WHERE chrome_visit_id = ?", ids[key])[0]

    # 時刻は Unix ミリ秒、滞在時間はミリ秒
    assert visit("g0")[:2] == (1760270520000, 30_000)
    # 転送の印は、符号付きで保存されていても正しく取り出せる
    assert visit("g2")[3] & SERVER_REDIRECT
    # 来た元が無いときは 0 ではなく NULL
    assert visit("g5")[4:6] == (None, ids["g2"])
    # スマホから同期された訪問には印がつく
    assert visit("gs")[6] == 1 and visit("g0")[6] == 0
    # 検索語は、検索結果ページの訪問につく
    assert _rows(db, "SELECT term FROM search_terms s JOIN visits v ON v.id = s.visit_id"
                     " WHERE v.chrome_visit_id = ?", ids["g0"]) == [("OCR 作り方",)]


def test_second_import_adds_only_new_visits(history, tmp_path):
    path, _ = history
    db = tmp_path / "tadori.db"
    import_history(path, db)

    assert import_history(path, db).added_visits == 0

    with closing(sqlite3.connect(path)) as con:
        _add_visit(con, "https://example.com/new", datetime(2025, 10, 20, 9, 0, tzinfo=JST))
    assert import_history(path, db).added_visits == 1
    assert _rows(db, "SELECT COUNT(*) FROM visits")[0][0] == STORED + 1
    assert [r[0] for r in _rows(db, "SELECT added_visits FROM import_runs ORDER BY id")] == [STORED, 0, 1]


def test_visits_only_in_wal_are_imported(history, tmp_path):
    """History-wal にだけ書かれた直近の訪問も取り込める（03 データ設計の約束1）。"""
    path, _ = history
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        # 自動で本体へ書き戻さないようにして、訪問が -wal にだけある状態を作る
        con.execute("PRAGMA wal_autocheckpoint=0")
        _add_visit(con, "https://example.com/only-in-wal", datetime(2025, 10, 20, 9, 0, tzinfo=JST))
        assert path.with_name("History-wal").stat().st_size > 0

        db = tmp_path / "tadori.db"
        result = import_history(path, db)
    finally:
        con.close()

    assert result.added_visits == STORED + 1
    assert _rows(db, "SELECT 1 FROM pages WHERE url_norm = 'https://example.com/only-in-wal'")


def test_original_history_is_not_modified(history, tmp_path):
    path, _ = history
    before = _sha256(path)
    import_history(path, tmp_path / "tadori.db")
    assert _sha256(path) == before
    # 元のフォルダに、-wal などの新しいファイルも作らない
    assert sorted(p.name for p in path.parent.iterdir()) == ["History"]


def test_history_without_opener_column(history, tmp_path):
    """古い Chrome の History には opener_visit が無い。それでも取り込める。"""
    path, _ = history
    with closing(sqlite3.connect(path)) as con:
        con.execute("ALTER TABLE visits DROP COLUMN opener_visit")
        con.commit()
    db = tmp_path / "tadori.db"
    assert import_history(path, db).added_visits == STORED
    assert _rows(db, "SELECT COUNT(*) FROM visits WHERE chrome_opener_visit IS NOT NULL")[0][0] == 0


def test_missing_history_file(tmp_path):
    with pytest.raises(HistoryError, match="見つかりません"):
        import_history(tmp_path / "nothing" / "History", tmp_path / "tadori.db")


def test_skipped_visits_keep_only_parent_hints(history, tmp_path):
    """取り込まない訪問は、来た元をさかのぼる手がかりだけを残す。"""
    path, ids = history
    db = tmp_path / "tadori.db"
    import_history(path, db)

    assert _rows(db, "SELECT chrome_visit_id, chrome_from_visit, chrome_opener_visit, reason"
                     " FROM skipped_visits ORDER BY chrome_visit_id") == [
        (ids["w2s"], ids["w2"], None, "subframe"),
        (ids["g2r"], ids["g1"], None, "redirect"),
        (ids["gx"], None, None, "internal"),
    ]
    assert not _rows(db, "SELECT 1 FROM pages WHERE url_norm LIKE 'chrome:%' OR domain = 'www.youtube.com'")


def test_pages_are_normalized(history, tmp_path):
    path, _ = history
    db = tmp_path / "tadori.db"
    import_history(path, db)
    keys = {r[0] for r in _rows(db, "SELECT url_norm FROM pages")}

    # 追跡用の引数が消え、再読み込みと同じ1ページになる
    assert "https://tutorials.github.io/learn-aiohttp" in keys
    assert not any("utm_" in k for k in keys)
    # # 以降と末尾の / が消える
    assert "https://zenn.dev/example/articles/document-ocr" in keys
    assert "https://github.com/dashcore/dash" in keys
    # 検索結果ページは検索語の鍵になり、検索語は正規化して保存される
    assert {"search:ocr 作り方", "search:python 辞書", "search:websocket python"} <= keys
    assert _rows(db, "SELECT term_norm FROM search_terms WHERE term = 'OCR 作り方'") == [("ocr 作り方",)]


def test_exclusion_list_marks_pages(history, tmp_path):
    """除外リストに合うページは消さずに印をつけ、リストから外せば印も外れる（FR-16）。"""
    from tadori.db.connection import connect
    from tadori.ingest.exclude import refresh_page_exclusions

    path, _ = history
    db = tmp_path / "tadori.db"
    with closing(connect(db)) as con:
        con.execute("INSERT INTO exclusions (pattern) VALUES ('*.example.com'), ('github.com/dashcore/*')")
        con.commit()
    import_history(path, db)

    excluded = {r[0] for r in _rows(db, "SELECT url_norm FROM pages WHERE excluded = 1")}
    assert excluded == {
        "https://news.example.com/",
        "https://github.com/dashcore/dash",
    }

    with closing(connect(db)) as con:
        con.execute("DELETE FROM exclusions")
        refresh_page_exclusions(con)
        con.commit()
    assert _rows(db, "SELECT COUNT(*) FROM pages WHERE excluded = 1")[0][0] == 0
