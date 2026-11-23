'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState, type FormEvent } from 'react'
import { BadgeCheck, Loader2, MailCheck, MailWarning } from 'lucide-react'
import { AuthShell } from '@/components/auth-shell'
import { authApi, type ApiError } from '@/lib/api'

function VerifyInner() {
  const params = useSearchParams()
  const token = params.get('token') || ''
  const [state, setState] = useState<'loading' | 'ok' | 'error'>(token ? 'loading' : 'error')
  const [message, setMessage] = useState('No verification token in the link.')
  const [resendEmail, setResendEmail] = useState('')
  const [resending, setResending] = useState(false)
  const [resentMsg, setResentMsg] = useState('')
  const [cooldown, setCooldown] = useState(0)

  useEffect(() => {
    if (!token) return
    authApi
      .verifyEmail(token)
      .then((res) => {
        setState('ok')
        setMessage(res.detail)
      })
      .catch((err) => {
        setState('error')
        setMessage(err instanceof Error ? err.message : 'Verification failed.')
      })
  }, [token])

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setInterval(() => setCooldown((c) => (c > 0 ? c - 1 : 0)), 1000)
    return () => clearInterval(timer)
  }, [cooldown])

  async function onResend(e: FormEvent) {
    e.preventDefault()
    if (!resendEmail.trim() || resending || cooldown > 0) return
    setResending(true)
    setResentMsg('')
    try {
      const res = await authApi.requestVerification(resendEmail.trim())
      setResentMsg(res.detail)
      setCooldown(60)
    } catch (err) {
      const apiErr = err as ApiError
      if (apiErr?.retryAfter) setCooldown(apiErr.retryAfter)
      setMessage(apiErr instanceof Error ? apiErr.message : 'Could not resend verification link.')
    } finally {
      setResending(false)
    }
  }

  return state === 'loading' ? (
    <p className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden /> Verifying your email…
    </p>
  ) : state === 'ok' ? (
    <div className="text-center">
      <span className="mx-auto grid size-11 place-items-center rounded-full bg-ok-soft text-ok">
        <BadgeCheck className="size-5" aria-hidden />
      </span>
      <h1 className="mt-5 text-[1.35rem] font-medium tracking-[-0.03em]">Email verified</h1>
      <p className="mx-auto mt-2 max-w-xs text-[12.5px] leading-relaxed text-muted-foreground">
        {message}
      </p>
      <Link
        href="/enterprise"
        className="btn btn-primary mt-6 inline-flex items-center gap-2"
      >
        Sign in now
      </Link>
    </div>
  ) : (
    <div>
      <div className="text-center">
        <span className="mx-auto grid size-11 place-items-center rounded-full bg-danger-soft text-danger">
          <MailWarning className="size-5" aria-hidden />
        </span>
        <h1 className="mt-5 text-[1.35rem] font-medium tracking-[-0.03em]">Link invalid or expired</h1>
        <p className="mx-auto mt-2 max-w-xs text-[12.5px] leading-relaxed text-muted-foreground">
          {message}
        </p>
      </div>

      <form onSubmit={onResend} className="mt-6 space-y-3">
        <label
          htmlFor="verify-resend-email"
          className="block text-[10px] font-semibold uppercase tracking-[0.13em] text-muted-foreground"
        >
          Request a new verification link
        </label>
        <input
          id="verify-resend-email"
          type="email"
          required
          value={resendEmail}
          onChange={(e) => setResendEmail(e.target.value)}
          placeholder="you@company.com"
          autoComplete="email"
          className="field"
        />
        {resentMsg && (
          <p className="flex items-center gap-1.5 rounded-lg border border-ok/30 bg-ok-soft px-3 py-2 text-[12px] text-ok">
            <MailCheck className="size-4 shrink-0" aria-hidden /> {resentMsg}
          </p>
        )}
        <button
          type="submit"
          disabled={resending || cooldown > 0}
          className="btn btn-primary w-full disabled:opacity-60"
        >
          {resending && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {cooldown > 0 ? `Resend available in ${cooldown}s` : 'Send new verification link'}
        </button>
      </form>

      <div className="mt-5 text-center">
        <Link
          href="/enterprise"
          className="text-[12px] font-medium text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          Back to sign in
        </Link>
      </div>
    </div>
  )
}

export default function VerifyEmailPage() {
  return (
    <AuthShell>
      <Suspense fallback={<p className="py-6 text-center text-sm text-muted-foreground">Loading…</p>}>
        <VerifyInner />
      </Suspense>
    </AuthShell>
  )
}
