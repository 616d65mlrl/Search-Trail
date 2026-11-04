<script setup lang="ts">
// 履歴ログ（05 画面仕様、元の案は「10 Git グラフ」）
// 新しい順のページ一覧。調べ物ごとの区切り、レーンの線、「分岐N」「過去N」の印を出す。
import { computed, nextTick, ref, watch } from 'vue'
import { useTadoriStore } from '../stores/tadori'
import { assignLanes, MAX_LANES, parentMap } from '../graph/lanes'
import { formatDate, formatTime, sessionColor, shortTitle } from '../graph/style'
import type { GraphNode } from '../api/types'

const ROW = 36
const LANE = 14
const LANE_WIDTH = LANE * MAX_LANES + 8

const store = useTadoriStore()
const list = ref<HTMLElement | null>(null)

interface Group {
  sessionId: number
  label: string
  color: string
  rows: GraphNode[]
  lines: { d: string }[]
  dots: { x: number; y: number; branch: boolean }[]
}

const groups = computed<Group[]>(() => {
  const lanes = assignLanes(store.visibleNodes, store.visibleEdges)
  const parents = parentMap(store.visibleNodes, store.visibleEdges)
  const bySession = new Map<number, GraphNode[]>()
  for (const n of store.visibleNodes) bySession.set(n.session_id, [...(bySession.get(n.session_id) ?? []), n])

  // 調べ物も、中のページも新しい順
  return [...bySession.entries()]
    .map(([sessionId, nodes]) => {
      const rows = [...nodes].sort((a, b) => b.first_visit_at - a.first_visit_at)
      const rowOf = new Map(rows.map((n, i) => [n.id, i]))
      const pos = (id: string) => ({ x: 8 + (lanes.get(id) ?? 0) * LANE, y: rowOf.get(id)! * ROW + ROW / 2 })
      const lines = rows.flatMap((n) => {
        const parent = parents.get(n.id)
        if (!parent || !rowOf.has(parent)) return []
        const c = pos(n.id)
        const p = pos(parent)
        // 子のレーンをまっすぐ下り、最後に来た元へ斜めにつなぐ
        return [{ d: `M${c.x},${c.y} L${c.x},${p.y - ROW / 2} L${p.x},${p.y}` }]
      })
      const session = store.sessionById.get(sessionId)
      return {
        sessionId,
        label: session?.name ?? `${formatDate(session?.started_at ?? rows.at(-1)!.first_visit_at)} の調べ物`,
        color: sessionColor(session?.color_index ?? 0),
        rows,
        lines,
        dots: rows.map((n) => ({ ...pos(n.id), branch: n.branch_count > 0 })),
      }
    })
    .sort((a, b) => b.rows[0]!.first_visit_at - a.rows[0]!.first_visit_at)
})

// 選んだ行が見える位置まで自動でスクロールする
watch(
  () => store.selectedNodeId,
  async (id) => {
    if (!id) return
    await nextTick()
    list.value?.querySelector(`[data-node="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' })
  },
)

function dimmed(id: string) {
  return store.matches !== null && !store.matches.has(id)
}
</script>

<template>
  <section ref="list" class="log" aria-label="履歴ログ">
    <div v-for="g in groups" :key="g.sessionId" class="group">
      <h2 class="group-title" :style="{ borderColor: g.color }">{{ g.label }}</h2>
      <div class="rows" :style="{ height: `${g.rows.length * ROW}px` }">
        <svg class="lanes" :width="LANE_WIDTH" :height="g.rows.length * ROW" aria-hidden="true">
          <path v-for="(l, i) in g.lines" :key="i" :d="l.d" :stroke="g.color" fill="none" stroke-width="2" />
          <circle v-for="(d, i) in g.dots" :key="i" :cx="d.x" :cy="d.y" :r="d.branch ? 5 : 4" :fill="g.color" />
        </svg>
        <div
          v-for="n in g.rows"
          :key="n.id"
          :data-node="n.id"
          class="row"
          :class="{ selected: n.id === store.selectedNodeId, dim: dimmed(n.id) }"
          :style="{ height: `${ROW}px`, paddingLeft: `${LANE_WIDTH + 4}px` }"
          tabindex="0"
          role="button"
          :aria-pressed="n.id === store.selectedNodeId"
          @click="store.select(n.id)"
          @keydown.enter.prevent="store.select(n.id)"
        >
          <span class="title">{{ shortTitle(n.title, n.url, 28) }}</span>
          <span v-if="n.branch_count" class="mark">分岐{{ n.branch_count }}</span>
          <span v-if="n.past_count" class="mark past">過去{{ n.past_count }}</span>
          <span class="time">{{ formatTime(n.first_visit_at) }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.log {
  overflow-y: auto;
  border-right: 1px solid var(--line);
  background: var(--panel);
}
.group-title {
  position: sticky;
  top: 0;
  z-index: 1;
  margin: 0;
  padding: 8px 12px;
  border-left: 4px solid;
  background: var(--panel);
  font-size: 13px;
}
.rows {
  position: relative;
}
.lanes {
  position: absolute;
  left: 4px;
  top: 0;
  pointer-events: none;
}
.row {
  display: flex;
  align-items: center;
  gap: 6px;
  box-sizing: border-box;
  padding-right: 10px;
  font-size: 13px;
  cursor: pointer;
}
.row:hover,
.row:focus-visible {
  background: var(--hover);
  outline: none;
}
.row.selected {
  background: var(--selected);
}
.row.dim {
  opacity: 0.35;
}
.title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 幅を狭めても札と時刻は折り返さず、名前のほうを短くする */
.mark,
.time {
  flex: none;
  white-space: nowrap;
}
.mark {
  padding: 1px 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 11px;
  color: var(--muted);
}
.time {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
</style>
