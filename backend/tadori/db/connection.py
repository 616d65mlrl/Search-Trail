"""解析用のデータベースを開き、テーブルがなければ作る。

ふだん（tadori serve）はメモリの中だけに作り、ファイルには保存しない（閲覧履歴を PC に残さないため）。
テストでは、一時フォルダのファイルを渡して中身を確かめることもある。
"""

import sqlite3
from pathlib import Path

MEMORY = ":memory:"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _migrate(con: sqlite3.Connection) -> None:
    """古い形の表を、今の形に合わせる。"""
    # 2026-11-03: past_links.concept_id を NULL 可にした（同じページのつながり）。
    # past_links は取り込みのたびに計算し直すデータなので、消して作り直してよい
    notnull = {row[1]: row[3] for row in con.execute("PRAGMA table_info(past_links)")}
    if notnull.get("concept_id") == 1:
        con.execute("DROP TABLE past_links")


def connect(db_path: Path | str = MEMORY, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """db_path を省略すると、メモリの中だけのデータベースになる（閉じると消える）。
    check_same_thread=False は、API のように「つないだスレッドと使うスレッドが違う」場合に使う。
    その場合も、1本の接続を同時に複数の処理から使ってはいけない。"""
    if str(db_path) != MEMORY:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    con.execute("PRAGMA foreign_keys = ON")
    _migrate(con)
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return con
