import { describe, expect, it } from 'vitest'
import type { GraphEdge } from '../src/api/types'
import { assignLanes, MAX_LANES, parentMap } from '../src/graph/lanes'

const node = (id: string, at: number, session_id = 1) => ({ id, session_id, first_visit_at: at })
const nav = (source: string, target: string): GraphEdge => ({ source, target, kind: 'nav', count: 1 })

describe('履歴ログのレーン', () => {
  it('最初の子は来た元と同じレーン、2番目以降の子は新しいレーン', () => {
    // A → B → C（B の最初の子）、B → D（2番目）、B → E（3番目）、D → F（D の最初の子）
    const nodes = [node('A', 0), node('B', 1), node('C', 2), node('D', 3), node('E', 4), node('F', 5)]
    const edges = [nav('A', 'B'), nav('B', 'C'), nav('B', 'D'), nav('B', 'E'), nav('D', 'F')]
    expect(Object.fromEntries(assignLanes(nodes, edges))).toEqual({ A: 0, B: 0, C: 0, D: 1, E: 2, F: 1 })
  })

  it('来た元のない点は最初のレーン', () => {
    const lanes = assignLanes([node('A', 0), node('B', 1)], [])
    expect([...lanes.values()]).toEqual([0, 0])
  })

  it('レーンは最大6本で、超えた分は最後のレーンにまとめる', () => {
    const children = Array.from({ length: 10 }, (_, i) => node(`c${i}`, i + 1))
    const lanes = assignLanes([node('root', 0), ...children], children.map((c) => nav('root', c.id)))
    expect(Math.max(...lanes.values())).toBe(MAX_LANES - 1)
    expect(lanes.get('c9')).toBe(MAX_LANES - 1)
  })

  it('調べ物ごとに新しいレーンを数え直す', () => {
    const nodes = [node('A', 0, 1), node('B', 1, 1), node('C', 2, 1), node('X', 3, 2), node('Y', 4, 2), node('Z', 5, 2)]
    const edges = [nav('A', 'B'), nav('A', 'C'), nav('X', 'Y'), nav('X', 'Z')]
    const lanes = assignLanes(nodes, edges)
    expect(lanes.get('C')).toBe(1)
    expect(lanes.get('Z')).toBe(1)
  })

  it('来た元が複数あるときは、行き先より前に開いた中で一番新しいもの', () => {
    const nodes = [node('A', 0), node('B', 5), node('T', 10), node('L', 20)]
    const parents = parentMap(nodes, [nav('A', 'T'), nav('B', 'T'), nav('L', 'T')])
    expect(parents.get('T')).toBe('B')
  })
})
