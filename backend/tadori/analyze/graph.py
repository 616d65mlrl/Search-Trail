"""点と線の集計と、分岐点（FR-06、04 アルゴリズムの「点、線、分岐点」）。

- 点 = （調べ物、ページ）の組。訪問回数と最初の訪問時刻を持つ。
- 線 = 来た元の関係を点同士にまとめたもの。同じ組の線は1本にし、回数を持たせる。
- 分岐点 = 同じ調べ物の中で、違うページへの線が2本以上出ている点。
- 再読み込みは訪問回数に数えない（滞在時間だけ足す）。
- 戻る・進むボタンの訪問は訪問回数だけ増やし、線は作らない。
- 過去とのつながり（FR-11）は、新しい側の点から古い側の点への kind="past" の線にする。

保存はせず、API から呼ばれるたびに期間と調べ物で絞って計算する。
"""

from __future__ import annotations

import sqlite3
import string
from dataclasses import dataclass, field

RELOAD = 8
FORWARD_BACK = 0x01000000


def node_id(session_id: int, page_id: int) -> str:
    """06 API 仕様の点の ID（例: s12-p34）。"""
    return f"s{session_id}-p{page_id}"


@dataclass
class Node:
    id: str
    session_id: int
    page_id: int
    title: str | None
    domain: str
    url_norm: str
    visits: int = 0
    duration_ms: int = 0
    first_visit_at: int = 0
    branch_count: int = 0
    past_count: int = 0  # 過去とのつながり（段階2）
    visit_times: list[tuple[int, int]] = field(default_factory=list)  # (時刻, 滞在時間)


@dataclass
class Edge:
    source: str
    target: str
    kind: str = "nav"
    count: int = 0
    first_at: int = 0  # この線を最初に通った時刻
    reason: str | None = None  # 最初に通ったときの来た元の決め方（parent_reason）
    concept: str | None = None  # 過去とのつながりの共通の概念（None は同じページ）
    score: float | None = None  # 過去とのつながりの点数


@dataclass
class Graph:
    nodes: dict[str, Node]
    edges: list[Edge]

    def children(self, nid: str) -> list[tuple[Node, str]]:
        """分岐先を、行き先の最初の訪問時刻の順に B、C、D… の文字つきで返す（A は分岐点自身）。"""
        targets = sorted(
            (self.nodes[e.target] for e in self.edges if e.source == nid and e.kind == "nav"),
            key=lambda n: (n.first_visit_at, n.id),
        )
        letters = string.ascii_uppercase[1:]
        return [(n, letters[i] if i < len(letters) else "") for i, n in enumerate(targets)]

    def parent_edge(self, nid: str) -> Edge | None:
        """この点へ最初に来た線。"""
        incoming = [e for e in self.edges if e.target == nid and e.kind == "nav"]
        return min(incoming, key=lambda e: e.first_at, default=None)

    def parent(self, nid: str) -> Node | None:
        """この点へ最初に来た線の元の点。"""
        edge = self.parent_edge(nid)
        return self.nodes[edge.source] if edge else None


@dataclass(frozen=True)
class PastLink:
    new: str  # 新しい側の点の ID
    old: str  # 古い側の点の ID
    concept: str | None  # None は同じページ
    score: float


def load_past_links(con: sqlite3.Connection) -> list[PastLink]:
    rows = con.execute(
        """
        SELECT nv.session_id, nv.page_id, ov.session_id, ov.page_id, c.label, pl.score
        FROM past_links pl
        JOIN visits nv ON nv.id = pl.new_visit_id
        JOIN visits ov ON ov.id = pl.old_visit_id
        LEFT JOIN concepts c ON c.id = pl.concept_id
        WHERE nv.session_id IS NOT NULL AND ov.session_id IS NOT NULL
        ORDER BY pl.score DESC, pl.id
        """
    ).fetchall()
    return [PastLink(node_id(ns, np), node_id(os_, op), label, score) for ns, np, os_, op, label, score in rows]


def build_graph(
    con: sqlite3.Connection,
    from_ms: int | None = None,
    to_ms: int | None = None,
    session_ids: list[int] | None = None,
) -> Graph:
    """期間（from_ms 以上 to_ms 未満）と調べ物で絞った点と線を作る。"""
    where = ["v.session_id IS NOT NULL"]
    params: list[object] = []
    if from_ms is not None:
        where.append("v.visited_at >= ?")
        params.append(from_ms)
    if to_ms is not None:
        where.append("v.visited_at < ?")
        params.append(to_ms)
    if session_ids is not None:
        where.append(f"v.session_id IN ({','.join('?' * len(session_ids))})")
        params.extend(session_ids)

    rows = con.execute(
        f"""
        SELECT v.id, v.session_id, v.page_id, v.visited_at, v.duration_ms, v.transition_core,
               v.transition_flags, v.parent_visit_id, v.parent_reason, p.title, p.domain, p.url_norm
        FROM visits v JOIN pages p ON p.id = v.page_id
        WHERE {' AND '.join(where)}
        ORDER BY v.visited_at, v.chrome_visit_id
        """,
        params,
    ).fetchall()

    nodes: dict[str, Node] = {}
    node_of_visit: dict[int, str] = {}
    edges: dict[tuple[str, str], Edge] = {}

    for (visit_id, session_id, page_id, at, duration, core, flags, parent_id, reason,
         title, domain, url_norm) in rows:
        nid = node_id(session_id, page_id)
        node = nodes.get(nid)
        if node is None:
            node = nodes[nid] = Node(nid, session_id, page_id, title, domain, url_norm, first_visit_at=at)
        node_of_visit[visit_id] = nid
        node.duration_ms += duration
        node.visit_times.append((at, duration))

        if core == RELOAD:
            continue  # 再読み込みは、滞在時間だけ足す
        node.visits += 1
        if flags & FORWARD_BACK:
            continue  # 戻る・進むは、新しい枝を作らない

        # 来た元が期間の外なら線は引かない（期間内の訪問だけで作り直す）
        source = node_of_visit.get(parent_id) if parent_id is not None else None
        if source is not None and source != nid:
            edge = edges.setdefault((source, nid), Edge(source, nid, first_at=at, reason=reason))
            edge.count += 1

    for edge in edges.values():
        nodes[edge.source].branch_count += 1
    # 行き先が1つだけなら分岐点ではない
    for node in nodes.values():
        if node.branch_count < 2:
            node.branch_count = 0

    # 過去とのつながりは、両端の点が表示範囲にあるものだけ
    past = [
        Edge(link.new, link.old, kind="past", concept=link.concept, score=link.score)
        for link in load_past_links(con)
        if link.new in nodes and link.old in nodes
    ]
    for edge in past:
        nodes[edge.source].past_count += 1
        nodes[edge.target].past_count += 1

    return Graph(nodes, list(edges.values()) + past)
