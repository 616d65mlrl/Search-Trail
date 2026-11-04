import { describe, expect, it } from 'vitest'
import type { GraphEdge, GraphNode } from '../src/api/types'
import { buildGraphology } from '../src/graph/webgl'

function node(id: string, session_id: number, visits = 1): GraphNode {
  return { id, session_id, page_id: 0, title: `ページ ${id}`, domain: 'example.com', url: `https://example.com/${id}`,
    visits, first_visit_at: 0, branch_count: 0, past_count: 0 }
}

describe('WebGL 用のグラフ', () => {
  const nodes = [node('a', 1, 4), node('b', 1), node('x', 2)]
  const edges: GraphEdge[] = [
    { source: 'a', target: 'b', kind: 'nav', count: 1 },
    { source: 'x', target: 'a', kind: 'past', concept: 'python', score: 1 },
    { source: 'a', target: 'c1', kind: 'mention' }, // 概念の線は WebGL では描かない
    { source: 'a', target: 'zzz', kind: 'nav', count: 1 }, // 表示していない点への線は捨てる
  ]
  const layout = new Map([['a', { x: 10, y: 20 }], ['b', { x: 30, y: 40 }], ['x', { x: -5, y: 0 }]])
  const graph = buildGraphology(nodes, edges, layout, (n) => (n.session_id === 1 ? '#111111' : '#222222'))

  it('点の位置は SVG と同じ見た目になるよう上下を反転し、大きさは訪問回数の式で決める', () => {
    expect(graph.order).toBe(3)
    expect(graph.getNodeAttributes('a')).toMatchObject({ x: 10, y: -20, size: 4 + 2 * 2.6, color: '#111111', label: 'ページ a' })
  })

  it('線は遷移と過去とのつながりだけ。色は行き先の調べ物の色', () => {
    expect(graph.size).toBe(2)
    expect(graph.getEdgeAttributes(graph.edge('a', 'b')!)).toMatchObject({ kind: 'nav', color: '#111111' })
    expect(graph.getEdgeAttributes(graph.edge('x', 'a')!)).toMatchObject({ kind: 'past', color: '#111111' })
  })
})
