// 配置計算を、画面とは別のスレッド（Web Worker）で行う（04 アルゴリズム「画面側の計算」）
import { computeLayout } from './layout'
import type { LayoutRequest, LayoutResponse } from './layoutAsync'

self.onmessage = (ev: MessageEvent<LayoutRequest>) => {
  const { id, nodes, edges, sessions, concepts } = ev.data
  const positions = [...computeLayout(nodes, edges, sessions, concepts).entries()]
  const response: LayoutResponse = { id, positions }
  self.postMessage(response)
}
