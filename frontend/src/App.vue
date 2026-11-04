<script setup lang="ts">
// 画面全体（05 画面仕様）: 上の帯と、履歴ログ・グラフ・今回と過去・詳細の4領域
import { computed, onMounted, reactive, ref } from 'vue'
import { useTadoriStore } from './stores/tadori'
import TopBar from './components/TopBar.vue'
import HistoryPicker from './components/HistoryPicker.vue'
import HistoryLog from './components/HistoryLog.vue'
import GraphView from './components/GraphView.vue'
import LinksView from './components/LinksView.vue'
import TanglePanel from './components/TanglePanel.vue'
import DetailPanel from './components/DetailPanel.vue'

const store = useTadoriStore()
onMounted(() => store.init())

// --- 領域の大きさをドラッグで変える ---
// 境目（区切り線）をつかんで動かす。ダブルクリックで元の大きさに戻す。矢印キーでも動かせる。
// 大きさはこのブラウザにだけ覚えておく（保存できない環境でも、既定の大きさで動く）
type Pane = 'log' | 'detail' | 'tangle'
const DEFAULT_SIZES: Record<Pane, number> = { log: 360, detail: 300, tangle: 290 }
const LIMITS: Record<Pane, [number, number]> = { log: [300, 720], detail: [220, 640], tangle: [120, 900] }
const STORAGE_KEY = 'tadori.paneSizes'

function loadSizes(): Record<Pane, number> {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<Record<Pane, number>>
    return { ...DEFAULT_SIZES, ...saved }
  } catch {
    return { ...DEFAULT_SIZES }
  }
}
const sizes = reactive(loadSizes())

function setSize(pane: Pane, value: number) {
  const [min, max] = LIMITS[pane]
  // 下の領域は、グラフが 150px 以上残る高さまでにする
  const limit = pane === 'tangle' ? Math.min(max, window.innerHeight - 52 - 150) : max
  sizes[pane] = Math.round(Math.max(min, Math.min(limit, value)))
}
function saveSizes() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sizes))
  } catch {
    // 保存できなくても、今の画面ではそのまま使える
  }
}

// 境目を右（下）へ動かしたとき、その領域が大きくなるなら +1、小さくなるなら -1
const DIRECTION: Record<Pane, number> = { log: 1, detail: -1, tangle: -1 }
function startResize(pane: Pane, ev: PointerEvent) {
  const el = ev.currentTarget as HTMLElement
  el.setPointerCapture(ev.pointerId)
  const start = pane === 'tangle' ? ev.clientY : ev.clientX
  const from = sizes[pane]
  const move = (e: PointerEvent) => setSize(pane, from + DIRECTION[pane] * ((pane === 'tangle' ? e.clientY : e.clientX) - start))
  const end = () => {
    el.removeEventListener('pointermove', move)
    el.removeEventListener('pointerup', end)
    el.removeEventListener('pointercancel', end)
    saveSizes()
  }
  el.addEventListener('pointermove', move)
  el.addEventListener('pointerup', end)
  el.addEventListener('pointercancel', end)
}
function keyResize(pane: Pane, ev: KeyboardEvent) {
  const keys = pane === 'tangle' ? ['ArrowUp', 'ArrowDown'] : ['ArrowLeft', 'ArrowRight']
  const i = keys.indexOf(ev.key)
  if (i < 0) return
  ev.preventDefault()
  setSize(pane, sizes[pane] + DIRECTION[pane] * (i === 0 ? -16 : 16))
  saveSizes()
}
function resetSize(pane: Pane) {
  sizes[pane] = DEFAULT_SIZES[pane]
  saveSizes()
}
const gridStyle = computed(() => ({
  '--log-w': `${sizes.log}px`,
  '--detail-w': `${sizes.detail}px`,
  '--tangle-h': `${sizes.tangle}px`,
}))

// 中央の表示（木 / つながり）
const centerView = ref<'tree' | 'links'>('tree')

const state = computed(() => {
  if (store.status === null) return store.error ? 'error' : 'loading'
  if (!store.status.imported) return 'not-imported'
  if (store.graph === null) return store.error ? 'error' : 'loading'
  if (store.graph.nodes.length === 0) return 'empty'
  return 'ready'
})
</script>

