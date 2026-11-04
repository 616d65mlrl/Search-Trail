<script setup lang="ts">
// 詳細（05 画面仕様）: 選んだページの来た元、分岐先 B・C・D、過去とのつながり、概念
import { computed, ref, watch } from 'vue'
import { useTadoriStore } from '../stores/tadori'
import { formatDate, formatDuration, formatTime, REASON_LABELS, sessionColor } from '../graph/style'

const store = useTadoriStore()
const node = computed(() => store.selectedNode)
const detail = computed(() => (store.detail?.node.id === store.selectedNodeId ? store.detail : null))
// 本文の取得（FR-14）は PC の外へ通信するので、必ず確認してから行う
const bodyMessage = ref('')
watch(() => store.selectedNodeId, () => (bodyMessage.value = ''))
// 検索の点は Google 検索の URL で開くようになっているので、それは取得の対象にしない
const fetchable = computed(
  () =>
    node.value !== undefined &&
    /^https?:\/\//.test(node.value.url) &&
    !node.value.url.startsWith('https://www.google.com/search?'),
)
async function onFetchBody() {
  const n = node.value
  if (!n) return
  const ok = window.confirm(`${n.domain} に接続して、このページの本文を取得します。よろしいですか？
（Search-Trail が外部と通信するのは、この操作のときだけです）`)
  if (!ok) return
  bodyMessage.value = await store.fetchBody(n.page_id)
}

const color = computed(() =>
  node.value ? sessionColor(store.sessionById.get(node.value.session_id)?.color_index ?? 0) : 'transparent',
)
</script>

<template>
  <aside class="detail" aria-label="詳細">
    <p v-if="!node" class="hint">点やログの行を選ぶと、ここに詳しい情報が出ます。</p>
    <template v-else>
      <h2 :style="{ borderColor: color }">{{ node.title ?? node.url }}</h2>
      <a class="url" :href="node.url" target="_blank" rel="noopener">{{ node.domain }}</a>
      <p class="meta">{{ formatTime(node.first_visit_at) }} ・ {{ node.visits }} 回</p>

      <template v-if="detail">
        <h3>来た元</h3>
        <p v-if="!detail.parent" class="hint">ここが出発点です</p>
        <button v-else class="link" @click="store.select(detail.parent.id)">
          {{ detail.parent.title }}
          <span class="reason" :class="{ guess: detail.parent.reason === 'time' || detail.parent.reason === 'search' }">
            {{ REASON_LABELS[detail.parent.reason ?? ''] ?? '' }}
          </span>
        </button>

        <h3>分岐先</h3>
        <p v-if="detail.children.length === 0" class="hint">ここから先はありません</p>
        <button v-for="c in detail.children" :key="c.id" class="link" @click="store.select(c.id)">
          <span v-if="detail.children.length > 1" class="letter">{{ c.letter }}</span>
          {{ c.title }}
        </button>

        <h3>過去とのつながり</h3>
        <p v-if="detail.past_links.length === 0" class="hint">なし</p>
        <button v-for="p in detail.past_links" :key="p.id" class="link past" @click="store.select(p.id)">
          <span class="past-title">{{ p.title }}</span>
          <span class="reason">
            {{ p.concept ?? '同じページ' }}・{{ p.session_name ?? `${formatDate(p.session_started_at)} の調べ物` }}
            （{{ formatDate(p.session_started_at) }}{{ p.relation === 'past' ? '' : '・後' }}）
          </span>
        </button>

        <h3>概念</h3>
        <p v-if="detail.concepts.length === 0" class="hint">このページには、他のページと共通する言葉がありません</p>
        <p v-else class="concepts">
          <span v-for="c in detail.concepts" :key="c" class="concept">{{ c }}</span>
        </p>
        <button v-if="fetchable" class="fetch" :disabled="store.fetchingBody" @click="onFetchBody">
          {{ store.fetchingBody ? '取得しています…' : '本文から概念を取る（外部に接続）' }}
        </button>
        <p v-if="bodyMessage" class="hint" role="status">{{ bodyMessage }}</p>

        <h3>訪問</h3>
        <ul class="visits">
          <li v-for="(v, i) in detail.visits" :key="i">
            {{ formatTime(v.visited_at) }} <span class="reason">{{ formatDuration(v.duration_ms) }}</span>
          </li>
        </ul>
      </template>
    </template>
  </aside>
</template>

<style scoped>
.detail {
  overflow-y: auto;
  padding: 12px 16px;
  border-left: 1px solid var(--line);
  background: var(--panel);
  font-size: 13px;
}
h2 {
  margin: 0 0 4px;
  padding-left: 8px;
  border-left: 4px solid;
  font-size: 15px;
  word-break: break-word;
}
h3 {
  margin: 14px 0 4px;
  font-size: 12px;
  color: var(--muted);
}
.url {
  color: var(--accent);
  font-size: 12px;
}
.meta {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.link {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 4px 6px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--fg);
  text-align: left;
  font: inherit;
  cursor: pointer;
}
.link:hover,
.link:focus-visible {
  background: var(--hover);
  outline: none;
}
.letter {
  flex: none;
  display: inline-grid;
  place-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--fg);
  color: var(--bg);
  font-size: 11px;
  font-weight: 700;
}
.reason {
  margin-left: auto;
  color: var(--muted);
  font-size: 11px;
  white-space: nowrap;
}
.link.past {
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
}
.link.past .reason {
  margin-left: 0;
  white-space: normal;
}
.reason.guess {
  font-style: italic;
}
.hint {
  margin: 2px 0;
  color: var(--muted);
  font-size: 12px;
}
.concepts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.concept {
  padding: 1px 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
}
.fetch {
  margin-top: 6px;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: transparent;
  color: var(--fg);
  font-size: 12px;
  cursor: pointer;
}
.fetch:disabled {
  opacity: 0.5;
  cursor: wait;
}
.visits {
  margin: 0;
  padding: 0;
  list-style: none;
}
.visits li {
  display: flex;
  padding: 2px 0;
}
</style>
