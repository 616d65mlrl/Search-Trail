// 履歴ログのレーン（04 アルゴリズム「画面側の計算」）
// 調べ物ごとに時刻順に見て、来た元の最初の子は来た元と同じレーン、2番目以降の子は新しいレーンにする。
// レーンは最大6本で、超えた分は最後のレーンにまとめる。

import type { GraphEdge, GraphNode } from '../api/types'

export const MAX_LANES = 6

type NodeLike = Pick<GraphNode, 'id' | 'session_id' | 'first_visit_at'>

// 行き先 → 来た元。来た元が複数あるときは、行き先より前に開いた中で一番新しいものを選ぶ
export function parentMap(nodes: NodeLike[], edges: GraphEdge[]): Map<string, string> {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const candidates = new Map<string, NodeLike[]>()
  for (const e of edges) {
    const source = byId.get(e.source)
    if (e.kind !== 'nav' || !source || !byId.has(e.target)) continue
    candidates.set(e.target, [...(candidates.get(e.target) ?? []), source])
  }

  const parents = new Map<string, string>()
  for (const [targetId, sources] of candidates) {
    const at = byId.get(targetId)!.first_visit_at
    const before = sources.filter((s) => s.first_visit_at <= at)
    const pick = before.length
      ? before.reduce((a, b) => (b.first_visit_at > a.first_visit_at ? b : a))
      : sources.reduce((a, b) => (b.first_visit_at < a.first_visit_at ? b : a))
    parents.set(targetId, pick.id)
  }
  return parents
}

export function assignLanes(nodes: NodeLike[], edges: GraphEdge[]): Map<string, number> {
  const parents = parentMap(nodes, edges)
  const lanes = new Map<string, number>()
  const hasChild = new Set<string>()
  const nextLane = new Map<number, number>() // 調べ物ごとの、次に使う新しいレーン

  const ordered = [...nodes].sort((a, b) => a.first_visit_at - b.first_visit_at || a.id.localeCompare(b.id))
  for (const node of ordered) {
    const parent = parents.get(node.id)
    let lane = 0
    if (parent !== undefined && lanes.has(parent)) {
      if (!hasChild.has(parent)) {
        lane = lanes.get(parent)!
      } else {
        const next = nextLane.get(node.session_id) ?? 1
        lane = Math.min(next, MAX_LANES - 1)
        nextLane.set(node.session_id, next + 1)
      }
      hasChild.add(parent)
    }
    lanes.set(node.id, lane)
  }
  return lanes
}
