import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    // changeOrigin: false сохраняет Host браузера: Python-сервер сверяет его
    // с Origin и отклоняет изменяющие запросы с чужих сайтов.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false },
      '/result': { target: 'http://127.0.0.1:8765', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
