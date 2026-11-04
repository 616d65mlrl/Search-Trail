import { describe, expect, it } from 'vitest'
import type { GraphEdge, GraphNode } from '../src/api/types'
import {
  bounds,
  bundleCurve,
  bundleRoute,
  computeLayout,
  DEPTH_STEP,
  labelLevel,
  midpointOf,
  treeParents,
} from '../src/graph/layout'
import { formatDuration, formatTime, nodeRadius, sessionColor } from '../src/graph/style'

function node(id: string, session_id: number, at: number, visits = 1): GraphNode {
  return { id, session_id, page_id: 0, title: id, domain: 'example.com', url: `https://example.com/${id}`,
    visits, first_visit_at: at, branch_count: 0, past_count: 0 }
}

const sessions = [
  { id: 1, started_at: 0 },
  { id: 2, started_at: 100 },
]
const nodes = [node('a', 1, 0), node('b', 1, 1), node('c', 1, 2), node('x', 2, 100), node('y', 2, 101)]
const edges: GraphEdge[] = [
  { source: 'a', target: 'b', kind: 'nav', count: 1 },
  { source: 'a', target: 'c', kind: 'nav', count: 1 },
  { source: 'x', target: 'y', kind: 'nav', count: 1 },
]

const dist = (p: { x: number; y: number }, q: { x: number; y: number }) => Math.hypot(p.x - q.x, p.y - q.y)
const radius = (p: { x: number; y: number }) => Math.hypot(p.x, p.y)
// 真上を 0 として、時計回りに測った角度（0〜2π）
const clockwise = (p: { x: number; y: number }) => (Math.atan2(p.y, p.x) + Math.PI / 2 + 2 * Math.PI) % (2 * Math.PI)

describe('グラフの配置（放射状の森）', () => {
  it('同じ入力からは同じ配置になる', () => {
    const first = computeLayout(nodes, edges, sessions)
    const second = computeLayout([...nodes].reverse(), edges, sessions)
    expect([...second.entries()].sort()).toEqual([...first.entries()].sort())
  })

  it('同じ調べ物の点は近くに、別の調べ物の点は離れて置かれる', () => {
    const pos = computeLayout(nodes, edges, sessions)
    expect(dist(pos.get('a')!, pos.get('b')!)).toBeLessThan(dist(pos.get('a')!, pos.get('x')!))
  })

  it('出発点は内側の輪に並び、たどった先ほど外側に置かれる', () => {
    const pos = computeLayout(nodes, edges, sessions)
    expect(radius(pos.get('a')!)).toBeCloseTo(radius(pos.get('x')!))
    expect(radius(pos.get('b')!)).toBeCloseTo(radius(pos.get('a')!) + DEPTH_STEP)
    expect(radius(pos.get('y')!)).toBeCloseTo(radius(pos.get('x')!) + DEPTH_STEP)
  })

  it('出発点は開いた時刻の順に、真上から時計回りに並ぶ', () => {
    const many = [node('r1', 1, 0), node('r2', 2, 10), node('r3', 3, 20), node('r4', 4, 30)]
    const pos = computeLayout(many, [], [])
    const angles = ['r1', 'r2', 'r3', 'r4'].map((id) => clockwise(pos.get(id)!))
    expect([...angles].sort((p, q) => p - q)).toEqual(angles)
  })

  it('子は親の扇の中に、葉の数に応じて広がる', () => {
    const pos = computeLayout(nodes, edges, sessions)
    const a = clockwise(pos.get('a')!)
    // a の2つの子は a をはさんで両側に置かれる
    expect(Math.min(clockwise(pos.get('b')!), clockwise(pos.get('c')!))).toBeLessThan(a)
    expect(Math.max(clockwise(pos.get('b')!), clockwise(pos.get('c')!))).toBeGreaterThan(a)
  })

  it('単発の点は、同じ頃に開いた出発点の隣に置かれる', () => {
    const list = [...nodes, node('solo', 3, 50), node('late', 4, 1000)]
    const pos = computeLayout(list, edges, [])
    const order = ['a', 'solo', 'x', 'late'].map((id) => clockwise(pos.get(id)!))
    expect([...order].sort((p, q) => p - q)).toEqual(order)
  })

  it('来た元が後から開いたページなら、木の親にしない（輪ができないように）', () => {
    const loop: GraphEdge[] = [
      { source: 'a', target: 'b', kind: 'nav' },
      { source: 'b', target: 'a', kind: 'nav' },
    ]
    const parents = treeParents([node('a', 1, 0), node('b', 1, 1)], loop)
    expect([...parents]).toEqual([['b', 'a']])
  })

  it('深い木でも止まらずに配置できる', () => {
    const chain = Array.from({ length: 5000 }, (_, i) => node(`n${i}`, 1, i))
    const navs: GraphEdge[] = chain.slice(1).map((n, i) => ({ source: `n${i}`, target: n.id, kind: 'nav' }))
    const pos = computeLayout(chain, navs, [])
    expect(pos.size).toBe(5000)
  })

  it('全体が収まる範囲', () => {
    expect(bounds([{ x: 0, y: 0 }, { x: 100, y: 50 }], 10)).toEqual({ x: -10, y: -10, w: 120, h: 70 })
  })
})