<template>
  <div class="app" :class="state" :style="gridStyle">
    <TopBar class="top" />

    <template v-if="state === 'ready' || state === 'loading'">
      <div
        v-for="pane in (['log', 'detail', 'tangle'] as const)"
        :key="pane"
        class="splitter"
        :class="`split-${pane}`"
        role="separator"
        tabindex="0"
        :aria-orientation="pane === 'tangle' ? 'horizontal' : 'vertical'"
        :aria-valuenow="sizes[pane]"
        :aria-valuemin="LIMITS[pane][0]"
        :aria-valuemax="LIMITS[pane][1]"
        :aria-label="{ log: '履歴ログの幅', detail: '詳細の幅', tangle: '今回と過去の高さ' }[pane]"
        title="ドラッグで大きさを変える（ダブルクリックで元に戻す）"
        @pointerdown.prevent="startResize(pane, $event)"
        @dblclick="resetSize(pane)"
        @keydown="keyResize(pane, $event)"
      />
    </template>

    <main v-if="state === 'not-imported'" class="center">
      <h2>取り込む History ファイルを選んでください</h2>
      <p>
        履歴はこの PC のメモリの中だけで扱い、ファイルには保存しません。<br />
        サーバーを止めると消えるので、起動するたびに選び直します。
      </p>
      <HistoryPicker label="History を選ぶ" />
      <p v-if="store.notice" class="notice" role="status">{{ store.notice }}</p>
      <p class="hint">
        Windows の Chrome では、ファイルを選ぶ画面の「ファイル名」に次を貼りつけると開けます
        （History-wal があれば一緒に選ぶと、直近の訪問も入ります）。
      </p>
      <pre><code>%LOCALAPPDATA%\Google\Chrome\User Data\Default\History</code></pre>
    </main>

    <main v-else-if="state === 'error'" class="center">
      <h2>サーバーにつながりません</h2>
      <p>{{ store.error }}</p>
      <p><code>uv run tadori serve</code> が動いているか確かめてください。</p>
      <button @click="store.init()">もう一度試す</button>
    </main>

    <main v-else-if="state === 'empty'" class="center">
      <h2>この期間の履歴はありません</h2>
      <button @click="store.setPeriod('all')">全期間を表示する</button>
    </main>

    <template v-else-if="state === 'loading'">
      <div class="log skeleton" aria-busy="true">
        <div v-for="i in 8" :key="i" class="bar" />
      </div>
      <div class="graph skeleton" aria-busy="true" />
      <div class="tangle skeleton" aria-busy="true">
        <div v-for="i in 3" :key="i" class="bar" />
      </div>
      <div class="detail skeleton" aria-busy="true">
        <div v-for="i in 4" :key="i" class="bar" />
      </div>
    </template>

    <template v-else>
      <HistoryLog class="log" />
      <section class="graph center-view">
        <!-- 中央の表示の切り替え: 調べ物の木（放射状の森）と、調べ物どうしのつながり -->
        <div class="view-tabs" role="tablist" aria-label="中央の表示">
          <button role="tab" :aria-selected="centerView === 'tree'" @click="centerView = 'tree'">木</button>
          <button role="tab" :aria-selected="centerView === 'links'" @click="centerView = 'links'">つながり</button>
        </div>
        <!-- 木は隠すだけにして、拡大や位置を保つ -->
        <GraphView v-show="centerView === 'tree'" class="fill" />
        <LinksView v-if="centerView === 'links'" />
      </section>
      <TanglePanel class="tangle" />
      <DetailPanel class="detail" />
    </template>
  </div>
</template>

<style scoped>
.app {
  display: grid;
  grid-template-rows: 52px minmax(0, 1fr) 6px var(--tangle-h);
  grid-template-columns: var(--log-w) 6px minmax(0, 1fr) 6px var(--detail-w);
  grid-template-areas:
    'top top top top top'
    'log s-log graph s-detail detail'
    'log s-log s-tangle s-detail detail'
    'log s-log tangle s-detail detail';
  height: 100vh;
}
/* 領域の境目。つかむと色が付く */
.splitter {
  background: var(--line);
  touch-action: none;
  outline: none;
}
.splitter:hover,
.splitter:active,
.splitter:focus-visible {
  background: var(--accent);
}
.split-log {
  grid-area: s-log;
  cursor: col-resize;
}
.split-detail {
  grid-area: s-detail;
  cursor: col-resize;
}
.split-tangle {
  grid-area: s-tangle;
  cursor: row-resize;
}
.top {
  grid-area: top;
}
.log {
  grid-area: log;
}
.graph {
  grid-area: graph;
}
.center-view {
  position: relative;
  overflow: hidden;
}
.fill {
  position: absolute;
  inset: 0;
}
.view-tabs {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 3;
  display: flex;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
  background: var(--panel);
}
.view-tabs button {
  padding: 4px 12px;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
}
.view-tabs button[aria-selected='true'] {
  background: var(--bg);
  color: var(--fg);
  font-weight: 700;
}
.tangle {
  grid-area: tangle;
}
.detail {
  grid-area: detail;
}
.center {
  grid-row: 2 / -1;
  grid-column: 1 / -1;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 8px;
  padding: 24px;
  text-align: center;
}
.center .hint,
.center .notice {
  max-width: 560px;
  font-size: 13px;
  color: var(--muted);
}
.center pre {
  padding: 12px 20px;
  border-radius: 6px;
  background: var(--panel);
  text-align: left;
}
.center button {
  padding: 6px 16px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  color: var(--fg);
  cursor: pointer;
}
.skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  background: var(--panel);
}
.graph.skeleton {
  background: var(--bg);
}
.bar {
  height: 14px;
  border-radius: 4px;
  background: var(--hover);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.5;
  }
}

/* 1180px 未満では詳細を隠す */
@media (max-width: 1179px) {
  .app {
    grid-template-columns: var(--log-w) 6px minmax(0, 1fr);
    grid-template-areas:
      'top top top'
      'log s-log graph'
      'log s-log s-tangle'
      'log s-log tangle';
  }
  .detail,
  .split-detail {
    display: none;
  }
}

/* 820px 未満では、上から「グラフ、今回と過去、履歴ログ」の縦並び */
@media (max-width: 819px) {
  .app {
    grid-template-rows: 52px 60vh 290px auto;
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'top' 'graph' 'tangle' 'log';
    height: auto;
  }
  .splitter {
    display: none;
  }
}
</style>
