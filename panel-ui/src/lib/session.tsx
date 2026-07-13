import React, { createContext, useContext, useEffect, useState } from 'react'
import { api } from './api'
import type { Role, WhoAmI } from './types'

const RANK: Record<Role, number> = { viewer: 0, operator: 1, approver: 2, admin: 3 }

interface SessionValue {
  who: WhoAmI | null
  can: (min: Role) => boolean
}

const Ctx = createContext<SessionValue>({ who: null, can: () => true })

export function useSession() {
  return useContext(Ctx)
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [who, setWho] = useState<WhoAmI | null>(null)
  useEffect(() => {
    api.whoami().then(setWho).catch(() => setWho(null))
  }, [])
  const can = (min: Role) => (who ? RANK[who.role] >= RANK[min] : true)
  return <Ctx.Provider value={{ who, can }}>{children}</Ctx.Provider>
}

// ---- theme ------------------------------------------------------------------

const THEME_KEY = 'pp311_theme'
type Theme = 'dark' | 'light'

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(() => {
    const saved = localStorage.getItem(THEME_KEY) as Theme | null
    if (saved) return saved
    return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  })
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])
  const setTheme = (t: Theme) => {
    localStorage.setItem(THEME_KEY, t)
    setThemeState(t)
  }
  return [theme, setTheme]
}
