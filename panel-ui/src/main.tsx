import React from 'react'
import ReactDOM from 'react-dom/client'
// Self-hosted Inter (the app's typeface) — bundled, no external CDN call, so it
// renders reliably even in an air-gapped government deployment.
import '@fontsource/inter/300.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import { App } from './App'
import { loadPanelConfig } from './lib/config'
import './index.css'

// Fetch non-sensitive fleet config (base domain) before first paint so
// hostnames render correctly everywhere.
loadPanelConfig().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
})
