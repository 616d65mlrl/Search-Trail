"""訪問を「調べ物」に分ける（FR-05、04 アルゴリズムの「調べ物の分割」）。

- 来た元がある訪問は、空き時間に関係なく来た元と同じ調べ物に入れる。
- 来た元がない訪問は、直前の訪問から 30 分以上空いていれば新しい調べ物を始め、
  30 分未満なら直前の訪問の調べ物に入れる。

毎回すべて計算し直すが、出発点の訪問が同じ調べ物は前と同じ ID を使い回す。
画面の点の ID（s{調べ物ID}-p{ページID}）を変えないためと、手で直した名前を残すため。
"""

from __future__ import annotations

import sqlite3

# 新しい調べ物を始める空き時間（設定で変えられるように引数で受け取る）
DEFAULT_SESSION_GAP_MS = 30 * 60 * 1000
COLOR_COUNT = 6  # 05 画面仕様の6色


def split_sessions(con: sqlite3.Connection, gap_ms: int = DEFAULT_SESSION_GAP_MS) -> None:
    # 来た元を決めていない訪問（同期された訪問、除外ページの訪問）は調べ物に入れない
    rows = con.execute(
        """
        SELECT v.id, v.visited_at, v.parent_visit_id
        FROM visits v JOIN pages p ON p.id = v.page_id
        WHERE v.synced = 0 AND p.excluded = 0
        ORDER BY v.visited_at, v.chrome_visit_id
        """
    ).fetchall()

    # 訪問ID → 調べ物の番号（この関数の中だけの仮の番号）
    group_of: dict[int, int] = {}
    groups: list[list[tuple[int, int]]] = []  # 調べ物ごとの (訪問ID, 時刻)
    last: tuple[int, int] | None = None  # 直前の訪問の (訪問ID, 時刻)
    for visit_id, at, parent_id in rows:
        if parent_id is not None and parent_id in group_of:
            g = group_of[parent_id]
        elif last is not None and at - last[1] < gap_ms:
            g = group_of[last[0]]
        else:
            g = len(groups)
            groups.append([])
        group_of[visit_id] = g
        groups[g].append((visit_id, at))
        last = (visit_id, at)

    # 前回の調べ物を、出発点の訪問で引けるようにしておく
    old = {
        root: (sid, name, manual)
        for sid, root, name, manual in con.execute(
            "SELECT id, root_visit_id, name, name_is_manual FROM sessions"
        )
    }
    next_id = max((sid for sid, _, _ in old.values()), default=0) + 1

    con.execute("UPDATE visits SET session_id = NULL")
    con.execute("DELETE FROM sessions")

    # 色は開始時刻の順に割り当てる
    groups.sort(key=lambda members: members[0][1])
    for rank, members in enumerate(groups):
        root_id = members[0][0]
        if root_id in old:
            sid, name, manual = old[root_id]
        else:
            sid, name, manual = next_id, None, 0
            next_id += 1
        times = [at for _, at in members]
        con.execute(
            "INSERT INTO sessions (id, started_at, ended_at, root_visit_id, name, name_is_manual, color_index)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, min(times), max(times), root_id, name, manual, rank % COLOR_COUNT),
        )
        con.executemany("UPDATE visits SET session_id = ? WHERE id = ?", [(sid, vid) for vid, _ in members])
