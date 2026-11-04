import type { ApiErrorBody, BodyResult, GraphResponse, ImportResult, NodeDetail, Session, Status, TangleResponse } from './types'

// 開発中は Vite が /api を 127.0.0.1:8765 の FastAPI へ中継する（vite.config.ts）
const BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

async function request<T>(method: string, path: string, params: Params = {}, body?: unknown): Promise<T> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') query.set(key, String(value))
  }
  const qs = query.toString()
  // FormData（ファイルの送信）は、ブラウザに形式（multipart）を決めさせる
  const init: RequestInit | undefined =
    method === 'GET'
      ? undefined
      : body instanceof FormData
        ? { method, body }
        : { method, headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
  const res = await fetch(`${BASE}${path}${qs ? `?${qs}` : ''}`, init)
  if (!res.ok) {
    let code = 'http_error'
    let message = `${res.status} ${res.statusText}`
    try {
      const err = (await res.json()) as ApiErrorBody
      code = err.error.code
      message = err.error.message
    } catch {
      // エラーの形でない返事は、状態コードだけを伝える
    }
    throw new ApiError(res.status, code, message)
  }
  return (await res.json()) as T
}

const get = <T>(path: string, params?: Params) => request<T>('GET', path, params)

export const api = {
  status: () => get<Status>('/status'),
  sessions: (from?: number | null, to?: number | null) => get<Session[]>('/sessions', { from, to }),
  graph: (opts: { from?: number | null; to?: number | null; sessions?: number[]; concepts?: boolean } = {}) =>
    get<GraphResponse>('/graph', {
      from: opts.from,
      to: opts.to,
      sessions: opts.sessions?.join(','),
      concepts: opts.concepts || undefined,
    }),
  node: (id: string) => get<NodeDetail>(`/nodes/${encodeURIComponent(id)}`),
  tangle: (sessionId: number) => get<TangleResponse>(`/sessions/${sessionId}/tangle`),
  // 空欄を送ると自動の名前に戻る（FR-12）
  renameSession: (sessionId: number, name: string) => request<Session>('PATCH', `/sessions/${sessionId}`, {}, { name }),
  // 選んだ History（と History-wal）の中身を送る。ファイルの場所（パス）はブラウザが送らないので、サーバーにも残らない
  runImport: (files: File[]) => {
    const form = new FormData()
    for (const f of files) form.append('files', f, f.name)
    return request<ImportResult>('POST', '/import', {}, form)
  },
  // ページの本文を取得して概念を足す（FR-14）。PC の外へ通信するので、画面で確認してから呼ぶ
  fetchBody: (pageId: number) => request<BodyResult>('POST', `/pages/${pageId}/fetch`),
}
