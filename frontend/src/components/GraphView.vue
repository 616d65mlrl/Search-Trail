<script setup lang="ts">
// 中央のグラフ（05 画面仕様、元の案は「01 ナレッジグラフ」）
// 点はすべて丸。色は調べ物、大きさは訪問回数。遷移は実線、過去とのつながりは点線。
// 配置は放射状の森（graph/layout.ts）: 中心のまわりに出発点を時刻順に並べ、たどった先ほど外側に置く。
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue'
import { useTadoriStore } from '../stores/tadori'
import {
  bounds,
  bundleCurve,
  bundleRoute,
  LEAF_ARC,
  midpointOf,
  polylinePath,
  labelLevel,
  radialLinkPath,
  treeParents,
  type LabelLevel,
  type Point,
} from '../graph/layout'
import { layoutAsync, WORKER_THRESHOLD } from '../graph/layoutAsync'
import { formatDate, formatTime, nodeRadius, sessionColor, shortTitle } from '../graph/style'
import type { GraphEdge, GraphNode } from '../api/types'
// WebGL の部品（sigma.js を含み大きい）は、点が2,000を超えて必要になったときだけ読み込む
const GraphWebGL = defineAsyncComponent(() => import('./GraphWebGL.vue'))

const store = useTadoriStore()
const svg = ref<SVGSVGElement | null>(null)

// 配置。点が多いときは Web Worker で計算するので、結果は後から届く
const layout = ref<Map<string, Point>>(new Map())
const computing = ref(false)
let layoutSeq = 0 // 計算中に表示範囲が変わったら、古い結果を捨てるための番号
const CONCEPT_COLOR = '#9A9CA3'
const CONCEPT_RADIUS = 5

const view = ref({ x: -300, y: -200, w: 600, h: 400 })
// 点が多いとき（2,000超）は WebGL で描く（FR-15）
const webgl = ref<{ fit: () => void } | null>(null)
function fit() {
  view.value = bounds(layout.value.values())
  webgl.value?.fit()
}
// 表示する点が変わったら配置を計算し直し、全体が収まる大きさに戻す
watch(
  () => [store.visibleNodes, store.visibleEdges, store.conceptEdges, store.sessions, store.conceptNodes] as const,
  async ([nodes, edges, mentions, sessions, concepts]) => {
    const seq = ++layoutSeq
    computing.value = nodes.length + concepts.length > WORKER_THRESHOLD
    const result = await layoutAsync(nodes, [...edges, ...mentions], sessions, concepts)
    if (seq !== layoutSeq) return
    layout.value = result
    computing.value = false
    fit()
  },
  { immediate: true },
)

const colorOf = (n: GraphNode) => sessionColor(store.sessionById.get(n.session_id)?.color_index ?? 0)
const pos = (id: string): Point => layout.value.get(id) ?? { x: 0, y: 0 }

// 選んだ点が分岐点なら A、行き先に B、C、D の文字を出す
const letters = computed(() => {
  const map = new Map<string, string>()
  const d = store.detail
  if (!d || d.node.id !== store.selectedNodeId || d.children.length < 2) return map
  map.set(d.node.id, 'A')
  for (const c of d.children) map.set(c.id, c.letter)
  return map
})

const dimmed = (id: string) => store.matches !== null && !store.matches.has(id)

// 過去とのつながりは、点の数に関係なく、選んだ点の分だけを描く（全部描くと線が重なって、たどった枝が読めないため）。
// 全体のつながりは「つながり」の表示（LinksView）で見る
const drawnEdges = computed(() =>
  store.visibleEdges.filter(
    (e) => e.kind === 'nav' || e.source === store.selectedNodeId || e.target === store.selectedNodeId,
  ),
)
// 描く過去とのつながりの線の形（木の幹をさかのぼり、輪の内側を回って相手の木へ渡る曲線）
const pastCurves = computed(() => {
  const curves = new Map<string, Point[]>()
  for (const e of drawnEdges.value) {
    if (e.kind === 'past') curves.set(`${e.source}>${e.target}`, bundleCurve(bundleRoute(e.source, e.target, parents.value, pos)))
  }
  return curves
})
const important = computed(() => {
  const ids = new Set<string>()
  const selected = store.selectedNodeId
  if (selected) {
    ids.add(selected)
    for (const e of store.visibleEdges) {
      if (e.source === selected) ids.add(e.target)
      if (e.target === selected) ids.add(e.source)
    }
  }
  for (const id of letters.value.keys()) ids.add(id)
  for (const id of store.matches ?? []) ids.add(id)
  return ids
})
// 名前は、縮小すると薄くし、さらに縮小すると隠す。選んだ点のまわりと検索に一致した点はいつも出す
// 葉の間隔は、内側の輪の長さを葉の数で割ったもの（葉は内側の輪より外にあるので、実際はこれ以上に広い）
const leafArc = computed(() => {
  const leaves = store.visibleNodes.filter((n) => !hasChildren.value.has(n.id)).length
  const inner = dateMarks.value?.inner ?? 0
  return Math.max(LEAF_ARC, (2 * Math.PI * inner) / Math.max(leaves, 1))
})
const zoomLevel = computed(() => labelLevel(px.value, leafArc.value))
function levelOf(n: GraphNode): LabelLevel {
  return important.value.has(n.id) ? 'full' : zoomLevel.value
}

