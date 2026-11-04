<script setup lang="ts">
// 「つながり」の表示（中央の領域の切り替え）。過去とのつながり（FR-11）の見やすさに特化した図。
// 調べ物を新しい順に1行ずつ並べ（履歴ログと同じ向き）、つながった調べ物どうしを右側の弧で結ぶ（アークダイアグラム）。
// 弧の太さはまとめた線の本数。選んだ調べ物の弧だけを強調し、何でつながったかを弧の横に出す。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { sessionIdOf, useTadoriStore } from '../stores/tadori'
import { arcPath, sessionLinks, strongest, type SessionLink } from '../graph/links'
import { formatDate, sessionColor } from '../graph/style'

const store = useTadoriStore()
const ROW = 28 // 1行の高さ
const TOP = 16 // 上の余白
const AXIS_X = 300 // 弧の軸（行の名前の右）
const NAME_CHARS = 24
const STRONG_PER_SESSION = 2 // ふだんは、調べ物ごとに強いつながりをこの本数だけ出す

const samePage = ref(false) // 同じページを開いただけのつながりも出すか
const showAll = ref(false) // つながりの無い調べ物も並べるか
const allLinks = ref(false) // 弱いつながりも全部出すか
const hover = ref<{ link: SessionLink; x: number; y: number } | null>(null)

const width = ref(800)
const root = ref<HTMLElement | null>(null)
let observer: ResizeObserver | null = null
onMounted(() => {
  if (!root.value) return
  observer = new ResizeObserver(([entry]) => (width.value = entry!.contentRect.width))
  observer.observe(root.value)
})
onBeforeUnmount(() => observer?.disconnect())

const selectedSession = computed(() => (store.selectedNodeId ? sessionIdOf(store.selectedNodeId) : undefined))
const everyLink = computed(() => sessionLinks(store.visibleNodes, store.visibleEdges, { samePage: samePage.value }))
// 全部の弧を描くと塊になって読めないので、ふだんは強いものだけにする（選んだ調べ物の弧はすべて出す）
const links = computed(() =>
  allLinks.value ? everyLink.value : strongest(everyLink.value, STRONG_PER_SESSION, selectedSession.value),
)
const rows = computed(() => {
  const linked = new Set(everyLink.value.flatMap((l) => [l.newer, l.older]))
  const shown = new Set(store.visibleNodes.map((n) => n.session_id))
  return store.sessions
    .filter((s) => shown.has(s.id) && (showAll.value || linked.has(s.id)))
    .sort((a, b) => b.started_at - a.started_at)
})
const rowY = computed(() => new Map(rows.value.map((s, i) => [s.id, TOP + i * ROW + ROW / 2])))
const linkCount = computed(() => {
  const count = new Map<number, number>()
  for (const l of everyLink.value) {
    count.set(l.newer, (count.get(l.newer) ?? 0) + 1)
    count.set(l.older, (count.get(l.older) ?? 0) + 1)
  }
  return count
})
const hiddenCount = computed(() => new Set(store.visibleNodes.map((n) => n.session_id)).size - rows.value.length)
const maxRx = computed(() => Math.max(40, width.value - AXIS_X - 24))
const height = computed(() => TOP * 2 + rows.value.length * ROW)

const touches = (l: SessionLink) => selectedSession.value !== undefined && (l.newer === selectedSession.value || l.older === selectedSession.value)
// 選んだ調べ物の弧は上に重ねて描く
const ordered = computed(() => [...links.value].sort((a, b) => Number(touches(a)) - Number(touches(b))))

function arc(l: SessionLink) {
  return arcPath(AXIS_X, rowY.value.get(l.newer)!, rowY.value.get(l.older)!, maxRx.value)
}
// 説明は、つながった相手の行の横に置く（相手1つにつき説明は1つなので、行の高さで並んで重ならない）
function labelY(l: SessionLink) {
  return rowY.value.get(l.newer === selectedSession.value ? l.older : l.newer)!
}
const strokeWidth = (l: SessionLink) => 1.2 + Math.log2(l.count) * 1.4
const colorOf = (sessionId: number) => sessionColor(store.sessionById.get(sessionId)?.color_index ?? 0)
const conceptText = (l: SessionLink) =>
  `${l.concepts.slice(0, 3).join('、')}${l.concepts.length > 3 ? ' ほか' : ''} つながり（${l.count}本）`

// 行を選ぶと、その調べ物の最初のページを選ぶ（ほかの領域も同じページを選んだ状態になる）
function selectSession(sessionId: number) {
  const first = store.visibleNodes
    .filter((n) => n.session_id === sessionId)
    .sort((a, b) => a.first_visit_at - b.first_visit_at)[0]
  if (first) void store.select(first.id)
}
// 弧を選ぶと、そのつながりの新しい側のページを選ぶ（詳細に、どの過去のページとつながったかが出る）
function selectLink(l: SessionLink) {
  void store.select(l.best.source)
}
function sessionName(s: { name: string | null; started_at: number }) {
  const name = s.name ?? `${formatDate(s.started_at)} の調べ物`
  return name.length > NAME_CHARS ? `${name.slice(0, NAME_CHARS - 1)}…` : name
}
function onEnter(l: SessionLink, ev: MouseEvent) {
  const rect = root.value!.getBoundingClientRect()
  hover.value = { link: l, x: ev.clientX - rect.left + 12, y: ev.clientY - rect.top + root.value!.scrollTop + 12 }
}
</script>

