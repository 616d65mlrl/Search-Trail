// API が返す形（06 API 仕様、backend/tadori/api/models.py と同じ）。時刻はすべて Unix ミリ秒（UTC）。
// docs 06 では OpenAPI から生成する方針。今は手で書き、生成ツールの導入時に置き換える。

export interface Range {
  from: number | null
  to: number | null
}

export interface Status {
  imported: boolean
  visits: number
  pages: number
  sessions: number
  range: Range | null
  last_import_at: number | null
}

export interface Session {
  id: number
  name: string | null
  started_at: number
  ended_at: number
  color_index: number
  page_count: number
}

export interface GraphSession {
  id: number
  name: string | null
  started_at: number
  color_index: number
}

export interface GraphNode {
  id: string
  session_id: number
  page_id: number
  title: string | null
  domain: string
  url: string
  visits: number
  first_visit_at: number
  branch_count: number
  past_count: number
}

export interface GraphEdge {
  source: string
  target: string
  kind: 'nav' | 'past' | 'mention'
  count?: number | null
  concept?: string | null
  score?: number | null
}

export interface GraphResponse {
  range: Range
  sessions: GraphSession[]
  nodes: GraphNode[]
  edges: GraphEdge[]
  concepts: { id: string; label: string; page_count: number }[]
}

export interface NodeRef {
  id: string
  title: string | null
}

export interface NodeDetail {
  node: { id: string; title: string | null; visits: number }
  parent: (NodeRef & { reason: string | null }) | null
  children: (NodeRef & { letter: string })[]
  past_links: (NodeRef & {
    session_id: number
    session_name: string | null
    session_started_at: number
    concept: string | null // null は「同じページ」
    relation: 'past' | 'later' // past = 相手が前の調べ物、later = 相手が後の調べ物
  })[]
  concepts: string[]
  visits: { visited_at: number; duration_ms: number }[]
}

export interface TangleResponse {
  session: { id: number; name: string | null }
  tree: { id: string; depth: number }[]
  others: {
    session: { id: number; name: string | null; started_at: number; relation: 'past' | 'later' }
    nodes: { id: string; title: string | null; linked: boolean }[]
  }[]
  bridges: { from: string; to: string; kind: string; label: string }[]
}

export interface BodyResult {
  page_id: number
  concepts: string[]
}

export interface ImportResult {
  added_visits: number
  skipped_visits: number
}

export interface ApiErrorBody {
  error: { code: string; message: string }
}
