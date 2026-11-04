<script setup lang="ts">
// 点が多いとき（2,000超）のグラフ（FR-15）。sigma.js で WebGL に描く。
// 見た目と操作は SVG の GraphView にそろえる（選択、検索での強調、ダブルクリックで開く、選んだ点の過去とのつながりだけを描く）。
// WebGL は点線を描けないので、過去とのつながりは細く薄い線で表す。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Sigma from 'sigma'
import { useTadoriStore } from '../stores/tadori'
import { buildGraphology, type WebglEdgeAttributes, type WebglNodeAttributes } from '../graph/webgl'
import type { Point } from '../graph/layout'
import { sessionColor } from '../graph/style'
import type { GraphNode } from '../api/types'

const props = defineProps<{ layout: Map<string, Point> }>()
const store = useTadoriStore()
const container = ref<HTMLDivElement | null>(null)
let sigma: Sigma<WebglNodeAttributes, WebglEdgeAttributes> | null = null

const colorOf = (n: GraphNode) => sessionColor(store.sessionById.get(n.session_id)?.color_index ?? 0)
const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

function create() {
  sigma?.kill()
  sigma = null
  if (!container.value) return
  const graph = buildGraphology(store.visibleNodes, store.visibleEdges, props.layout, colorOf)
  const instance = new Sigma(graph, container.value, {
    settings: { renderEdgeLabels: false, labelRenderedSizeThreshold: 6 },
    nodeReducer: (key, data) => {
      const selected = key === store.selectedNodeId
      const dim = store.matches !== null && !store.matches.has(key)
      return {
        ...data,
        size: selected ? data.size + 3 : data.size,
        highlighted: selected,
        opacity: dim ? 0.15 : 1,
        labelColor: cssVar('--fg'),
        labelVisibility: selected || store.matches?.has(key) ? 'visible' : data.labelVisibility,
      }
    },
    edgeReducer: (key, data) => {
      const kind = graph.getEdgeAttribute(key, 'kind')
      const touches = graph.source(key) === store.selectedNodeId || graph.target(key) === store.selectedNodeId
      // 過去とのつながりは、選んだ点の分だけ描く（SVG で点が多いときと同じ決まり）
      return { ...data, visibility: kind === 'past' && !touches ? 'hidden' : 'visible', opacity: kind === 'past' ? 0.7 : 0.5 }
    },
  })
  instance.on('clickNode', ({ node }) => store.select(node))
  instance.on('doubleClickNode', (payload) => {
    payload.preventSigmaDefault() // ダブルクリックでの拡大をやめ、元のページを開く
    const n = store.nodeById.get(payload.node)
    if (n) window.open(n.url, '_blank', 'noopener')
  })
  sigma = instance
}

function fit() {
  void sigma?.getCamera().reset()
}

onMounted(create)
onBeforeUnmount(() => sigma?.kill())
// 点や配置が変わったら作り直し、選択や検索が変わったら描き直すだけにする
watch(() => [props.layout, store.visibleNodes, store.visibleEdges], create)
watch(() => [store.selectedNodeId, store.matches], () => sigma?.refresh({ skipIndexation: true }))

defineExpose({ fit })
</script>

<template>
  <div ref="container" class="webgl" aria-label="グラフ（WebGL）" />
</template>

<style scoped>
.webgl {
  position: absolute;
  inset: 0;
}
</style>