<template>
  <section ref="root" class="links" aria-label="つながり">
    <div class="options">
      <label><input v-model="samePage" type="checkbox" /> 同じページだけのつながりも出す</label>
      <label><input v-model="allLinks" type="checkbox" /> 弱いつながりも全部出す</label>
      <label><input v-model="showAll" type="checkbox" /> つながりの無い調べ物も並べる</label>
      <span class="muted">
        弧 {{ links.length }} / {{ everyLink.length }} 本<template v-if="!showAll && hiddenCount > 0">・つながりの無い {{ hiddenCount }} 件は省略</template>
      </span>
    </div>
    <p v-if="rows.length === 0" class="empty">この範囲には、過去とのつながりがありません。</p>
    <svg v-else :width="width" :height="height" role="img" aria-label="調べ物どうしのつながり">
      <!-- 行 -->
      <g
        v-for="(s, i) in rows"
        :key="s.id"
        class="row"
        :class="{ selected: s.id === selectedSession }"
        :transform="`translate(0,${TOP + i * ROW})`"
        tabindex="0"
        role="button"
        :aria-label="`${sessionName(s)}（${formatDate(s.started_at)}）`"
        @click="selectSession(s.id)"
        @keydown.enter.prevent="selectSession(s.id)"
      >
        <rect class="row-bg" x="0" :width="AXIS_X + 6" :height="ROW" />
        <text class="date" x="12" :y="ROW / 2" dy="0.35em">{{ formatDate(s.started_at) }}</text>
        <text class="name" x="62" :y="ROW / 2" dy="0.35em">{{ sessionName(s) }}</text>
        <text v-if="linkCount.get(s.id)" class="count" :x="AXIS_X - 12" :y="ROW / 2" dy="0.35em" text-anchor="end">
          {{ linkCount.get(s.id) }}
        </text>
        <circle :cx="AXIS_X" :cy="ROW / 2" r="5" :fill="colorOf(s.id)" />
      </g>
      <!-- 弧 -->
      <g class="arcs">
        <path
          v-for="l in ordered"
          :key="`${l.newer}>${l.older}`"
          :d="arc(l)"
          fill="none"
          :stroke="l.samePageOnly ? 'var(--muted)' : colorOf(l.newer)"
          :stroke-width="strokeWidth(l)"
          :stroke-dasharray="l.samePageOnly ? '4 3' : undefined"
          class="arc"
          :class="{ on: touches(l), off: selectedSession !== undefined && !touches(l) }"
          @click="selectLink(l)"
          @mouseenter="onEnter(l, $event)"
          @mouseleave="hover = null"
        />
      </g>
      <!-- 選んだ調べ物の弧に、何でつながったかを、相手の行の横に添える -->
      <g class="arc-labels">
        <text
          v-for="l in links.filter(touches)"
          :key="`${l.newer}>${l.older}`"
          class="arc-label"
          :x="AXIS_X + 14"
          :y="labelY(l)"
          dy="0.35em"
        >{{ conceptText(l) }}</text>
      </g>
    </svg>
    <div v-if="hover" class="tooltip" :style="{ left: `${hover.x}px`, top: `${hover.y}px` }" role="tooltip">
      <strong>{{ conceptText(hover.link) }}</strong>
      <span>
        {{ sessionName(store.sessionById.get(hover.link.newer) ?? { name: null, started_at: 0 }) }}
        → {{ sessionName(store.sessionById.get(hover.link.older) ?? { name: null, started_at: 0 }) }}
      </span>
      <span class="muted">クリックで、そのページを選ぶ</span>
    </div>
  </section>
</template>

<style scoped>
.links {
  position: absolute;
  inset: 0;
  overflow: auto;
  background: var(--bg);
  padding-top: 40px; /* 切り替えのタブと重ならないように */
}
.options {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  padding: 0 12px 4px;
  font-size: 12px;
  color: var(--fg);
}
.options label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}
.muted {
  color: var(--muted);
}
.empty {
  padding: 24px;
  color: var(--muted);
  text-align: center;
}
svg {
  display: block;
}
.row {
  cursor: pointer;
  outline: none;
}
.row-bg {
  fill: transparent;
}
.row:hover .row-bg,
.row:focus-visible .row-bg {
  fill: var(--panel);
}
.row.selected .row-bg {
  fill: var(--panel);
  stroke: var(--line);
}
.date {
  fill: var(--muted);
  font-size: 11px;
}
.name {
  fill: var(--fg);
  font-size: 13px;
}
.row.selected .name {
  font-weight: 700;
}
.count {
  fill: var(--muted);
  font-size: 11px;
}
.arc {
  opacity: 0.6;
  cursor: pointer;
}
.arc:hover,
.arc.on {
  opacity: 1;
}
.arc.off {
  opacity: 0.12;
}
.arc-label {
  fill: var(--fg);
  font-size: 12px;
  font-weight: 700;
  paint-order: stroke;
  stroke: var(--bg);
  stroke-width: 3px;
  pointer-events: none;
}
.tooltip {
  position: absolute;
  display: grid;
  gap: 2px;
  max-width: 320px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  font-size: 12px;
  pointer-events: none;
  z-index: 2;
}
</style>
