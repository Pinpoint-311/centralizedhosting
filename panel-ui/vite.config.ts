import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

// Build straight into the FastAPI static dir so `orchestrator.main` serves the
// SPA at / with no extra copy step.
const outDir = fileURLToPath(new URL('../orchestrator/static', import.meta.url))

export default defineConfig({
  plugins: [react()],
  build: {
    outDir,
    emptyOutDir: false, // keep dashboard.html fallback alongside the SPA
  },
  server: {
    port: 5273,
    proxy: {
      '/api': 'http://127.0.0.1:8100',
      '/healthz': 'http://127.0.0.1:8100',
    },
  },
})