// 木の枝（来た元 → 行き先）は外へ伸びる曲線、それ以外の遷移は直線、過去とのつながりは中心側へふくらむ曲線
const parents = computed(() => treeParents(store.visibleNodes, store.visibleEdges))
const hasChildren = computed(() => new Set(parents.value.values()))
function edgePath(e: GraphEdge): string {
  const s = pos(e.source)
  const t = pos(e.target)
  const curve = e.kind === 'past' ? pastCurves.value.get(`${e.source}>${e.target}`) : undefined
  if (curve) return polylinePath(curve)
  if (parents.value.get(e.target) === e.source) return radialLinkPath(s, t)
  return `M${s.x},${s.y} L${t.x},${t.y}`
}

// 中心のまわりの日付。出発点の日付が変わるところにだけ、内側に小さく出す（画面で近すぎるものは省く）
const dateMarks = computed(() => {
  const roots = store.visibleNodes.filter((n) => !parents.value.has(n.id)).sort((a, b) => a.first_visit_at - b.first_visit_at)
  if (!roots.length) return null
  const inner = Math.min(...roots.map((n) => Math.hypot(pos(n.id).x, pos(n.id).y)))
  // 点の下に出る名前（横幅の半分でおよそ 60px）にかからないよう、輪より少し内側に置く
  const r = Math.max(inner * 0.5, inner - 90 * px.value)
  const marks: { key: string; x: number; y: number; text: string }[] = []
  let lastDate = ''
  let last: Point | null = null
  for (const n of roots) {
    const text = formatDate(n.first_visit_at)
    if (text === lastDate) continue
    lastDate = text
    const p = pos(n.id)
    const a = Math.atan2(p.y, p.x)
    const m = { key: n.id, x: Math.cos(a) * r, y: Math.sin(a) * r, text }
    if (last && Math.hypot(m.x - last.x, m.y - last.y) / px.value < 40) continue
    marks.push(m)
    last = m
  }
  return { marks, r, inner, sun: Math.min(8 * px.value, inner / 4) }
})

// 関係の説明（「Python つながり（9/3）」）は、選んだ点の過去とのつながりの線にだけ出す
const pastLabels = computed(() => {
  const selected = store.selectedNodeId
  if (!selected) return []
  return store.visibleEdges
    .filter((e) => e.kind === 'past' && (e.source === selected || e.target === selected))
    .map((e) => {
      const other = store.nodeById.get(e.source === selected ? e.target : e.source)!
      const started = store.sessionById.get(other.session_id)?.started_at ?? other.first_visit_at
      const mid = midpointOf(pastCurves.value.get(`${e.source}>${e.target}`) ?? [pos(e.source), pos(e.target)])
      return {
        key: `${e.source}>${e.target}`,
        x: mid.x,
        y: mid.y,
        text: `${e.concept ?? '同じページ'} つながり（${formatDate(started)}）`,
      }
    })
})

// --- 拡大縮小と移動 ---
// 画面の1px が、グラフの座標でいくつにあたるか。
// preserveAspectRatio の既定（中央寄せで全体が収まる）に合わせて換算する
function pixelScale(rect: { width: number; height: number }): number {
  return Math.max(view.value.w / rect.width, view.value.h / rect.height)
}

// 表示領域の大きさを追いかけ、文字や線の太さを拡大縮小に関係なく画面上で一定にする
const size = ref({ width: 1, height: 1 })
const observer =
  typeof ResizeObserver === 'undefined'
    ? undefined
    : new ResizeObserver(([entry]) => {
        if (entry) size.value = { width: entry.contentRect.width || 1, height: entry.contentRect.height || 1 }
      })
