import { useEffect, useState } from 'react'
import { Terminal } from 'lucide-react'
import { api } from '../../lib/api'
import type { KeyCatalog, SecretOut } from '../../lib/types'
import { Spinner } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { useSession } from '../../lib/session'
import { ApiKeysHub, SsoFederation } from '../Settings'

export function Integration() {
  const toast = useToast()
  const { can } = useSession()
  const [catalog, setCatalog] = useState<KeyCatalog | null>(null)
  const [creds, setCreds] = useState<SecretOut[]>([])

  async function loadCreds() {
    setCreds(await api.listStateCredentials())
  }
  useEffect(() => {
    Promise.all([api.keyCatalog(), api.listStateCredentials()])
      .then(([c, s]) => { setCatalog(c); setCreds(s) })
      .catch((e) => toast.push((e as Error).message, 'error'))
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2">
          <Terminal className="w-6 h-6" /> Setup &amp; Integration
        </h1>
        <p className="text-white/50 text-sm mt-1">
          Single sign-on and the shared API credentials this platform provides to the fleet.
        </p>
      </div>

      {can('admin') && <SsoFederation />}
      {!catalog ? <Spinner /> : <ApiKeysHub catalog={catalog} creds={creds} onChange={loadCreds} />}
    </div>
  )
}
