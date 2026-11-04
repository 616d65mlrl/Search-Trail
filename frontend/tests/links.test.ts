import { describe, expect, it } from 'vitest'
import type { GraphEdge } from '../src/api/types'
import { arcPath, SAME_PAGE, sessionLinks, strongest, type SessionLink } from '../src/graph/links'

const nodes = [
  { id: 's1-p1', session_id: 1 },
  { id: 's1-p2', session_id: 1 },
  { id: 's2-p3', session_id: 2 },
  { id: 's2-p4', session_id: 2 },
  { id: 's3-p1', session_id: 3 },
]
const past = (source: string, target: string, concept: string | null, score = 1): GraphEdge => ({
  source,
  target,
  kind: 'past',
  concept,
  score,
})

describe('調べ物どうしのつながり（FR-11）', () => {
  const edges: GraphEdge[] = [
    { source: 's1-p1', target: 's1-p2', kind: 'nav' },
    past('s2-p3', 's1-p1', 'python', 2),
    past('s2-p4', 's1-p2', 'python', 1),
    past('s2-p4', 's1-p1', 'aiohttp', 3),
    past('s3-p1', 's1-p1', null, 5),
  ]

  it('点どうしの線を、調べ物の組ごとに1本にまとめる', () => {
    const links = sessionLinks(nodes, edges)
    expect(links).toHaveLength(1)
    const [l] = links
    expect(l).toMatchObject({ newer: 2, older: 1, count: 3, concepts: ['python', 'aiohttp'], samePageOnly: false })
    // 弧を選んだときは、いちばん点数の高い線の点を選ぶ
    expect(l!.best.source).toBe('s2-p4')
  })

  it('同じページだけのつながりは、頼んだときだけ出す', () => {
    const links = sessionLinks(nodes, edges, { samePage: true })
    expect(links).toHaveLength(2)
    expect(links[1]).toMatchObject({ newer: 3, older: 1, concepts: [SAME_PAGE], samePageOnly: true })
  })

  it('表示していない点の線は数えない', () => {
    expect(sessionLinks(nodes.slice(0, 2), edges)).toEqual([])
  })
})

describe('強いつながりだけを残す', () => {
  const link = (newer: number, older: number, count: number): SessionLink => ({
    newer, older, count, concepts: ['x'], samePageOnly: false, best: past(`s${newer}-p1`, `s${older}-p1`, 'x'),
  })
  // 調べ物4は、1・2・3とつながる（本数 5、3、1）
  const links = [link(4, 1, 5), link(4, 2, 3), link(4, 3, 1)]

  it('調べ物ごとに、本数の多いものから決まった数だけ残す', () => {
    // 4→3 は、4 にとっては3番目だが、3 にとっては唯一のつながりなので残る
    expect(strongest(links, 1).map((l) => l.older)).toEqual([1, 2, 3])
    expect(strongest([link(4, 1, 5), link(4, 2, 3), link(4, 3, 1), link(3, 1, 9)], 1).map((l) => `${l.newer}>${l.older}`))
      .toEqual(['4>1', '4>2', '3>1'])
  })

  it('選んだ調べ物のつながりは、すべて残す', () => {
    const more = [link(4, 1, 5), link(3, 1, 9), link(4, 3, 1)]
    expect(strongest(more, 1).map((l) => `${l.newer}>${l.older}`)).toEqual(['4>1', '3>1'])
    expect(strongest(more, 1, 4)).toHaveLength(3)
  })
})

describe('弧の形', () => {
  it('離れた行ほど大きな弧になるが、横幅はおさえる', () => {
    expect(arcPath(100, 50, 10, 200)).toBe('M100,10 A20,20 0 0 1 100,50')
    expect(arcPath(100, 0, 1000, 200)).toBe('M100,0 A200,500 0 0 1 100,1000')
  })
})
