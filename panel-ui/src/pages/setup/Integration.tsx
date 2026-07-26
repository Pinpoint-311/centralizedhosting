import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import type { KeyCatalog, SecretOut } from '../../lib/types'
import { Spinner } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { useSession } from '../../lib/session'
import { ApiKeysHub, SsoFederation, SsoSidecar } from '../Settings'

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
    <div className="space-y-4">
      {can('admin') && <SsoFederation />}
      {can('admin') && <SsoSidecar />}
      {!catalog ? <Spinner /> : <ApiKeysHub catalog={catalog} creds={creds} onChange={loadCreds} />}
    </div>
  )
}
