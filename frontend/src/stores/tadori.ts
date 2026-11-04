// 4つの領域（履歴ログ、グラフ、今回と過去、詳細）で共有する状態（05 画面仕様、FR-07〜FR-09）。
// どの領域でページを選んでも、ここの selectedNodeId が変わり、4領域すべてが同じページを選んだ状態になる。

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, ApiError } from '../api/client'
import type { GraphResponse, NodeDetail, Status, TangleResponse } from '../api/types'
import { MAX_SVG_NODES } from '../graph/style'

export const PERIODS = {
  all: { label: '全期間', days: null },
  '7d': { label: '7日', days: 7 },
  '30d': { label: '30日', days: 30 },
  '90d': { label: '90日', days: 90 },
} as const
export type Period = keyof typeof PERIODS

const DAY_MS = 24 * 60 * 60 * 1000

// 点の ID（s{調べ物ID}-p{ページID}）から調べ物の ID を取り出す
export function sessionIdOf(nodeId: string): number | undefined {
  const match = /^s(\d+)-p\d+$/.exec(nodeId)
  return match ? Number(match[1]) : undefined
}

export const useTadoriStore = defineStore('tadori', () => {
  const status = ref<Status | null>(null)
  const graph = ref<GraphResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const importing = ref(false)
  const notice = ref('') // 取り込みの結果など、上の帯に短く出す知らせ

  const period = ref<Period>('all')
  const hiddenSessionIds = ref<number[]>([])
  const query = ref('')
  const conceptsOn = ref(false)

  const selectedNodeId = ref<string | null>(null)
  const detail = ref<NodeDetail | null>(null)
  const tangle = ref<TangleResponse | null>(null)
  let selectSeq = 0 // 速く選び直したとき、古い返事で上書きしないための番号

  // 期間は「最新の訪問」から数える。古い履歴だけを取り込んだときも空にならないようにするため
  const range = computed(() => {
    const days = PERIODS[period.value].days
    const latest = status.value?.range?.to
    if (days === null || latest == null) return { from: null, to: null }
    return { from: latest - days * DAY_MS + 1, to: latest + 1 }
  })

  const sessions = computed(() => graph.value?.sessions ?? [])
  const sessionById = computed(() => new Map(sessions.value.map((s) => [s.id, s])))
  const visibleNodes = computed(() =>
    (graph.value?.nodes ?? []).filter((n) => !hiddenSessionIds.value.includes(n.session_id)),
  )
  const nodeById = computed(() => new Map(visibleNodes.value.map((n) => [n.id, n])))
  const visibleEdges = computed(() =>
    (graph.value?.edges ?? []).filter((e) => nodeById.value.has(e.source) && nodeById.value.has(e.target)),
  )
  // 「概念も点にする」（FR-13）: 表示中のページにつながる概念と、ページ → 概念の線
  const conceptEdges = computed(() =>
    conceptsOn.value ? (graph.value?.edges ?? []).filter((e) => e.kind === 'mention' && nodeById.value.has(e.source)) : [],
  )
  const conceptNodes = computed(() => {
    const used = new Set(conceptEdges.value.map((e) => e.target))
    return (graph.value?.concepts ?? []).filter((c) => used.has(c.id))
  })
  const selectedNode = computed(() => (selectedNodeId.value ? nodeById.value.get(selectedNodeId.value) : undefined))
  const tooManyNodes = computed(() => visibleNodes.value.length > MAX_SVG_NODES)

  // 検索欄に一致するページ（空欄なら null = すべて普通に表示）
  const matches = computed<Set<string> | null>(() => {
    const q = query.value.trim().toLowerCase()
    if (!q) return null
    return new Set(
      visibleNodes.value
        .filter((n) => (n.title ?? '').toLowerCase().includes(q) || n.url.toLowerCase().includes(q))
        .map((n) => n.id),
    )
  })

  async function init() {
    error.value = null
    try {
      status.value = await api.status()
      if (status.value.imported) await loadGraph()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  async function loadGraph() {
    loading.value = true
    error.value = null
    try {
      graph.value = await api.graph({ ...range.value, concepts: conceptsOn.value })
      const known = new Set(graph.value.sessions.map((s) => s.id))
      hiddenSessionIds.value = hiddenSessionIds.value.filter((id) => known.has(id))
      if (selectedNodeId.value && !nodeById.value.has(selectedNodeId.value)) await select(null)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'not_imported') status.value = { ...status.value!, imported: false }
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function select(nodeId: string | null) {
    const seq = ++selectSeq
    selectedNodeId.value = nodeId
    if (nodeId === null) {
      detail.value = null
      tangle.value = null
      return
    }
    // 表示範囲の外（今回と過去の右側など）の点も選べるよう、調べ物は ID から割り出す
    const sessionId = nodeById.value.get(nodeId)?.session_id ?? sessionIdOf(nodeId)
    // 今回と過去の図は調べ物ごとなので、同じ調べ物の中で選び直したときは取り直さない
    const sameSession = sessionId !== undefined && tangle.value?.session.id === sessionId
    try {
      const [d, t] = await Promise.all([
        api.node(nodeId),
        sessionId === undefined ? null : sameSession ? tangle.value : api.tangle(sessionId),
      ])
      if (seq !== selectSeq) return
      detail.value = d
      tangle.value = t
    } catch (e) {
      if (seq === selectSeq) error.value = e instanceof Error ? e.message : String(e)
    }
  }

  // 調べ物の名前を手で直す。空欄なら自動の名前に戻る（FR-12）
  async function renameSession(sessionId: number, name: string) {
    try {
      const updated = await api.renameSession(sessionId, name)
      if (graph.value) {
        graph.value.sessions = graph.value.sessions.map((s) => (s.id === sessionId ? { ...s, name: updated.name } : s))
      }
      if (tangle.value) {
        if (tangle.value.session.id === sessionId) tangle.value.session.name = updated.name
        for (const o of tangle.value.others) if (o.session.id === sessionId) o.session.name = updated.name
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  // 画面で選んだ History を取り込み、読み直す。前に取り込んだ履歴とは入れ替わるので、選択や表示の切り替えも戻す
  async function runImport(files: File[]) {
    if (importing.value || files.length === 0) return
    importing.value = true
    try {
      const result = await api.runImport(files)
      notice.value = `${result.added_visits} 件の訪問を取り込みました`
      selectedNodeId.value = null
      detail.value = null
      tangle.value = null
      hiddenSessionIds.value = []
      await init()
    } catch (e) {
      notice.value = `取り込みに失敗しました: ${e instanceof Error ? e.message : String(e)}`
    } finally {
      importing.value = false
    }
  }

  // ページの本文から概念を取る（FR-14）。終わったら、概念と過去とのつながりを読み直す
  const fetchingBody = ref(false)
  async function fetchBody(pageId: number): Promise<string> {
    fetchingBody.value = true
    try {
      const result = await api.fetchBody(pageId)
      await loadGraph()
      if (selectedNodeId.value) await select(selectedNodeId.value)
      return result.concepts.length
        ? `本文から ${result.concepts.length} 個の言葉を取りました`
        : '本文から、概念にできる言葉は見つかりませんでした'
    } catch (e) {
      return e instanceof Error ? e.message : String(e)
    } finally {
      fetchingBody.value = false
    }
  }

  async function setPeriod(p: Period) {
    period.value = p
    await loadGraph()
  }

  async function setConcepts(on: boolean) {
    conceptsOn.value = on
    await loadGraph()
  }

  // 選択中の調べ物は非表示にできない。切り替えられたら true
  function toggleSession(sessionId: number): boolean {
    if (selectedNode.value?.session_id === sessionId) return false
    hiddenSessionIds.value = hiddenSessionIds.value.includes(sessionId)
      ? hiddenSessionIds.value.filter((id) => id !== sessionId)
      : [...hiddenSessionIds.value, sessionId]
    return true
  }

  // 調べ物をまとめて表示する・隠す。選択中のページの調べ物は隠さない（隠せなかったら false を返す）
  function setSessionsHidden(sessionIds: number[], hidden: boolean): boolean {
    const keep = selectedNode.value?.session_id
    const targets = new Set(hidden ? sessionIds.filter((id) => id !== keep) : sessionIds)
    hiddenSessionIds.value = hidden
      ? [...new Set([...hiddenSessionIds.value, ...targets])]
      : hiddenSessionIds.value.filter((id) => !targets.has(id))
    return !hidden || keep === undefined || !sessionIds.includes(keep)
  }

  // Enter で、最初に一致したページ（いちばん早く開いたもの）を選ぶ
  async function selectFirstMatch() {
    const hits = matches.value
    if (!hits || hits.size === 0) return
    const first = visibleNodes.value.find((n) => hits.has(n.id))
    if (first) await select(first.id)
  }

  return {
    status, graph, loading, error, importing, notice, fetchingBody, period, hiddenSessionIds, query, conceptsOn,
    selectedNodeId, detail, tangle, range, sessions, sessionById, visibleNodes, nodeById,
    visibleEdges, conceptEdges, conceptNodes, selectedNode, tooManyNodes, matches,
    init, loadGraph, select, setPeriod, setConcepts, toggleSession, setSessionsHidden, selectFirstMatch, renameSession, runImport, fetchBody,
  }
})
