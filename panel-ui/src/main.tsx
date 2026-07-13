import React from 'react'
import ReactDOM from 'react-dom/client'
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
