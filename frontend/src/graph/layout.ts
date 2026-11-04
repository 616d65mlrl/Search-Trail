// グラフの配置（04 アルゴリズム「画面側の計算」）: 放射状の森（radial forest）
// 中心（原点）を太陽に見立て、来た元の無い点（調べ物の出発点）を開いた時刻の順に、上から時計回りに内側の輪へ並べる。
// 来た元 → 行き先 とたどるほど、外側の輪へ置く（深さ1つにつき DEPTH_STEP）。
// 出発点はそれぞれ角度の範囲（扇）を持ち、子孫の葉（行き先の無い点）の数に応じて扇を分け合いながら外へ広がる。
// 行き先の無い単発の点は小さな扇だけを持ち、時刻の順の位置（＝同じ頃に開いた出発点の隣）に置く。
// 「概念も点にする」（FR-13）ときは、概念の点を、つながるページの角度の平均で、いちばん外の輪のさらに外へ置く。
// 乱数を使わないので、同じ入力からは必ず同じ配置になる。

import type { GraphEdge, GraphNode, GraphSession } from '../api/types'
import { parentMap } from './lanes'

export interface Point {
  x: number
  y: number
}

export const LEAF_ARC = 22 // 隣り合う葉の、輪の上での最小の間隔
export const DEPTH_STEP = 90 // 輪と輪の間隔
const MIN_INNER_RADIUS = 240 // いちばん内側の輪（出発点）の最小の半径。内向きの名前が中心で重ならない大きさ
const ROOT_GAP = 10 // 出発点の扇と扇のすき間（輪の上の長さ）
const SOLO_WEIGHT = 0.5 // 単発の点が使う扇の大きさ（葉1つを 1 とする）
const SOLO_STAGGER = 26 // 単発の点が続くとき、交互に内側へずらして重なりを防ぐ
const START_ANGLE = -Math.PI / 2 // 真上から始める

type NodeLike = Pick<GraphNode, 'id' | 'first_visit_at'> & Partial<Pick<GraphNode, 'session_id'>>

const byTime = (a: NodeLike, b: NodeLike) => a.first_visit_at - b.first_visit_at || a.id.localeCompare(b.id)

// 木の親（行き先 → 来た元）。来た元は行き先より前に開いたものだけにして、輪（循環）ができないようにする
export function treeParents(nodes: NodeLike[], edges: GraphEdge[]): Map<string, string> {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const parents = new Map<string, string>()
  for (const [child, parent] of parentMap(nodes as GraphNode[], edges)) {
    if (byTime(byId.get(parent)!, byId.get(child)!) < 0) parents.set(child, parent)
  }
  return parents
}

export interface RadialInfo {
  positions: Map<string, Point>
  roots: string[] // 出発点（時刻順）
  innerRadius: number
}

export function radialForest(nodes: NodeLike[], edges: GraphEdge[]): RadialInfo {
  const parents = treeParents(nodes, edges)
  const kids = new Map<string, string[]>()
  const ordered = [...nodes].sort(byTime)
  for (const n of ordered) {
    const p = parents.get(n.id)
    if (p !== undefined) kids.set(p, [...(kids.get(p) ?? []), n.id])
  }
  const roots = ordered.filter((n) => !parents.has(n.id)).map((n) => n.id)

  // 葉の数（扇の取り分）。深い木でも再帰の深さで止まらないよう、時刻の逆順（子が先）に数える
  const leaves = new Map<string, number>()
  for (const n of [...ordered].reverse()) {
    const k = kids.get(n.id)
    leaves.set(n.id, k ? k.reduce((s, c) => s + leaves.get(c)!, 0) : 1)
  }
  const weight = (id: string) => (kids.has(id) ? leaves.get(id)! : SOLO_WEIGHT)

  // 内側の輪は、すべての葉が LEAF_ARC 以上の間隔で並べる大きさにする（葉は内側の輪より外にあるので、そこでも間隔が保たれる）
  const totalWeight = roots.reduce((s, r) => s + weight(r), 0)
  const innerRadius = Math.max(MIN_INNER_RADIUS, (totalWeight * LEAF_ARC + roots.length * ROOT_GAP) / (2 * Math.PI))
  const gap = roots.length > 1 ? ROOT_GAP / innerRadius : 0
  const perWeight = totalWeight > 0 ? (2 * Math.PI - gap * roots.length) / totalWeight : 0

  const positions = new Map<string, Point>()
  const put = (id: string, angle: number, r: number) =>
    positions.set(id, { x: Math.cos(angle) * r, y: Math.sin(angle) * r })

  let angle = START_ANGLE
  let soloRun = 0
  for (const root of roots) {
    const span = weight(root) * perWeight
    if (!kids.has(root)) {
      // 単発の点は、続くたびに内側と外側へ交互にずらす
      put(root, angle + span / 2, innerRadius - (soloRun % 2) * SOLO_STAGGER)
      soloRun++
    } else {
      soloRun = 0
      // 扇を子へ配る。深い木でも止まらないよう、積み上げ（スタック）で順にたどる
      const stack: [string, number, number, number][] = [[root, angle, angle + span, 0]]
      while (stack.length) {
        const [id, a0, a1, depth] = stack.pop()!
        put(id, (a0 + a1) / 2, innerRadius + depth * DEPTH_STEP)
        const k = kids.get(id) ?? []
        const total = k.reduce((s, c) => s + leaves.get(c)!, 0)
        let s = a0
        for (const c of k) {
          const sp = ((a1 - a0) * leaves.get(c)!) / total
          stack.push([c, s, s + sp, depth + 1])
          s += sp
        }
      }
    }
    angle += span + gap
  }
  return { positions, roots, innerRadius }
}

