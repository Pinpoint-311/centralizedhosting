import React, { createContext, useCallback, useContext, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle, AlertCircle, X } from 'lucide-react'

interface Toast {
  id: number
  message: string
  kind: 'success' | 'error'
}

const ToastCtx = createContext<{ push: (m: string, k?: 'success' | 'error') => void }>({
  push: () => {},
})

export function useToast() {
  return useContext(ToastCtx)
}

let nextId = 1

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((message: string, kind: 'success' | 'error' = 'success') => {
    const id = nextId++
    setToasts((t) => [...t, { id, message, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 w-80">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, x: 40 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 40 }}
              className={`glass-card !p-3.5 flex items-start gap-3 border ${
                t.kind === 'success' ? 'border-green-500/30' : 'border-red-500/30'
              }`}
            >
              {t.kind === 'success' ? (
                <CheckCircle className="w-5 h-5 text-green-300 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="w-5 h-5 text-red-300 shrink-0 mt-0.5" />
              )}
              <p className="text-sm text-white/90 flex-1">{t.message}</p>
              <button
                onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}
                className="text-white/40 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  )
}
