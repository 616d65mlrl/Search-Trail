// 点が多いときだけ、配置計算を Web Worker に任せる（04 アルゴリズム「画面側の計算」）
// それ以下はその場で計算する（Worker の起動とデータの受け渡しのほうが時間がかかるため）。

import { toRaw } from 'vue'
import type { GraphEdge, GraphNode, GraphSession } from '../api/types'
import { computeLayout, type Point } from './layout'

export const WORKER_THRESHOLD = 500

export interface LayoutRequest {
  id: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  sessions: Pick<GraphSession, 'id' | 'started_at'>[]
  concepts: { id: string }[]
}

export interface LayoutResponse {
  id: number
  positions: [string, Point][]
}

interface WorkerLike {
  postMessage(message: LayoutRequest): void
  onmessage: ((ev: MessageEvent<LayoutResponse>) => void) | null
}

export type WorkerFactory = () => WorkerLike

const defaultFactory: WorkerFactory = () =>
  new Worker(new URL('./layout.worker.ts', import.meta.url), { type: 'module' }) as unknown as WorkerLike

let worker: WorkerLike | null = null
let nextId = 0
const pending = new Map<number, (positions: Map<string, Point>) => void>()

// Pinia の状態は Proxy（変化を見張る包み）なので、Worker へ送る前に素のオブジェクトに戻す
const plain = <T extends object>(items: T[]): T[] => items.map((x) => ({ ...toRaw(x) }))

export function layoutAsync(
  nodes: GraphNode[],
  edges: GraphEdge[],
  sessions: Pick<GraphSession, 'id' | 'started_at'>[],
  concepts: { id: string }[] = [],
  createWorker: WorkerFactory = defaultFactory,
): Promise<Map<string, Point>> {
  const canUseWorker = createWorker !== defaultFactory || typeof Worker !== 'undefined'
  if (nodes.length + concepts.length <= WORKER_THRESHOLD || !canUseWorker) {
    return Promise.resolve(computeLayout(nodes, edges, sessions, concepts))
  }
  if (worker === null) {
    worker = createWorker()
    worker.onmessage = (ev) => {
      const resolve = pending.get(ev.data.id)
      pending.delete(ev.data.id)
      resolve?.(new Map(ev.data.positions))
    }
  }
  const id = ++nextId
  return new Promise((resolve) => {
    pending.set(id, resolve)
    worker!.postMessage({
      id,
      nodes: plain(nodes),
      edges: plain(edges),
      sessions: plain(sessions).map(({ id, started_at }) => ({ id, started_at })),
      concepts: plain(concepts).map(({ id }) => ({ id })),
    })
  })
}

// テスト用: 使い回している Worker を捨てる
export function resetLayoutWorker() {
  worker = null
  pending.clear()
}
