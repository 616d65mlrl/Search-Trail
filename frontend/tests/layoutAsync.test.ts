import { afterEach, describe, expect, it } from 'vitest'
import type { GraphNode } from '../src/api/types'
import { computeLayout } from '../src/graph/layout'
import { layoutAsync, resetLayoutWorker, WORKER_THRESHOLD, type LayoutRequest, type LayoutResponse } from '../src/graph/layoutAsync'

function nodes(count: number): GraphNode[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `s1-p${i}`, session_id: 1, page_id: i, title: `${i}`, domain: 'example.com', url: `https://example.com/${i}`,
    visits: 1, first_visit_at: i, branch_count: 0, past_count: 0,
  }))
}
const sessions = [{ id: 1, started_at: 0 }]

// 本物の Worker の代わりに、同じ計算をして非同期に返す偽物
function fakeWorkerFactory(log: LayoutRequest[]) {
  return () => {
    const fake = {
      onmessage: null as ((ev: MessageEvent<LayoutResponse>) => void) | null,
      postMessage(req: LayoutRequest) {
        log.push(req)
        const positions = [...computeLayout(req.nodes, req.edges, req.sessions, req.concepts).entries()]
        setTimeout(() => fake.onmessage?.({ data: { id: req.id, positions } } as MessageEvent<LayoutResponse>), 0)
      },
    }
    return fake
  }
}

afterEach(() => resetLayoutWorker())

describe('配置計算の振り分け', () => {
  it('点が少ないときは Worker を使わずにその場で計算する', async () => {
    const log: LayoutRequest[] = []
    const small = nodes(10)
    const result = await layoutAsync(small, [], sessions, [], fakeWorkerFactory(log))
    expect(log).toHaveLength(0)
    expect(result).toEqual(computeLayout(small, [], sessions))
  })

  it('点が多いときは Worker で計算し、結果はその場で計算したものと同じ', async () => {
    const log: LayoutRequest[] = []
    const large = nodes(WORKER_THRESHOLD + 1)
    const result = await layoutAsync(large, [], sessions, [], fakeWorkerFactory(log))
    expect(log).toHaveLength(1)
    expect(result.size).toBe(large.length)
    expect(result).toEqual(computeLayout(large, [], sessions))
  })

  it('続けて頼んでも、それぞれの頼みに正しい結果が返る', async () => {
    const log: LayoutRequest[] = []
    const factory = fakeWorkerFactory(log)
    const a = nodes(WORKER_THRESHOLD + 1)
    const b = nodes(WORKER_THRESHOLD + 2)
    const [ra, rb] = await Promise.all([layoutAsync(a, [], sessions, [], factory), layoutAsync(b, [], sessions, [], factory)])
    expect(ra.size).toBe(a.length)
    expect(rb.size).toBe(b.length)
  })
})
