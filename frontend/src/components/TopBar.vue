<script setup lang="ts">
// 上の帯（05 画面仕様）: 名前、検索欄、調べ物の表示切り替え、期間、「概念も点にする」
import { ref } from 'vue'
import { PERIODS, useTadoriStore, type Period } from '../stores/tadori'
import HistoryPicker from './HistoryPicker.vue'
import SessionPicker from './SessionPicker.vue'

const store = useTadoriStore()
const notice = ref('')

function flash(text: string) {
  notice.value = text
  setTimeout(() => (notice.value = ''), 2500)
}
</script>

<template>
  <header class="topbar">
    <h1 class="name">Search-Trail</h1>
    <input
      v-model="store.query"
      class="search"
      type="search"
      placeholder="ページ名で検索（Enter で選択）"
      aria-label="ページ名で検索"
      @keydown.enter.prevent="store.selectFirstMatch()"
    />
    <!-- 調べ物が多くても帯があふれないよう、表示の切り替えはパネルにまとめる -->
    <SessionPicker v-if="store.sessions.length" @notice="flash" />
    <span class="spacer" />
    <span v-if="notice" class="notice" role="status">{{ notice }}</span>
    <label class="period">
      期間
      <select :value="store.period" @change="store.setPeriod(($event.target as HTMLSelectElement).value as Period)">
        <option v-for="(p, key) in PERIODS" :key="key" :value="key">{{ p.label }}</option>
      </select>
    </label>
    <label class="concepts">
      <input type="checkbox" :checked="store.conceptsOn" @change="store.setConcepts(!store.conceptsOn)" />
      概念も点にする
    </label>
    <HistoryPicker @done="flash(store.notice)" />
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 52px;
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
  overflow: hidden;
}
.name {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.search {
  width: 240px;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
  color: var(--fg);
}
.spacer {
  flex: 1;
}
.notice {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
}
.period,
.concepts {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  white-space: nowrap;
}
</style>