watch(svg, (el, old) => {
  if (old) observer?.unobserve(old)
  if (el) observer?.observe(el)
})
onBeforeUnmount(() => observer?.disconnect())
const px = computed(() => pixelScale(size.value))

function toGraph(ev: { clientX: number; clientY: number }): Point {
  const rect = svg.value!.getBoundingClientRect()
  const v = view.value
  const scale = pixelScale(rect)
  const offX = (rect.width * scale - v.w) / 2
  const offY = (rect.height * scale - v.h) / 2
  return { x: v.x - offX + (ev.clientX - rect.left) * scale, y: v.y - offY + (ev.clientY - rect.top) * scale }
}

function onWheel(ev: WheelEvent) {
  const p = toGraph(ev)
  const k = Math.exp(ev.deltaY * 0.0015)
  const v = view.value
  view.value = { x: p.x - (p.x - v.x) * k, y: p.y - (p.y - v.y) * k, w: v.w * k, h: v.h * k }
}

let drag: { clientX: number; clientY: number; view: typeof view.value; scale: number } | null = null
function onPointerDown(ev: PointerEvent) {
  if ((ev.target as Element).closest('.node')) return
  const rect = svg.value!.getBoundingClientRect()
  drag = { clientX: ev.clientX, clientY: ev.clientY, view: { ...view.value }, scale: pixelScale(rect) }
  svg.value!.setPointerCapture(ev.pointerId)
}
function onPointerMove(ev: PointerEvent) {
  if (!drag) return
  view.value = {
    ...drag.view,
    x: drag.view.x - (ev.clientX - drag.clientX) * drag.scale,
    y: drag.view.y - (ev.clientY - drag.clientY) * drag.scale,
  }
}
function onPointerUp() {
  drag = null
}

// --- 吹き出し ---
const hover = ref<{ node: GraphNode; x: number; y: number } | null>(null)
function onEnter(n: GraphNode, ev: MouseEvent) {
  const rect = svg.value!.getBoundingClientRect()
  hover.value = { node: n, x: ev.clientX - rect.left + 12, y: ev.clientY - rect.top + 12 }
}

function open(n: GraphNode) {
  window.open(n.url, '_blank', 'noopener')
}
</script>

