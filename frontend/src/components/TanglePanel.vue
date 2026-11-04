<script setup lang="ts">
// 今回と過去（05 画面仕様、元の案は「08 タングルグラム」）
// 左は選んだ調べ物の木（深さ優先・時刻順）、右はつながる過去の調べ物、その間に橋（過去とのつながり）を描く。
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useTadoriStore } from '../stores/tadori'
import { formatDate, sessionColor, shortTitle } from '../graph/style'

const LONG_SESSION = 15 // これを超えたら、つながりのある点とその前後だけを表示する

const store = useTadoriStore()
const panel = ref<HTMLElement | null>(null)

const session = computed(() => (store.tangle ? store.sessionById.get(store.tangle.session.id) : undefined))
const color = computed(() => sessionColor(session.value?.color_index ?? 0))

const tree = computed(() => {
  const t = store.tangle
  if (!t) return []
  const items = t.tree.map((item) => ({ ...item, node: store.nodeById.get(item.id) }))
  const linked = new Set(t.bridges.map((b) => b.from))
  if (items.length <= LONG_SESSION || linked.size === 0) return items
  return items.filter((_, i) => [i - 1, i, i + 1].some((j) => items[j] && linked.has(items[j]!.id)))
})

function sessionTitle(s: { name: string | null; started_at?: number } | undefined, fallbackAt?: number) {
  if (!s) return ''
  const at = s.started_at ?? fallbackAt
  return s.name ?? (at !== undefined ? `${formatDate(at)} の調べ物` : '')
}

// --- 名前を手で直す（FR-12） ---
const editing = ref(false)
const draft = ref('')
const input = ref<HTMLInputElement | null>(null)
async function startEdit() {
  draft.value = store.tangle?.session.name ?? ''
  editing.value = true
  await nextTick()
  input.value?.select()
}
async function saveEdit() {
  if (!editing.value || !store.tangle) return
  editing.value = false
  await store.renameSession(store.tangle.session.id, draft.value)
}

// --- 橋: 左の行と右の行の位置を測って線を引く ---
interface Bridge {
  key: string
  x1: number
  y1: number
  x2: number
  y2: number
  label: string
}
const bridges = ref<Bridge[]>([])

function measure() {
  const root = panel.value
  const t = store.tangle
  if (!root || !t) {
    bridges.value = []
    return
  }
  const base = root.getBoundingClientRect()
  const area = (side: string) => root.querySelector<HTMLElement>(`.side.${side}`)?.getBoundingClientRect()
  const currentArea = area('current')
  const otherArea = area('other')
  // スクロールしないと見えない行への橋は描かない
  const visible = (r: DOMRect, a: DOMRect | undefined) =>
    a !== undefined && r.top + r.height / 2 >= a.top && r.top + r.height / 2 <= a.bottom
  const find = (side: string, id: string) =>
    root.querySelector<HTMLElement>(`[data-side="${side}"][data-node="${CSS.escape(id)}"]`)?.getBoundingClientRect()
  bridges.value = t.bridges.flatMap((b, i) => {
    const from = find('current', b.from)
    const to = find('other', b.to)
    if (!from || !to || !visible(from, currentArea) || !visible(to, otherArea)) return []
    return [{
      key: `${i}:${b.from}>${b.to}`,
      x1: from.right - base.left,
      y1: from.top + from.height / 2 - base.top,
      x2: to.left - base.left,
      y2: to.top + to.height / 2 - base.top,
      label: b.label,
    }]
  })
}

