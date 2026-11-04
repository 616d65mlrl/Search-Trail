"""過去とのつながり（FR-11、04 アルゴリズムの「過去とのつながり」）。

新しい調べ物の点 n と、それより前の調べ物の点 m が同じ概念 c を持つとき、

    score(n, m, c) = w_n(c) × w_m(c) × log(N / df(c))

w は概念の重み、N はページの総数、df(c) は概念 c を持つページの数。どこにでも出る概念ほど点数が下がる。
線が増えすぎないよう、点ごとに点数の高い3本まで、1つの古い調べ物につき1本までにする。

同じページを別の調べ物で開いたときも、つながりにする（03 データ設計）。概念は NULL とし、
どの概念よりも高い点数（log(N) + 1）を与える。
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

MAX_LINKS_PER_NODE = 3


@dataclass(frozen=True)
class _Node:
    session_id: int
    page_id: int
    first_visit_id: int
    first_visit_at: int
    session_started_at: int


def _load_nodes(con: sqlite3.Connection) -> list[_Node]:
    rows = con.execute(
        """
        SELECT v.id, v.session_id, v.page_id, v.visited_at, s.started_at
        FROM visits v JOIN sessions s ON s.id = v.session_id
        ORDER BY v.visited_at, v.chrome_visit_id
        """
    ).fetchall()
    nodes: dict[tuple[int, int], _Node] = {}
    for visit_id, session_id, page_id, at, started_at in rows:
        nodes.setdefault((session_id, page_id), _Node(session_id, page_id, visit_id, at, started_at))
    return list(nodes.values())


def link_past(con: sqlite3.Connection) -> None:
    con.execute("DELETE FROM past_links")
    nodes = _load_nodes(con)
    if not nodes:
        return

    # ページごとの概念の重み（材料が複数あるときは大きいほう）
    weights: dict[int, dict[int, float]] = defaultdict(dict)
    for page_id, concept_id, weight in con.execute(
        "SELECT page_id, concept_id, MAX(weight) FROM page_concepts GROUP BY page_id, concept_id"
    ):
        weights[page_id][concept_id] = weight

    pages = {n.page_id for n in nodes}
    total = len(pages)
    df: dict[int, int] = defaultdict(int)
    for page_id in pages:
        for concept_id in weights.get(page_id, {}):
            df[concept_id] += 1
    same_page_score = math.log(max(total, 2)) + 1

    nodes_with_concept: dict[int, list[_Node]] = defaultdict(list)
    nodes_of_page: dict[int, list[_Node]] = defaultdict(list)
    for n in nodes:
        nodes_of_page[n.page_id].append(n)
        for concept_id in weights.get(n.page_id, {}):
            nodes_with_concept[concept_id].append(n)

    rows: list[tuple[int, int, int | None, float]] = []
    for n in nodes:
        # 古い調べ物ごとに、いちばん点数の高いつながりを1本だけ選ぶ
        best: dict[int, tuple[float, int, int, int | None]] = {}  # 古い調べ物 → (点数, 時刻, 訪問, 概念)

        def consider(m: _Node, score: float, concept_id: int | None) -> None:
            if m.session_started_at >= n.session_started_at or m.session_id == n.session_id:
                return  # 新しい側から、それより前の調べ物へだけ結ぶ
            # 点数が同じなら、先に開いたほうを選ぶ（毎回同じ結果にするため）
            key = (score, -m.first_visit_at)
            current = best.get(m.session_id)
            if current is None or key > (current[0], -current[1]):
                best[m.session_id] = (score, m.first_visit_at, m.first_visit_id, concept_id)

        for m in nodes_of_page[n.page_id]:
            consider(m, same_page_score, None)
        for concept_id, w_n in weights.get(n.page_id, {}).items():
            idf = math.log(total / df[concept_id])
            for m in nodes_with_concept[concept_id]:
                if m.page_id != n.page_id:
                    consider(m, w_n * weights[m.page_id][concept_id] * idf, concept_id)

        top = sorted(best.values(), key=lambda b: (-b[0], b[1]))[:MAX_LINKS_PER_NODE]
        rows.extend((n.first_visit_id, visit_id, concept_id, score) for score, _, visit_id, concept_id in top)

    con.executemany(
        "INSERT INTO past_links (new_visit_id, old_visit_id, concept_id, score) VALUES (?, ?, ?, ?)", rows
    )