// 概念の点を、つながるページの角度の平均（円の上の平均）に置き、近すぎるものは角度をずらす
function placeConcepts(
  positions: Map<string, Point>,
  edges: GraphEdge[],
  concepts: { id: string }[],
): Map<string, Point> {
  const result = new Map<string, Point>()
  if (concepts.length === 0) return result
  let maxR = 0
  for (const p of positions.values()) maxR = Math.max(maxR, Math.hypot(p.x, p.y))
  const radius = maxR + DEPTH_STEP
  const sums = new Map<string, Point>()
  for (const e of edges) {
    if (e.kind !== 'mention') continue
    const p = positions.get(e.source)
    const s = sums.get(e.target)
    if (!p) continue
    const len = Math.hypot(p.x, p.y) || 1
    sums.set(e.target, { x: (s?.x ?? 0) + p.x / len, y: (s?.y ?? 0) + p.y / len })
  }
  const sorted = [...concepts].sort((a, b) => a.id.localeCompare(b.id))
  const angles = sorted
    .map((c, i) => {
      const s = sums.get(c.id)
      const a = s && (s.x || s.y) ? Math.atan2(s.y, s.x) : START_ANGLE + (i / sorted.length) * 2 * Math.PI
      return { id: c.id, a }
    })
    .sort((p, q) => p.a - q.a || p.id.localeCompare(q.id))
  const minGap = Math.min(LEAF_ARC / radius, (2 * Math.PI) / angles.length)
  for (let i = 1; i < angles.length; i++) {
    angles[i]!.a = Math.max(angles[i]!.a, angles[i - 1]!.a + minGap)
  }
  for (const { id, a } of angles) result.set(id, { x: Math.cos(a) * radius, y: Math.sin(a) * radius })
  return result
}

export function computeLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  // 時刻の順は点の first_visit_at で決まるので、調べ物の一覧は使わない（呼び出し側との形を保つために受け取る）
  _sessions: Pick<GraphSession, 'id' | 'started_at'>[] = [],
  concepts: { id: string }[] = [],
): Map<string, Point> {
  const { positions } = radialForest(nodes, edges)
  for (const [id, p] of placeConcepts(positions, edges, concepts)) positions.set(id, p)
  return positions
}

// 来た元 → 行き先 の枝。来た元の角度のまま外へ進み、行き先の角度へ曲がる（d3.linkRadial と同じ考え方）
export function radialLinkPath(s: Point, t: Point): string {
  const rs = Math.hypot(s.x, s.y)
  const rt = Math.hypot(t.x, t.y)
  const rm = (rs + rt) / 2
  const as = Math.atan2(s.y, s.x)
  const at = Math.atan2(t.y, t.x)
  const c1 = { x: Math.cos(as) * rm, y: Math.sin(as) * rm }
  const c2 = { x: Math.cos(at) * rm, y: Math.sin(at) * rm }
  return `M${s.x},${s.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${t.x},${t.y}`
}

// 過去とのつながりの線は、階層に沿って束ねる（hierarchical edge bundling。Holten 2006）。
// 放射状の木では、つながる2点の「共通の祖先」を経由する道筋を作り、それをなめらかな曲線にするのが定番。
// 道筋: 点 → 来た元 → … → 出発点 →（輪の内側）→ 相手の出発点 → … → 相手の点。
// 別々の木（別の調べ物）どうしは共通の祖先が無いので、輪の内側を通って相手の木へ渡る。
// こうすると、線は自分の幹から出て輪の内側を回るので、輪の上の点や名前を横切らない。
const BUNDLE_BETA = 0.85 // 1 に近いほど道筋にぴったり沿い、0 に近いほど直線になる
const BUNDLE_INNER = 0.55 // 別の木へ渡るとき、出発点の半径の何倍の位置まで内側へ入るか
const BUNDLE_SAMPLES = 8 // 曲線の1区間を何個の点で近似するか

// 点から出発点までの道（自分 → 来た元 → … → 出発点）
function ancestry(id: string, parents: Map<string, string>): string[] {
  const chain = [id]
  const seen = new Set(chain)
  for (let p = parents.get(id); p !== undefined && !seen.has(p); p = parents.get(p)) {
    chain.push(p)
    seen.add(p)
  }
  return chain
}

