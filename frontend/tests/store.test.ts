import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GraphResponse, NodeDetail, Status, TangleResponse } from '../src/api/types'
import { sessionIdOf, useTadoriStore } from '../src/stores/tadori'

const status: Status = {
  imported: true, visits: 3, pages: 3, sessions: 2,
  range: { from: 1_000, to: 10 * 86_400_000 }, last_import_at: 0,
}

const graph: GraphResponse = {
  range: { from: 1_000, to: 10 * 86_400_000 },
  sessions: [
    { id: 1, name: null, started_at: 1_000, color_index: 0 },
    { id: 2, name: null, started_at: 5_000, color_index: 1 },
  ],
  nodes: [
    { id: 's1-p1', session_id: 1, page_id: 1, title: 'Lens', domain: 'github.com', url: 'https://github.com/x',
      visits: 2, first_visit_at: 1_000, branch_count: 0, past_count: 0 },
    { id: 's1-p2', session_id: 1, page_id: 2, title: 'Plotly', domain: 'plotly.io', url: 'https://plotly.io/',
      visits: 1, first_visit_at: 2_000, branch_count: 0, past_count: 0 },
    { id: 's2-p3', session_id: 2, page_id: 3, title: '辞書とは', domain: 'docs.python.jp', url: 'https://docs.python.jp/',
      visits: 1, first_visit_at: 5_000, branch_count: 0, past_count: 0 },
  ],
  edges: [
    { source: 's1-p1', target: 's1-p2', kind: 'nav', count: 1 },
    { source: 's2-p3', target: 's1-p1', kind: 'past', concept: 'python', score: 1.2 },
    { source: 's1-p1', target: 'c7', kind: 'mention' },
    { source: 's2-p3', target: 'c7', kind: 'mention' },
  ],
  concepts: [{ id: 'c7', label: 'python', page_count: 2 }],
}

const detail = (id: string): NodeDetail => ({
  node: { id, title: id, visits: 1 }, parent: null, children: [], past_links: [], concepts: [], visits: [],
})
const tangle = (sessionId: number): TangleResponse => ({
  session: { id: sessionId, name: null }, tree: [], others: [], bridges: [],
})

let calls: string[] = []
let imported = 0

