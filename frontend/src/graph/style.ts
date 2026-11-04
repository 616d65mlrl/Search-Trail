// 点と線の見た目のルール（05 画面仕様「見た目のルール」）

// 調べ物ごとに、この順番で割り当てる（紫、水色、緑、赤紫、橙、赤）
export const SESSION_COLORS = ['#7C6CF2', '#2FB5D2', '#4CC66A', '#D157C9', '#EB8A3E', '#E04F6A'] as const

export function sessionColor(colorIndex: number): string {
  const n = SESSION_COLORS.length
  return SESSION_COLORS[((colorIndex % n) + n) % n]!
}

// 点の半径 = 4 + √訪問回数 × 2.6（px）
export function nodeRadius(visits: number): number {
  return 4 + Math.sqrt(Math.max(visits, 0)) * 2.6
}

// 点の数がこれを超えたら、段階2までは「期間を絞ってください」と案内する
export const MAX_SVG_NODES = 2000

const timeFormat = new Intl.DateTimeFormat('ja-JP', {
  timeZone: 'Asia/Tokyo',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

const dateFormat = new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' })

// 時刻は Unix ミリ秒（UTC）で受け取り、日本時間で表示する（03 データ設計）
export function formatTime(ms: number): string {
  return timeFormat.format(ms)
}

export function formatDate(ms: number): string {
  return dateFormat.format(ms)
}

export function formatDuration(ms: number): string {
  const minutes = Math.round(ms / 60000)
  if (minutes < 1) return '1分未満'
  if (minutes < 60) return `${minutes}分`
  return `${Math.floor(minutes / 60)}時間${minutes % 60}分`
}

// 来た元の決め方（parent_reason）を画面の言葉に直す
export const REASON_LABELS: Record<string, string> = {
  from_visit: 'リンク',
  opener: '新しいタブ',
  search: '推定（直前の検索）',
  time: '推定（直前の訪問）',
}

export function shortTitle(title: string | null, url: string, max = 24): string {
  const text = title || url
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}
