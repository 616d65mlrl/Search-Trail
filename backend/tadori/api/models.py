"""API が返す形（06 API 仕様）。時刻はすべて Unix ミリ秒（UTC）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Range(BaseModel):
    # JSON では from と書く（Python では予約語なので from_）
    from_: int | None = Field(default=None, serialization_alias="from")
    to: int | None = None


class Status(BaseModel):
    imported: bool
    visits: int
    pages: int
    sessions: int
    range: Range | None
    last_import_at: int | None


class Session(BaseModel):
    id: int
    name: str | None
    started_at: int
    ended_at: int
    color_index: int
    page_count: int


class GraphSession(BaseModel):
    id: int
    name: str | None
    started_at: int
    color_index: int


class GraphNode(BaseModel):
    id: str
    session_id: int
    page_id: int
    title: str | None
    domain: str
    url: str
    visits: int
    first_visit_at: int
    branch_count: int
    past_count: int


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str
    count: int | None = None
    concept: str | None = None
    score: float | None = None


class GraphConcept(BaseModel):
    id: str
    label: str
    page_count: int


class GraphResponse(BaseModel):
    range: Range
    sessions: list[GraphSession]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    concepts: list[GraphConcept]


class NodeRef(BaseModel):
    id: str
    title: str | None


class NodeSummary(BaseModel):
    id: str
    title: str | None
    visits: int


class ParentRef(NodeRef):
    reason: str | None


class ChildRef(NodeRef):
    letter: str


class PastLinkRef(NodeRef):
    session_id: int
    session_name: str | None
    session_started_at: int
    concept: str | None  # None は「同じページ」
    relation: str  # past = 相手が前の調べ物、later = 相手が後の調べ物


class VisitTime(BaseModel):
    visited_at: int
    duration_ms: int


class NodeDetail(BaseModel):
    node: NodeSummary
    parent: ParentRef | None
    children: list[ChildRef]
    past_links: list[PastLinkRef]
    concepts: list[str]
    visits: list[VisitTime]


class TangleSessionRef(BaseModel):
    id: int
    name: str | None


class TangleTreeItem(BaseModel):
    id: str
    depth: int


class TangleOtherSession(BaseModel):
    id: int
    name: str | None
    started_at: int
    relation: str  # past = 前の調べ物、later = 後の調べ物


class TangleOtherNode(BaseModel):
    id: str
    title: str | None
    linked: bool


class TangleOther(BaseModel):
    session: TangleOtherSession
    nodes: list[TangleOtherNode]


class TangleBridge(BaseModel):
    from_: str = Field(serialization_alias="from")
    to: str
    kind: str
    label: str


class TangleResponse(BaseModel):
    session: TangleSessionRef
    tree: list[TangleTreeItem]
    others: list[TangleOther]
    bridges: list[TangleBridge]


class SearchHit(BaseModel):
    id: str
    title: str | None
    domain: str
    session_id: int
    first_visit_at: int


class Exclusion(BaseModel):
    id: int
    pattern: str


class ExclusionIn(BaseModel):
    pattern: str


class ImportResult(BaseModel):
    added_visits: int
    skipped_visits: int


class BodyResult(BaseModel):
    page_id: int
    concepts: list[str]  # 本文から取れた概念の表示名


class SessionNameIn(BaseModel):
    name: str | None = None  # 空欄なら自動の名前に戻す
