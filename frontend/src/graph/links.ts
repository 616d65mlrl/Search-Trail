// 「つながり」の表示（LinksView）の計算。過去とのつながり（FR-11）を、調べ物どうしの組にまとめる。
// 点どうしの線をそのまま描くと数が多すぎて読めないので、「どの調べ物が、どの過去の調べ物と、何でつながったか」に絞る。
// 描き方はアークダイアグラム: 調べ物を時刻順に1行ずつ並べ、つながった行どうしを弧で結ぶ。名前は横書きのまま読める。

import type { GraphEdge, GraphNode } from '../api/types'

export const SAME_PAGE = '同じページ'

export interface SessionLink {
  newer: number // 新しい側の調べ物
  older: number // 古い側の調べ物
  count: number // まとめた線の本数
  concepts: string[] // 何でつながったか（本数の多い順。同じページのつながりは SAME_PAGE）
  samePageOnly: boolean // 同じページを開いただけのつながり（日課のページで起きやすい）
  best: GraphEdge // いちばん点数の高い線（弧を選んだときに、その点を選ぶ）
}

export function sessionLinks(
  nodes: Pick<GraphNode, 'id' | 'session_id'>[],
  edges: GraphEdge[],
  opts: { samePage?: boolean } = {},
): SessionLink[] {
  const sessionOf = new Map(nodes.map((n) => [n.id, n.session_id]))
  const groups = new Map<string, { newer: number; older: number; edges: GraphEdge[] }>()
  for (const e of edges) {
    if (e.kind !== 'past') continue
    if (!opts.samePage && e.concept == null) continue
    const newer = sessionOf.get(e.source)
    const older = sessionOf.get(e.target)
    if (newer === undefined || older === undefined || newer === older) continue
    const key = `${newer}>${older}`
    const g = groups.get(key) ?? { newer, older, edges: [] }
    g.edges.push(e)
    groups.set(key, g)
  }
  return [...groups.values()]
    .map(({ newer, older, edges: es }) => {
      const tally = new Map<string, number>()
      for (const e of es) tally.set(e.concept ?? SAME_PAGE, (tally.get(e.concept ?? SAME_PAGE) ?? 0) + 1)
      const concepts = [...tally].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([c]) => c)
      const best = es.reduce((a, b) => ((b.score ?? 0) > (a.score ?? 0) ? b : a))
      return { newer, older, count: es.length, concepts, samePageOnly: concepts.length === 1 && concepts[0] === SAME_PAGE, best }
    })
    .sort((a, b) => a.newer - b.newer || a.older - b.older)
}

// 調べ物ごとに、強いつながり（本数が多く、点数が高いもの）だけを残す。
// keep に入っている調べ物（選んだ調べ物）のつながりは、すべて残す
export function strongest(links: SessionLink[], perSession: number, keep?: number): SessionLink[] {
  const rank = new Map<SessionLink, number>()
  const bySession = new Map<number, SessionLink[]>()
  for (const l of links) {
    for (const s of [l.newer, l.older]) bySession.set(s, [...(bySession.get(s) ?? []), l])
  }
  for (const list of bySession.values()) {
    list
      .sort((a, b) => b.count - a.count || (b.best.score ?? 0) - (a.best.score ?? 0))
      .forEach((l, i) => rank.set(l, Math.min(rank.get(l) ?? Infinity, i)))
  }
  return links.filter((l) => rank.get(l)! < perSession || l.newer === keep || l.older === keep)
}

// 弧の形。行は上から下へ並び、弧は軸（x0）の右側へふくらむ。
// 離れた行どうしほど大きな弧になるが、横幅は maxRx までにおさえる（はみ出さないように縦長の楕円にする）
export function arcPath(x0: number, y1: number, y2: number, maxRx: number): string {
  const top = Math.min(y1, y2)
  const bottom = Math.max(y1, y2)
  const ry = (bottom - top) / 2
  const rx = Math.max(4, Math.min(ry, maxRx))
  return `M${x0},${top} A${rx},${ry} 0 0 1 ${x0},${bottom}`
}
