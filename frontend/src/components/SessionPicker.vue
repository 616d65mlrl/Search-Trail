<script setup lang="ts">
// 調べ物の表示切り替え（上の帯）。調べ物が多いと帯に並べきれないので、ボタン1つにまとめ、押すと一覧のパネルを開く。
// パネルでは名前で絞り込み、日付ごとにチェックボックスで表示・非表示を切り替える。絞り込んだものをまとめて切り替えることもできる。
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useTadoriStore } from '../stores/tadori'
import { formatDate, sessionColor } from '../graph/style'

const emit = defineEmits<{ notice: [text: string] }>()
const store = useTadoriStore()
const open = ref(false)
const filter = ref('')
const button = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const place = ref({ top: 0, right: 0 })

const sessionLabel = (s: { name: string | null; started_at: number }) => s.name ?? `${formatDate(s.started_at)} の調べ物`
const isHidden = (id: number) => store.hiddenSessionIds.includes(id)
const shownCount = computed(() => store.sessions.filter((s) => !isHidden(s.id)).length)
// 調べ物ごとのページの数
const pageCount = computed(() => {
  const count = new Map<number, number>()
  for (const n of store.graph?.nodes ?? []) count.set(n.session_id, (count.get(n.session_id) ?? 0) + 1)
  return count
})
// 名前で絞り込み、新しい順に日付ごとにまとめる
const filtered = computed(() => {
  const q = filter.value.trim().toLowerCase()
  return store.sessions
    .filter((s) => !q || sessionLabel(s).toLowerCase().includes(q))
    .sort((a, b) => b.started_at - a.started_at)
})
const groups = computed(() => {
  const result: { date: string; items: typeof filtered.value }[] = []
  for (const s of filtered.value) {
    const date = formatDate(s.started_at)
    if (result.at(-1)?.date !== date) result.push({ date, items: [] })
    result.at(-1)!.items.push(s)
  }
  return result
})

function toggle(id: number) {
  if (!store.toggleSession(id)) emit('notice', '選択中の調べ物は非表示にできません')
}
function setAll(hidden: boolean) {
  if (!store.setSessionsHidden(filtered.value.map((s) => s.id), hidden)) {
    emit('notice', '選択中の調べ物は表示したままにしました')
  }
}

async function show() {
  const rect = button.value!.getBoundingClientRect()
  place.value = { top: rect.bottom + 6, right: Math.max(8, window.innerWidth - rect.right) }
  open.value = true
  await nextTick()
  input.value?.focus()
}
function onOutside(ev: PointerEvent) {
  const target = ev.target as Node
  if (!panel.value?.contains(target) && !button.value?.contains(target)) open.value = false
}
function onKey(ev: KeyboardEvent) {
  if (ev.key === 'Escape') {
    open.value = false
    button.value?.focus()
  }
}
watch(open, (v) => {
  if (v) {
    document.addEventListener('pointerdown', onOutside)
    document.addEventListener('keydown', onKey)
  } else {
    document.removeEventListener('pointerdown', onOutside)
    document.removeEventListener('keydown', onKey)
  }
})
onBeforeUnmount(() => (open.value = false))
</script>

<template>
  <button
    ref="button"
    class="picker"
    :aria-expanded="open"
    aria-haspopup="dialog"
    @click="open ? (open = false) : show()"
  >
    調べ物 {{ shownCount }} / {{ store.sessions.length }} <span aria-hidden="true">▾</span>
  </button>
  <Teleport to="body">
    <div
      v-if="open"
      ref="panel"
      class="panel"
      role="dialog"
      aria-label="表示する調べ物"
      :style="{ top: `${place.top}px`, right: `${place.right}px` }"
    >
      <input ref="input" v-model="filter" class="filter" type="search" placeholder="名前で絞り込む" aria-label="調べ物を名前で絞り込む" />
      <div class="actions">
        <button @click="setAll(false)">{{ filter ? '一致したものを表示' : 'すべて表示' }}</button>
        <button @click="setAll(true)">{{ filter ? '一致したものを隠す' : 'すべて隠す' }}</button>
        <span class="muted">{{ filtered.length }} 件</span>
      </div>
      <div class="list">
        <p v-if="filtered.length === 0" class="muted empty">一致する調べ物はありません</p>
        <section v-for="g in groups" :key="g.date" class="group">
          <h3>{{ g.date }}</h3>
          <label v-for="s in g.items" :key="s.id" class="item" :class="{ off: isHidden(s.id) }">
            <input type="checkbox" :checked="!isHidden(s.id)" @change="toggle(s.id)" />
            <span class="dot" :style="{ background: sessionColor(s.color_index) }" />
            <span class="name">{{ sessionLabel(s) }}</span>
            <span class="muted">{{ pageCount.get(s.id) ?? 0 }}</span>
          </label>
        </section>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.picker {
  padding: 4px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  color: var(--fg);
  white-space: nowrap;
  cursor: pointer;
}
.panel {
  position: fixed;
  z-index: 20;
  display: flex;
  flex-direction: column;
  width: min(380px, calc(100vw - 16px));
  max-height: min(70vh, 640px);
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--fg);
  box-shadow: 0 8px 24px rgb(0 0 0 / 0.35);
}
.filter {
  margin: 10px 10px 6px;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
  color: var(--fg);
}
.actions {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px 8px;
  border-bottom: 1px solid var(--line);
  font-size: 12px;
}
.actions button {
  padding: 3px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: transparent;
  color: var(--fg);
  cursor: pointer;
}
.actions .muted {
  margin-left: auto;
}
.list {
  overflow-y: auto;
  padding: 4px 0 8px;
}
.group h3 {
  margin: 8px 12px 2px;
  font-size: 11px;
  font-weight: 400;
  color: var(--muted);
}
.item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  font-size: 13px;
  cursor: pointer;
}
.item:hover {
  background: var(--bg);
}
.item.off .name {
  color: var(--muted);
}
.dot {
  flex: none;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.muted {
  color: var(--muted);
  font-size: 12px;
}
.empty {
  padding: 8px 12px;
}
</style>
