import { useEffect, useState } from 'react'
import { Landmark, Building2, KeyRound, Info } from 'lucide-react'
import { api } from '../lib/api'
import type { KeyCatalog } from '../lib/types'
import { Card, Spinner } from '../components/ui'
import { PageHeader } from '../components/Shell'
import { useToast } from '../components/Toast'

import { getBaseDomain } from '../lib/config'

/**
 * Settings surfaces the fleet-wide defaults and the key catalog. The base
 * domain and panel crypto are process env on the control plane (shown here
 * read-only); the default owner per service comes from the catalog and is the
 * starting point for every new town's matrix.
 */
export function Settings() {
  const BASE_DOMAIN = getBaseDomain()
  const toast = useToast()
  const [catalog, setCatalog] = useState<KeyCatalog | null>(null)

  useEffect(() => {
    api
      .keyCatalog()
      .then(setCatalog)
      .catch((e) => toast.push((e as Error).message, 'error'))
  }, [])

  return (
    <div>
      <PageHeader title="Settings" subtitle="Fleet-wide configuration and defaults." />

      <div className="space-y-4">
        <Card>
          <h3 className="font-semibold text-white mb-4">Fleet identity</h3>
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-white/40 uppercase tracking-wide mb-1">Base domain</div>
              <div className="text-white font-mono">{BASE_DOMAIN}</div>
              <p className="text-xs text-white/40 mt-1">Towns live at <code>&lt;slug&gt;.{BASE_DOMAIN}</code> via wildcard TLS.</p>
            </div>
            <div>
              <div className="text-xs text-white/40 uppercase tracking-wide mb-1">Deployment mode</div>
              <div className="text-white">Compose per town (MVP)</div>
              <p className="text-xs text-white/40 mt-1">Graduates to Kubernetes/GitOps behind the same API.</p>
            </div>
          </div>
          <div className="flex items-start gap-2 mt-4 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
            <Info className="w-4 h-4 text-blue-300 shrink-0 mt-0.5" />
            <p className="text-xs text-blue-100/70">
              Base domain, panel token, and encryption key are set as environment variables on the
              control plane (<code>BASE_DOMAIN</code>, <code>PANEL_API_TOKEN</code>, <code>PANEL_SECRET_KEY</code>) and
              are intentionally not editable from the browser.
            </p>
          </div>
        </Card>

        {!catalog ? (
          <Spinner />
        ) : (
          <Card>
            <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
              <KeyRound className="w-5 h-5" /> Default key responsibility
            </h3>
            <p className="text-sm text-white/50 mb-4">
              The starting point for each new municipality's matrix. Flip any of these per town when
              you add or edit it.
            </p>
            <div className="space-y-2">
              {catalog.assignable.map((s) => (
                <div key={s.id} className="flex items-center justify-between py-2 border-b border-white/5">
                  <div>
                    <div className="text-white font-medium">{s.label}</div>
                    <code className="text-[11px] text-white/40">{s.keys.join(', ')}</code>
                  </div>
                  {s.default_owner === 'state' ? (
                    <span className="inline-flex items-center gap-1.5 text-sm text-indigo-200">
                      <Landmark className="w-4 h-4" /> State provides
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-sm text-white/60">
                      <Building2 className="w-4 h-4" /> Town provides
                    </span>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}
