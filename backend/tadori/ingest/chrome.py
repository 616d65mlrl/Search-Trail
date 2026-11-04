"""Chrome の History ファイルをコピーして読む（FR-01、FR-02、03 データ設計）。

元のファイルには一切触らない（NFR-06）。History と History-wal を一時フォルダへコピーし、
コピーだけを開く。WAL 付きのファイルを読み取り専用で開くと失敗することがあり、
WAL を無視するモードでは直近の訪問が抜けるため、コピーは普通に開く。
"""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

# Chrome の時刻は「1601年1月1日（UTC）からのマイクロ秒」
CHROME_EPOCH_OFFSET_US = 11_644_473_600_000_000

# History と一緒にコピーするファイル。-wal に直近の変更が入っている
COMPANION_SUFFIXES = ("-wal", "-journal")

# これが無いと取り込めない列。opener_visit などの新しい列は、無くても動くようにする
REQUIRED_COLUMNS = {
    "urls": {"id", "url", "title", "hidden"},
    "visits": {"id", "url", "visit_time", "from_visit", "transition", "visit_duration"},
}


class HistoryError(Exception):
    """利用者に見せるための、取り込みの失敗。"""


@dataclass(frozen=True)
class ChromeVisit:
    chrome_visit_id: int
    url_id: int
    url: str
    title: str | None
    hidden: bool
    visited_at: int  # Unix ミリ秒（UTC）
    duration_ms: int
    transition: int
    from_visit: int | None
    opener_visit: int | None
    synced: bool
    search_term: str | None


def chrome_time_to_unix_ms(chrome_us: int) -> int:
    return (chrome_us - CHROME_EPOCH_OFFSET_US) // 1000


def copy_history(src: Path, dest_dir: Path) -> Path:
    """History と、あれば History-wal などを dest_dir へコピーし、コピーの場所を返す。"""
    src = Path(src)
    if not src.is_file():
        raise HistoryError(f"履歴ファイルが見つかりません: {src}")
    dest = Path(dest_dir) / "History"
    try:
        shutil.copyfile(src, dest)
        for suffix in COMPANION_SUFFIXES:
            companion = src.with_name(src.name + suffix)
            if companion.is_file():
                shutil.copyfile(companion, dest.with_name(dest.name + suffix))
    except PermissionError as e:
        raise HistoryError(
            f"履歴ファイルをコピーできませんでした（Chrome が使用中の可能性があります）: {e}"
        ) from e
    return dest


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def read_visits(history_copy: Path, after_id: int = 0) -> list[ChromeVisit]:
    """コピーした History から、Chrome 訪問ID が after_id より大きい訪問を古い順に読む。"""
    try:
        return _read_visits(history_copy, after_id)
    except sqlite3.DatabaseError as e:
        raise HistoryError(f"Chrome の History ファイルとして読めませんでした: {e}") from e


def _read_visits(history_copy: Path, after_id: int) -> list[ChromeVisit]:
    with closing(sqlite3.connect(history_copy)) as con:
        for table, required in REQUIRED_COLUMNS.items():
            missing = required - _columns(con, table)
            if missing:
                raise HistoryError(f"History の {table} に必要な列がありません: {sorted(missing)}")

        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        opener = "v.opener_visit" if "opener_visit" in _columns(con, "visits") else "NULL"
        # visit_source には、この PC 以外から来た訪問だけが入っている。source=0 が同期
        synced = (
            "EXISTS (SELECT 1 FROM visit_source s WHERE s.id = v.id AND s.source = 0)"
            if "visit_source" in tables
            else "0"
        )
        rows = con.execute(
            f"""
            SELECT v.id, u.id, u.url, u.title, u.hidden, v.visit_time, v.visit_duration,
                   v.transition, v.from_visit, {opener}, {synced}
            FROM visits v JOIN urls u ON u.id = v.url
            WHERE v.id > ?
            ORDER BY v.id
            """,
            (after_id,),
        ).fetchall()

        terms: dict[int, str] = {}
        if "keyword_search_terms" in tables:
            terms = dict(con.execute("SELECT url_id, term FROM keyword_search_terms"))

    return [
        ChromeVisit(
            chrome_visit_id=vid,
            url_id=url_id,
            url=url,
            title=title or None,
            hidden=bool(hidden),
            visited_at=chrome_time_to_unix_ms(visit_time),
            duration_ms=(duration or 0) // 1000,
            # 符号付き32ビットで保存され、転送の印（0x80000000）があると負の数になるため正に揃える
            transition=transition & 0xFFFFFFFF,
            # Chrome は「なし」を 0 で持つので、None に揃える
            from_visit=from_visit or None,
            opener_visit=opener_visit or None,
            synced=bool(is_synced),
            search_term=terms.get(url_id),
        )
        for (vid, url_id, url, title, hidden, visit_time, duration, transition,
             from_visit, opener_visit, is_synced) in rows
    ]
