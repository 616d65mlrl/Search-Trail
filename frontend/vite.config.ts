/// <reference types="vitest/config" />
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 履歴は個人情報なので、開発サーバーも自分の PC からだけ開けるようにする（NFR-02）
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    // /api への通信は、FastAPI のサーバー（06 API 仕様のポート 8765）へ中継する
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
  },
})
