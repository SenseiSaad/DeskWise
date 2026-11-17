'use client'

import React, { createContext, useContext, useState, useEffect } from 'react'
import { AlertCircle, CheckCircle2 } from 'lucide-react'

type Toast = { id: number; message: string; type: 'success' | 'error' }

const ToastContext = createContext<any>(null)

let addToastObj: (t: Omit<Toast, 'id'>) => void = () => {}
let nextToastId = 0

export const toast = {
  success: (msg: string) => addToastObj({ message: msg, type: 'success' }),
  error: (msg: string) => addToastObj({ message: msg, type: 'error' })
}

export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([])

  useEffect(() => {
    addToastObj = (t) => {
      const id = ++nextToastId
      setToasts((prev) => [...prev, { ...t, id }])
      setTimeout(() => {
        setToasts((prev) => prev.filter((x) => x.id !== id))
      }, 4000)
    }
  }, [])

  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`animate-[fade-in-up_0.2s_ease-out] flex items-center gap-2 rounded-xl px-4 py-3 text-sm shadow-xl ${
            t.type === 'success'
              ? 'bg-ok-soft text-ok border border-ok/30'
              : 'bg-danger-soft text-danger border border-danger/30'
          }`}
        >
          {t.type === 'success' ? <CheckCircle2 className="size-4" /> : <AlertCircle className="size-4" />}
          {t.message}
        </div>
      ))}
    </div>
  )
}