beforeEach(() => {
  setActivePinia(createPinia())
  calls = []
  imported = 0
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push(method === 'GET' ? input : `${method} ${input}`)
    const url = new URL(input, 'http://localhost')
    let body: unknown
    if (method === 'PATCH' && url.pathname.startsWith('/api/sessions/')) {
      const name = (JSON.parse(String(init!.body)) as { name: string }).name
      body = { id: Number(url.pathname.split('/')[3]), name: name || '自動の名前', started_at: 0, ended_at: 0, color_index: 0, page_count: 1 }
    } else if (method === 'POST' && url.pathname === '/api/import') body = { added_visits: (imported += 3), skipped_visits: 0 }
    else if (method === 'POST' && url.pathname === '/api/pages/1/fetch') body = { page_id: 1, concepts: ['python', 'aiohttp'] }
    else if (url.pathname === '/api/status') body = status
    else if (url.pathname === '/api/graph') body = graph
    else if (url.pathname.startsWith('/api/nodes/')) body = detail(decodeURIComponent(url.pathname.split('/').pop()!))
    else if (url.pathname.endsWith('/tangle')) body = tangle(Number(url.pathname.split('/')[3]))
    else return new Response(JSON.stringify({ error: { code: 'not_found', message: 'x' } }), { status: 404 })
    return new Response(JSON.stringify(body), { status: 200 })
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('4領域で共有する状態', () => {
  it('起動すると状態とグラフを読む', async () => {
    const store = useTadoriStore()
    await store.init()
    expect(store.visibleNodes).toHaveLength(3)
    expect(calls).toEqual(['/api/status', '/api/graph'])
  })

  it('選ぶと詳細と今回と過去を取りに行き、同じ調べ物の中では今回と過去を取り直さない', async () => {
    const store = useTadoriStore()
    await store.init()
    await store.select('s1-p1')
    expect(store.selectedNodeId).toBe('s1-p1')
    expect(store.detail?.node.id).toBe('s1-p1')
    expect(store.tangle?.session.id).toBe(1)

    calls = []
    await store.select('s1-p2')
    expect(calls).toEqual(['/api/nodes/s1-p2'])
  })

  it('選択中の調べ物は非表示にできない', async () => {
    const store = useTadoriStore()
    await store.init()
    await store.select('s1-p1')
    expect(store.toggleSession(1)).toBe(false)
    expect(store.toggleSession(2)).toBe(true)
    expect(store.visibleNodes.map((n) => n.id)).toEqual(['s1-p1', 's1-p2'])
    // 非表示の調べ物につながる線も消える
    expect(store.toggleSession(2)).toBe(true)
    expect(store.visibleNodes).toHaveLength(3)
  })

  it('調べ物をまとめて隠す・表示する（選択中の調べ物は残す）', async () => {
    const store = useTadoriStore()
    await store.init()
    await store.select('s1-p1')
    expect(store.setSessionsHidden([1, 2], true)).toBe(false)
    expect(store.hiddenSessionIds).toEqual([2])
    expect(store.setSessionsHidden([1, 2], false)).toBe(true)
    expect(store.hiddenSessionIds).toEqual([])
  })

  it('検索欄に一致しない点を見分け、Enter で最初に一致したページを選ぶ', async () => {
    const store = useTadoriStore()
    await store.init()
    expect(store.matches).toBeNull()
    store.query = 'PYTHON'
    expect([...store.matches!]).toEqual(['s2-p3']) // URL の docs.python.jp に一致
    await store.selectFirstMatch()
    expect(store.selectedNodeId).toBe('s2-p3')
  })

  it('期間は最新の訪問から数え、変えるとグラフを取り直す', async () => {
    const store = useTadoriStore()
    await store.init()
    calls = []
    await store.setPeriod('7d')
    const latest = status.range!.to!
    expect(store.range).toEqual({ from: latest - 7 * 86_400_000 + 1, to: latest + 1 })
    expect(calls).toEqual([`/api/graph?from=${latest - 7 * 86_400_000 + 1}&to=${latest + 1}`])
  })

  it('まだ取り込んでいないときはグラフを読まない', async () => {
    status.imported = false
    try {
      const store = useTadoriStore()
      await store.init()
      expect(store.graph).toBeNull()
      expect(calls).toEqual(['/api/status'])
    } finally {
      status.imported = true
    }
  })

  it('概念の点は「概念も点にする」のときだけ。過去とのつながりの線は表示中の点どうしだけ', async () => {
    const store = useTadoriStore()
    await store.init()
    expect(store.visibleEdges.map((e) => e.kind)).toEqual(['nav', 'past'])
    expect(store.conceptNodes).toEqual([])
    await store.setConcepts(true)
    expect(store.conceptNodes.map((c) => c.label)).toEqual(['python'])
    expect(store.conceptEdges).toHaveLength(2)
    store.toggleSession(2)
    expect(store.visibleEdges.map((e) => e.kind)).toEqual(['nav'])
    expect(store.conceptEdges).toHaveLength(1)
  })

  it('表示範囲の外の点を選んでも、ID から調べ物を割り出して今回と過去を取りに行く', async () => {
    const store = useTadoriStore()
    await store.init()
    calls = []
    await store.select('s9-p1')
    expect(calls).toEqual(['/api/nodes/s9-p1', '/api/sessions/9/tangle'])
    expect(store.tangle?.session.id).toBe(9)
    expect(sessionIdOf('s12-p34')).toBe(12)
    expect(sessionIdOf('c5')).toBeUndefined()
  })

  it('調べ物の名前を手で直すと、上の帯と今回と過去の名前も変わる。空欄なら自動の名前', async () => {
    const store = useTadoriStore()
    await store.init()
    await store.select('s1-p1')
    await store.renameSession(1, 'OCR')
    expect(calls.at(-1)).toBe('PATCH /api/sessions/1')
    expect(store.sessionById.get(1)?.name).toBe('OCR')
    expect(store.tangle?.session.name).toBe('OCR')
    await store.renameSession(1, '')
    expect(store.sessionById.get(1)?.name).toBe('自動の名前')
  })

  it('取り込みボタンで取り込み、状態とグラフを読み直す', async () => {
    const store = useTadoriStore()
    await store.init()
    calls = []
    await store.select('s1-p1')
    calls = []
    await store.runImport([new File(['x'], 'History'), new File([''], 'History-wal')])
    expect(calls).toEqual(['POST /api/import', '/api/status', '/api/graph'])
    expect(store.notice).toBe('3 件の訪問を取り込みました')
    expect(store.importing).toBe(false)
    // 選び直した履歴では点の ID が変わりうるので、選択を外す
    expect(store.selectedNodeId).toBeNull()
    // ファイルを選ばなかったときは何もしない
    calls = []
    await store.runImport([])
    expect(calls).toEqual([])
  })

  it('本文の取得のあと、グラフと詳細を読み直す', async () => {
    const store = useTadoriStore()
    await store.init()
    await store.select('s1-p1')
    calls = []
    expect(await store.fetchBody(1)).toBe('本文から 2 個の言葉を取りました')
    expect(calls).toEqual(['POST /api/pages/1/fetch', '/api/graph', '/api/nodes/s1-p1'])
    expect(store.fetchingBody).toBe(false)
    // 失敗したときは理由を返す
    expect(await store.fetchBody(99)).toBe('x')
  })
})