watch(() => [store.tangle, store.nodeById], () => nextTick(measure), { deep: false })
const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(() => measure())
watch(panel, (el, old) => {
  if (old) observer?.unobserve(old)
  if (el) observer?.observe(el)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <section ref="panel" class="tangle" aria-label="今回と過去">
    <p v-if="!store.tangle" class="hint whole">ページを選ぶと、その調べ物の流れがここに出ます。</p>
    <template v-else>
      <div class="side current" @scroll="measure">
        <h2 :style="{ borderColor: color }">
          <span class="caption">今回</span>
          <form v-if="editing" class="rename" @submit.prevent="saveEdit">
            <input
              ref="input"
              v-model="draft"
              aria-label="調べ物の名前"
              placeholder="空欄で自動の名前に戻す"
              @blur="saveEdit"
              @keydown.esc.prevent="editing = false"
            />
          </form>
          <template v-else>
            <span class="name">{{ sessionTitle(store.tangle.session, session?.started_at) }}</span>
            <button class="edit" title="名前を変える" aria-label="調べ物の名前を変える" @click="startEdit">✎</button>
          </template>
        </h2>
        <ol class="tree">
          <li
            v-for="item in tree"
            :key="item.id"
            :data-node="item.id"
            data-side="current"
            :style="{ paddingLeft: `${item.depth * 14 + 8}px` }"
            :class="{ selected: item.id === store.selectedNodeId }"
            tabindex="0"
            role="button"
            @click="store.select(item.id)"
            @keydown.enter.prevent="store.select(item.id)"
          >
            <span class="dot" :style="{ background: color }" />
            <span class="text">{{ item.node ? shortTitle(item.node.title, item.node.url, 32) : item.id }}</span>
          </li>
        </ol>
      </div>

      <svg class="bridges" aria-hidden="true">
        <g v-for="b in bridges" :key="b.key">
          <path
            :d="`M${b.x1},${b.y1} C${(b.x1 + b.x2) / 2},${b.y1} ${(b.x1 + b.x2) / 2},${b.y2} ${b.x2},${b.y2}`"
            :stroke="color"
            stroke-dasharray="4 3"
            stroke-width="1.5"
            fill="none"
          />
          <!-- 説明は右の行の手前に置く（橋が集まる真ん中で文字が重ならないように） -->
          <text :x="b.x2 - 4" :y="b.y2 - 4" text-anchor="end">{{ b.label }}</text>
        </g>
      </svg>

      <div class="side other" @scroll="measure">
        <h2>過去</h2>
        <p v-if="store.tangle.others.length === 0" class="hint">
          この調べ物には、他の調べ物とのつながりがありません
        </p>
        <div v-for="o in store.tangle.others" :key="o.session.id" class="other-session">
          <h3 :style="{ borderColor: sessionColor(store.sessionById.get(o.session.id)?.color_index ?? 0) }">
            {{ sessionTitle(o.session) }}
            <span class="when">{{ formatDate(o.session.started_at) }}・{{ o.session.relation === 'past' ? '前' : '後' }}</span>
          </h3>
          <ul>
            <li
              v-for="n in o.nodes"
              :key="n.id"
              :data-node="n.id"
              data-side="other"
              :class="{ linked: n.linked, selected: n.id === store.selectedNodeId }"
              tabindex="0"
              role="button"
              @click="store.select(n.id)"
              @keydown.enter.prevent="store.select(n.id)"
            >
              <span class="text">{{ shortTitle(n.title, n.id, 32) }}</span>
            </li>
          </ul>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.tangle {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 96px minmax(0, 1fr);
  padding: 10px 16px;
  overflow: hidden;
  border-top: 1px solid var(--line);
  background: var(--panel);
}
.side {
  min-height: 0;
  overflow-y: auto;
}
.current {
  grid-column: 1;
}
.other {
  grid-column: 3;
}
.bridges {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: visible;
}
.bridges text {
  font-size: 10px;
  fill: var(--muted);
  paint-order: stroke;
  stroke: var(--panel);
  stroke-width: 3px;
}
h2 {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 6px;
  padding-left: 8px;
  border-left: 4px solid var(--line);
  font-size: 13px;
}
.caption {
  color: var(--muted);
  font-weight: 400;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.edit {
  padding: 0 4px;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}
.rename input {
  width: 100%;
  padding: 2px 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--bg);
  color: var(--fg);
  font: inherit;
}
h3 {
  display: flex;
  gap: 6px;
  margin: 8px 0 2px;
  padding-left: 6px;
  border-left: 3px solid var(--line);
  font-size: 12px;
}
.when {
  color: var(--muted);
  font-weight: 400;
}
.tree,
ul {
  margin: 0;
  padding: 0;
  list-style: none;
}
li {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  font-size: 12px;
  border-radius: 4px;
  cursor: pointer;
}
.text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
li:hover,
li:focus-visible {
  background: var(--hover);
  outline: none;
}
li.selected {
  background: var(--selected);
}
li.linked {
  font-weight: 700;
}
.dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.hint {
  margin: 8px 0;
  font-size: 12px;
  color: var(--muted);
}
.hint.whole {
  grid-column: 1 / -1;
  align-self: center;
  text-align: center;
}
</style>
