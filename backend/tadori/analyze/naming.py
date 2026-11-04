"""調べ物の名前（FR-12、04 アルゴリズムの手順10）。

検索語か、いちばん多い概念から仮の名前をつける。
  1. 調べ物の中で、いちばん早い検索語
  2. 検索が無ければ、調べ物の中で重みの合計がいちばん大きい概念
  3. どちらも無ければ名前なし（画面では開始日で表示する）
手で直した名前（name_is_manual = 1）は上書きしない。
"""

import sqlite3


def auto_name(con: sqlite3.Connection, session_id: int) -> str | None:
    row = con.execute(
        """
        SELECT s.term FROM search_terms s JOIN visits v ON v.id = s.visit_id
        WHERE v.session_id = ? ORDER BY v.visited_at, v.chrome_visit_id LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if row:
        return row[0].strip()
    row = con.execute(
        """
        SELECT c.label FROM concepts c
        JOIN page_concepts pc ON pc.concept_id = c.id
        JOIN (SELECT DISTINCT page_id FROM visits WHERE session_id = ?) p ON p.page_id = pc.page_id
        GROUP BY c.id ORDER BY SUM(pc.weight) DESC, c.label LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    return row[0] if row else None


def name_sessions(con: sqlite3.Connection) -> None:
    ids = [r[0] for r in con.execute("SELECT id FROM sessions WHERE name_is_manual = 0")]
    con.executemany("UPDATE sessions SET name = ? WHERE id = ?", [(auto_name(con, sid), sid) for sid in ids])


def rename_session(con: sqlite3.Connection, session_id: int, name: str | None) -> None:
    """名前を手で直す。空欄なら自動の名前に戻す。"""
    name = (name or "").strip()
    if name:
        con.execute("UPDATE sessions SET name = ?, name_is_manual = 1 WHERE id = ?", (name, session_id))
    else:
        con.execute(
            "UPDATE sessions SET name = ?, name_is_manual = 0 WHERE id = ?", (auto_name(con, session_id), session_id)
        )
