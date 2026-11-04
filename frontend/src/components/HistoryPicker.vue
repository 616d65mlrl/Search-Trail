<script setup lang="ts">
// 取り込む History ファイルを選ぶボタン。上の帯と「まだ取り込んでいません」の画面で使う。
// 選んだファイルの中身だけをサーバーへ送る。ファイルの場所は、ブラウザもサーバーも覚えない（毎回選び直す）。
import { ref } from 'vue'
import { useTadoriStore } from '../stores/tadori'

defineProps<{ label?: string }>()
const emit = defineEmits<{ done: [] }>()
const store = useTadoriStore()
const input = ref<HTMLInputElement | null>(null)

async function onChange() {
  const el = input.value
  if (!el?.files?.length) return
  const files = [...el.files]
  // 同じファイルを続けて選んでも change が起きるよう、選んだ内容を空に戻す
  el.value = ''
  await store.runImport(files)
  emit('done')
}
</script>

<template>
  <button class="pick" :disabled="store.importing" @click="input?.click()">
    {{ store.importing ? '取り込み中…' : (label ?? 'History を選ぶ') }}
  </button>
  <input ref="input" type="file" multiple hidden aria-label="取り込む History ファイル" @change="onChange" />
</template>

<style scoped>
.pick {
  padding: 4px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: transparent;
  color: var(--fg);
  white-space: nowrap;
  cursor: pointer;
}
.pick:disabled {
  opacity: 0.5;
  cursor: wait;
}
</style>