describe('線の形（階層に沿って束ねる）', () => {
  // 木: a → b → c（調べ物1）、d → e（調べ物2）
  const parents = new Map([
    ['b', 'a'],
    ['c', 'b'],
    ['e', 'd'],
  ])
  const at: Record<string, { x: number; y: number }> = {
    a: { x: 100, y: 0 },
    b: { x: 200, y: 0 },
    c: { x: 300, y: 20 },
    d: { x: 0, y: 100 },
    e: { x: 0, y: 200 },
  }
  const pos = (id: string) => at[id]!

  it('別の木へは、自分の幹をさかのぼり、輪の内側を通って渡る', () => {
    const route = bundleRoute('c', 'e', parents, pos)
    expect(route[0]).toEqual(at.c)
    expect(route[route.length - 1]).toEqual(at.e)
    // 出発点 a と d を経由し、その内側の点も通る
    expect(route).toContainEqual(at.a)
    expect(route).toContainEqual(at.d)
    expect(route.length).toBe(3 + 2 + 2)
    // 曲線の真ん中は、出発点の輪（半径 100）より内側にある
    expect(radius(midpointOf(bundleCurve(route)))).toBeLessThan(100)
  })

  it('同じ木の中では、共通の祖先で折り返す', () => {
    const route = bundleRoute('c', 'a', parents, pos)
    expect(route).toEqual([at.c, at.b, at.a])
  })

  it('曲線は両端の点をちょうど通る', () => {
    const curve = bundleCurve(bundleRoute('c', 'e', parents, pos))
    expect(curve[0]!.x).toBeCloseTo(at.c.x)
    expect(curve[0]!.y).toBeCloseTo(at.c.y)
    expect(curve[curve.length - 1]!.x).toBeCloseTo(at.e.x)
    expect(curve[curve.length - 1]!.y).toBeCloseTo(at.e.y)
  })

  it('長さで半分の位置', () => {
    expect(midpointOf([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 30 }])).toEqual({ x: 10, y: 10 })
  })
})

describe('拡大の度合いと名前', () => {
  it('縮小すると名前を薄くし、さらに縮小すると隠す', () => {
    expect(labelLevel(1)).toBe('full')
    expect(labelLevel(2)).toBe('faint')
    expect(labelLevel(4)).toBe('none')
    // 葉の間隔に余裕があれば、同じ縮小でも名前を出す
    expect(labelLevel(4, 88)).toBe('full')
  })
})

describe('見た目のルール', () => {
  it('点の半径 = 4 + √訪問回数 × 2.6', () => {
    expect(nodeRadius(1)).toBeCloseTo(6.6)
    expect(nodeRadius(4)).toBeCloseTo(9.2)
  })

  it('色は6色を順番に使う', () => {
    expect(sessionColor(0)).toBe('#7C6CF2')
    expect(sessionColor(5)).toBe('#E04F6A')
    expect(sessionColor(6)).toBe('#7C6CF2')
  })

  it('時刻は日本時間で表示する', () => {
    // 2025-10-12 12:02 UTC = 日本時間 21:02
    expect(formatTime(1760270520000)).toContain('21:02')
  })

  it('滞在時間', () => {
    expect(formatDuration(20_000)).toBe('1分未満')
    expect(formatDuration(420_000)).toBe('7分')
    expect(formatDuration(5_400_000)).toBe('1時間30分')
  })
})

describe('概念の点', () => {
  it('概念の点は、つながるページの近くの、いちばん外の輪の外に置かれる', () => {
    const mention: GraphEdge[] = [
      { source: 'a', target: 'c1', kind: 'mention' },
      { source: 'b', target: 'c1', kind: 'mention' },
    ]
    const pos = computeLayout(nodes, [...edges, ...mention], sessions, [{ id: 'c1' }])
    const c = pos.get('c1')!
    expect(dist(c, pos.get('a')!)).toBeLessThan(dist(c, pos.get('y')!))
    expect(radius(c)).toBeGreaterThan(radius(pos.get('b')!))
  })
})
