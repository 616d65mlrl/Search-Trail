// 点が多いとき（2,000超）の WebGL 描画用に、graphology のグラフを作る（FR-15、02 システム構成）
// 描画そのもの（sigma.js）は GraphWebGL.vue。ここは WebGL の無いテスト環境でも確かめられる純粋な部分。

import Graph from 'graphology'
import type { GraphEdge, GraphNode } from '../api/types'
import type { Point } from './layout'
import { nodeRadius, shortTitle } from './style'

export interface WebglNodeAttributes {
  x: number
  y: number
  size: number
  color: string
  label: string
}

export interface WebglEdgeAttributes {
  kind: GraphEdge['kind']
  size: number
  color: string
}

export function buildGraphology(
  nodes: GraphNode[],
  edges: GraphEdge[],
  layout: Map<string, Point>,
  colorOf: (n: GraphNode) => string,
): Graph<WebglNodeAttributes, WebglEdgeAttributes> {
  const graph = new Graph<WebglNodeAttributes, WebglEdgeAttributes>({ multi: false, type: 'directed' })
  const byId = new Map(nodes.map((n) => [n.id, n]))
  for (const n of nodes) {
    const p = layout.get(n.id) ?? { x: 0, y: 0 }
    // sigma.js は上が y の正の向きなので、SVG（下が正）と同じ見た目になるよう上下を反転する
    graph.addNode(n.id, { x: p.x, y: -p.y, size: nodeRadius(n.visits), color: colorOf(n), label: shortTitle(n.title, n.url) })
  }
  for (const e of edges) {
    const target = byId.get(e.target)
    if (!target || !byId.has(e.source) || e.kind === 'mention' || graph.hasEdge(e.source, e.target)) continue
    graph.addDirectedEdge(e.source, e.target, { kind: e.kind, size: e.kind === 'nav' ? 1 : 0.8, color: colorOf(target) })
  }
  return graph
}