<template>
  <section class="graph" aria-label="グラフ">
    <template v-if="store.tooManyNodes">
      <GraphWebGL v-if="layout.size" ref="webgl" :layout="layout" />
      <button class="fit" @click="fit">全体</button>
      <p v-if="computing" class="computing" role="status">配置を計算しています…</p>
    </template>
    <template v-else>
      <svg
        ref="svg"
        :viewBox="`${view.x} ${view.y} ${view.w} ${view.h}`"
        @wheel.prevent="onWheel"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <g class="mentions">
          <line
            v-for="e in store.conceptEdges"
            :key="`${e.source}>${e.target}`"
            :x1="pos(e.source).x"
            :y1="pos(e.source).y"
            :x2="pos(e.target).x"
            :y2="pos(e.target).y"
            :stroke="CONCEPT_COLOR"
            :stroke-width="px"
            :class="{ dim: dimmed(e.source) }"
          />
        </g>
        <!-- 中心（太陽）と、出発点の輪の内側の日付 -->
        <g v-if="dateMarks" class="center-marks">
          <circle :r="dateMarks.sun" class="sun" />
          <text
            v-for="m in dateMarks.marks"
            :key="m.key"
            class="date"
            :x="m.x"
            :y="m.y"
            :font-size="10 * px"
            text-anchor="middle"
            dy="0.35em"
          >{{ m.text }}</text>
        </g>
        <g class="edges">
          <path
            v-for="e in drawnEdges"
            :key="`${e.kind}:${e.source}>${e.target}`"
            :d="edgePath(e)"
            fill="none"
            :stroke="colorOf(store.nodeById.get(e.target)!)"
            :stroke-dasharray="e.kind === 'nav' ? undefined : `${6 * px} ${4 * px}`"
            :class="{ dim: dimmed(e.source) && dimmed(e.target) }"
            :stroke-width="1.6 * px"
          />
        </g>
        <g
          v-for="n in store.visibleNodes"
          :key="n.id"
          class="node"
          :class="{ dim: dimmed(n.id), selected: n.id === store.selectedNodeId }"
          :transform="`translate(${pos(n.id).x},${pos(n.id).y})`"
          tabindex="0"
          role="button"
          :aria-label="n.title ?? n.url"
          :aria-pressed="n.id === store.selectedNodeId"
          @click="store.select(n.id)"
          @dblclick="open(n)"
          @keydown.enter.prevent="store.select(n.id)"
          @mouseenter="onEnter(n, $event)"
          @mouseleave="hover = null"
        >
          <!-- 分岐点は、外側に細い点線の輪 -->
          <circle
            v-if="n.branch_count"
            :r="nodeRadius(n.visits) + 5 * px"
            fill="none"
            :stroke="colorOf(n)"
            :stroke-width="px"
            :stroke-dasharray="`${2 * px} ${3 * px}`"
          />
          <!-- 選んだ点は太い輪 -->
          <circle
            v-if="n.id === store.selectedNodeId"
            :r="nodeRadius(n.visits) + 3 * px"
            fill="none"
            stroke="var(--fg)"
            :stroke-width="3 * px"
          />
          <circle :r="nodeRadius(n.visits)" :fill="colorOf(n)" />
          <text v-if="letters.has(n.id)" class="letter" :font-size="11 * px" text-anchor="middle" dy="0.35em">
            {{ letters.get(n.id) }}
          </text>
          <text
            v-if="levelOf(n) !== 'none'"
            class="label"
            :class="{ faint: levelOf(n) === 'faint' }"
            :y="nodeRadius(n.visits) + 14 * px"
            :font-size="11 * px"
            :stroke-width="3 * px"
            text-anchor="middle"
          >
            {{ shortTitle(n.title, n.url) }}
          </text>
        </g>
        <!-- 概念の点（「概念も点にする」のときだけ） -->
        <g
          v-for="c in store.conceptNodes"
          :key="c.id"
          class="concept"
          :transform="`translate(${pos(c.id).x},${pos(c.id).y})`"
        >
          <circle :r="CONCEPT_RADIUS" :fill="CONCEPT_COLOR" />
          <text v-if="zoomLevel !== 'none'" class="label muted" :y="CONCEPT_RADIUS + 14 * px" :font-size="11 * px" :stroke-width="3 * px"
                text-anchor="middle">{{ c.label }}</text>
        </g>
        <g class="past-labels">
          <text
            v-for="l in pastLabels"
            :key="l.key"
            class="label past-label"
            :x="l.x"
            :y="l.y"
            :font-size="11 * px"
            :stroke-width="3 * px"
            text-anchor="middle"
          >{{ l.text }}</text>
        </g>
      </svg>
      <button class="fit" @click="fit">全体</button>
      <p v-if="computing" class="computing" role="status">配置を計算しています…</p>
      <div v-if="hover" class="tooltip" :style="{ left: `${hover.x}px`, top: `${hover.y}px` }" role="tooltip">
        <strong>{{ hover.node.title ?? hover.node.url }}</strong>
        <span>{{ hover.node.domain }}</span>
        <span>{{ formatTime(hover.node.first_visit_at) }} ・ {{ hover.node.visits }} 回</span>
      </div>
    </template>
  </section>
</template>

<style scoped>
.graph {
  position: relative;
  overflow: hidden;
  background: var(--bg);
}
svg {
  width: 100%;
  height: 100%;
  display: block;
  cursor: grab;
  touch-action: none;
}
.node {
  cursor: pointer;
  outline: none;
}
.node:focus-visible circle:last-of-type {
  stroke: var(--fg);
  stroke-width: 2;
}
.dim {
  opacity: 0.15;
}
/* 文字の大きさと縁取りの太さは、画面上で一定になるよう属性で指定している */
.label {
  fill: var(--fg);
  paint-order: stroke;
  stroke: var(--bg);
  pointer-events: none;
}
.label.muted {
  fill: var(--muted);
}
/* 縮小したときの名前は、灰色で薄くする */
.label.faint {
  fill: var(--muted);
  opacity: 0.6;
}
.sun {
  fill: var(--muted);
  opacity: 0.35;
}
.date {
  fill: var(--muted);
  pointer-events: none;
}
.past-label {
  font-weight: 700;
}
.letter {
  font-weight: 700;
  fill: #fff;
  pointer-events: none;
}
.fit {
  position: absolute;
  right: 12px;
  top: 12px;
  padding: 4px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  color: var(--fg);
  cursor: pointer;
}
.computing {
  position: absolute;
  left: 12px;
  top: 12px;
  margin: 0;
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--panel);
  color: var(--muted);
  font-size: 12px;
}
.tooltip {
  position: absolute;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 280px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  font-size: 12px;
  pointer-events: none;
}
.tooltip span {
  color: var(--muted);
}
.message {
  margin: auto;
  padding: 40px;
  text-align: center;
  color: var(--muted);
}
</style>
