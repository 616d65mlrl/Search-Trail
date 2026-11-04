"""訪問ごとに「来た元」を決める（FR-04、04 アルゴリズムの「来た元の決め方」）。

上から順に試し、最初に見つかったものを使う。どれで決めたかを parent_reason に残す。
  1. from_visit（リンク元）                → from_visit
  2. opener_visit（新しいタブの開き元）    → opener
  3. 直前の検索結果ページ（リンクのとき）  → search
  4. 3分以内の直前の訪問（リンクのとき）   → time
  どれも無ければ出発点（parent_visit_id も parent_reason も NULL）

差分取り込みでも結果が変わらないよう、毎回すべての訪問を計算し直す。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

LINK = 0

# 推定に使う時間の幅（仮の値。自分の履歴で試しながら直す）
SEARCH_WINDOW_MS = 10 * 60 * 1000
TIME_WINDOW_MS = 3 * 60 * 1000


@dataclass(frozen=True)
class _Visit:
    id: int
    chrome_visit_id: int
    visited_at: int
    transition_core: int
    from_visit: int | None
    opener_visit: int | None
    is_search: bool
    # 来た元の候補にしない訪問（同期された訪問、除外リストに合うページの訪問）
    transparent: bool


def _load(con: sqlite3.Connection) -> list[_Visit]:
    rows = con.execute(
        """
        SELECT v.id, v.chrome_visit_id, v.visited_at, v.transition_core,
               v.chrome_from_visit, v.chrome_opener_visit,
               p.url_norm LIKE 'search:%', v.synced OR p.excluded
        FROM visits v JOIN pages p ON p.id = v.page_id
        ORDER BY v.visited_at, v.chrome_visit_id
        """
    ).fetchall()
    return [_Visit(r[0], r[1], r[2], r[3], r[4], r[5], bool(r[6]), bool(r[7])) for r in rows]


class _Resolver:
    """Chrome 訪問ID から、来た元にできる訪問をさかのぼって探す。"""

    def __init__(self, con: sqlite3.Connection, visits: list[_Visit]):
        self.by_chrome_id = {v.chrome_visit_id: v for v in visits}
        # 取り込まなかった訪問は、来た元の手がかり（リンク元、開き元）だけを持っている
        self.skipped = {
            r[0]: (r[1], r[2])
            for r in con.execute(
                "SELECT chrome_visit_id, chrome_from_visit, chrome_opener_visit FROM skipped_visits"
            )
        }

    def resolve(self, chrome_id: int | None) -> _Visit | None:
        seen: set[int] = set()
        while chrome_id and chrome_id not in seen:
            seen.add(chrome_id)
            v = self.by_chrome_id.get(chrome_id)
            if v is not None and not v.transparent:
                return v
            # 来た元の候補にできない訪問は、その来た元へさかのぼる
            if v is not None:
                hints = (v.from_visit, v.opener_visit)
            elif chrome_id in self.skipped:
                hints = self.skipped[chrome_id]
            else:
                return None  # tadori.db に無い訪問（Chrome 側で消えた古い訪問など）
            chrome_id = hints[0] or hints[1]
        return None


def decide_parents(con: sqlite3.Connection) -> None:
    visits = _load(con)
    resolver = _Resolver(con, visits)
    decided: list[tuple[int | None, str | None, int]] = []

    last_visit: _Visit | None = None  # 時刻順で直前の、来た元の候補にできる訪問
    last_search: _Visit | None = None  # 同じく、直前の検索結果ページ

    for v in visits:
        parent: _Visit | None = None
        reason: str | None = None
        if not v.transparent:
            if (p := resolver.resolve(v.from_visit)) is not None:
                parent, reason = p, "from_visit"
            elif (p := resolver.resolve(v.opener_visit)) is not None:
                parent, reason = p, "opener"
            elif v.transition_core == LINK:
                if last_search is not None and v.visited_at - last_search.visited_at <= SEARCH_WINDOW_MS:
                    parent, reason = last_search, "search"
                elif last_visit is not None and v.visited_at - last_visit.visited_at <= TIME_WINDOW_MS:
                    parent, reason = last_visit, "time"
            # 自分自身を来た元にはしない（壊れた記録への備え）
            if parent is not None and parent.id == v.id:
                parent, reason = None, None

            last_visit = v
            if v.is_search:
                last_search = v

        decided.append((parent.id if parent else None, reason, v.id))

    con.executemany("UPDATE visits SET parent_visit_id = ?, parent_reason = ? WHERE id = ?", decided)