// 線の道筋（制御点）。共通の祖先があればそこで折り返し、無ければ輪の内側を通る
export function bundleRoute(
  source: string,
  target: string,
  parents: Map<string, string>,
  pos: (id: string) => Point,
): Point[] {
  const up = ancestry(source, parents)
  const down = ancestry(target, parents)
  const inDown = new Set(down)
  const lca = up.findIndex((id) => inDown.has(id))
  if (lca >= 0) {
    const ids = [...up.slice(0, lca + 1), ...down.slice(0, down.indexOf(up[lca]!)).reverse()]
    return ids.map(pos)
  }
  const inward = (id: string) => {
    const p = pos(id)
    return { x: p.x * BUNDLE_INNER, y: p.y * BUNDLE_INNER }
  }
  return [...up.map(pos), inward(up[up.length - 1]!), inward(down[down.length - 1]!), ...[...down].reverse().map(pos)]
}

// 道筋をなめらかな曲線の点の列にする（3次の一様 B スプライン。両端の点はちょうど通る）。
// まず道筋を両端を結ぶ直線へ少し寄せ（beta）、束ねたときに線どうしがわずかに離れて見分けられるようにする
export function bundleCurve(route: Point[], beta: number = BUNDLE_BETA): Point[] {
  const n = route.length
  if (n <= 2) return route
  const a = route[0]!
  const b = route[n - 1]!
  const pts = route.map((p, i) => {
    const t = i / (n - 1)
    return { x: beta * p.x + (1 - beta) * (a.x + t * (b.x - a.x)), y: beta * p.y + (1 - beta) * (a.y + t * (b.y - a.y)) }
  })
  const ctrl = [a, a, ...pts, b, b]
  const out: Point[] = []
  for (let i = 0; i + 3 < ctrl.length; i++) {
    const [p0, p1, p2, p3] = [ctrl[i]!, ctrl[i + 1]!, ctrl[i + 2]!, ctrl[i + 3]!]
    for (let k = i === 0 ? 0 : 1; k <= BUNDLE_SAMPLES; k++) {
      const t = k / BUNDLE_SAMPLES
      const w0 = (1 - t) ** 3 / 6
      const w1 = (3 * t ** 3 - 6 * t ** 2 + 4) / 6
      const w2 = (-3 * t ** 3 + 3 * t ** 2 + 3 * t + 1) / 6
      const w3 = t ** 3 / 6
      out.push({
        x: w0 * p0.x + w1 * p1.x + w2 * p2.x + w3 * p3.x,
        y: w0 * p0.y + w1 * p1.y + w2 * p2.y + w3 * p3.y,
      })
    }
  }
  return out
}

export function polylinePath(points: Point[]): string {
  return points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
}

// 点の列の、長さでちょうど半分の位置（線に添える説明の位置）
export function midpointOf(points: Point[]): Point {
  if (points.length === 0) return { x: 0, y: 0 }
  const seg = points.slice(1).map((p, i) => Math.hypot(p.x - points[i]!.x, p.y - points[i]!.y))
  let rest = seg.reduce((s, d) => s + d, 0) / 2
  for (let i = 0; i < seg.length; i++) {
    if (rest <= seg[i]!) {
      const t = seg[i] ? rest / seg[i]! : 0
      return { x: points[i]!.x + t * (points[i + 1]!.x - points[i]!.x), y: points[i]!.y + t * (points[i + 1]!.y - points[i]!.y) }
    }
    rest -= seg[i]!
  }
  return points[points.length - 1]!
}

// 拡大の度合いに応じた名前の出し方。px は画面の1px がグラフの座標でいくつにあたるか、
// leafArc はグラフの座標での葉の間隔（点が少なく、間隔に余裕があるときは LEAF_ARC より広い）。
// 葉の間隔が画面で十分に広ければ普通に、少し狭ければ薄く、もっと狭ければ出さない
export type LabelLevel = 'full' | 'faint' | 'none'
export function labelLevel(px: number, leafArc: number = LEAF_ARC): LabelLevel {
  const spacing = leafArc / px // 隣り合う葉の、画面上の間隔
  if (spacing >= 14) return 'full'
  if (spacing >= 8) return 'faint'
  return 'none'
}

// すべての点が収まる範囲（「全体」ボタン用）
export function bounds(points: Iterable<Point>, margin = 60): { x: number; y: number; w: number; h: number } {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const p of points) {
    minX = Math.min(minX, p.x)
    minY = Math.min(minY, p.y)
    maxX = Math.max(maxX, p.x)
    maxY = Math.max(maxY, p.y)
  }
  if (minX === Infinity) return { x: -300, y: -200, w: 600, h: 400 }
  return { x: minX - margin, y: minY - margin, w: maxX - minX + margin * 2, h: maxY - minY + margin * 2 }
}
