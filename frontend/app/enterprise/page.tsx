'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  Loader2,
  MailCheck,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react'
import { Logo } from '@/components/logo'
import { ThemeToggle } from '@/components/theme-toggle'
import { useAuth, type MfaStep } from '@/lib/auth'
import {
  authApi,
  SERVER_WAKING_EVENT,
  type ApiError,
  type MfaLoginResponse,
} from '@/lib/api'

const GOOGLE_CLIENT_ID = (process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '').trim()

const COMMON_PASSWORDS = new Set([
  'password',
  'password123',
  'password1234',
  '1234567890',
  '12345678901',
  'qwerty12345',
  'qwertyuiop',
  'admin12345',
  'welcome123',
  'letmein123',
  'deskwise123',
])

export function safeNextPath(raw: string | null): string {
  if (!raw) return '/workspace'
  const trimmed = raw.trim()
  if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.startsWith('/\\')) {
    return '/workspace'
  }
  return trimmed
}

type AuthLang = 'en' | 'ur'

const COPY: Record<AuthLang, Record<string, string>> = {
  en: {
    signInTab: 'Sign in',
    createTab: 'Create a company',
    joinTab: 'Join a company',
    welcomeBack: 'Welcome back.',
    startOrg: 'Start your organization.',
    joinOrg: 'Join your team.',
    onboardTitle: 'Finish setting up your workspace.',
    signInSub: 'Sign in with your work email or Google account.',
    createSub: 'Create a private company workspace and become its admin.',
    joinSub: 'Join an existing workspace with a company join code or admin invite link.',
    onboardSub: 'Your Google account is verified. Create a new company or enter a team join code to continue.',
    fullName: 'Full name',
    companyName: 'Company name',
    workEmail: 'Work email',
    password: 'Password',
    joinCode: 'Company join code (8 characters)',
    signInBtn: 'Sign in',
    createBtn: 'Create company',
    joinBtn: 'Join company',
    forgotPassword: 'Forgot password?',
    resendVerify: 'Resend verification email',
    wakingUp: 'Server is waking up, retrying automatically…',
  },
  ur: {
    signInTab: 'Sign in karein',
    createTab: 'Company banayein',
    joinTab: 'Company join karein',
    welcomeBack: 'Khush aamdeed.',
    startOrg: 'Apni organization shuru karein.',
    joinOrg: 'Apni team join karein.',
    onboardTitle: 'Apna workspace mukammal karein.',
    signInSub: 'Apne work email ya Google account se sign in karein.',
    createSub: 'Apni company ka private workspace banayein aur admin banein.',
    joinSub: 'Company join code ya admin invite link se workspace join karein.',
    onboardSub: 'Aapka Google email verify ho chuka hai. Nayi company banayein ya join code darj karein.',
    fullName: 'Poora naam',
    companyName: 'Company ka naam',
    workEmail: 'Work email',
    password: 'Password',
    joinCode: 'Company join code (8 huroof)',
    signInBtn: 'Sign in karein',
    createBtn: 'Company banayein',
    joinBtn: 'Company join karein',
    forgotPassword: 'Password bhool gaye?',
    resendVerify: 'Verification email dobara bhejein',
    wakingUp: 'Server jaag raha hai, dobara koshish ho rahi hai…',
  },
}

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (cfg: {
            client_id: string
            callback: (resp: { credential?: string }) => void
            ux_mode?: 'popup'
          }) => void
          renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void
        }
      }
    }
  }
}

function PasswordChecklist({ password, email }: { password: string; email?: string }) {
  const lenOk = password.length >= 10
  const lower = password.toLowerCase()
  const emailLocal = (email || '').split('@')[0]?.toLowerCase() || ''
  const notCommon =
    password.length > 0 &&
    !COMMON_PASSWORDS.has(lower) &&
    !/^\d+$/.test(password) &&
    (!emailLocal || emailLocal.length < 3 || !lower.includes(emailLocal))

  return (
    <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground" aria-live="polite">
      <li className={`flex items-center gap-1.5 ${lenOk ? 'text-ok' : ''}`}>
        {lenOk ? <Check className="size-3 shrink-0" /> : <X className="size-3 shrink-0 opacity-60" />}
        At least 10 characters
      </li>
      <li className={`flex items-center gap-1.5 ${notCommon ? 'text-ok' : ''}`}>
        {notCommon ? <Check className="size-3 shrink-0" /> : <X className="size-3 shrink-0 opacity-60" />}
        Not a common, numeric-only, or email-matching password
      </li>
    </ul>
  )
}

function EnterpriseInner() {
  const router = useRouter()
  const params = useSearchParams()
  const {
    user,
    needsOnboarding,
    enterpriseLogin,
    enterpriseRegister,
    joinCompany,
    googleLogin,
    onboardCompany,
    completeMfa,
  } = useAuth()

  const inviteParam = (params.get('invite') || '').trim()
  const emailParam = (params.get('email') || '').trim()
  const rawTab = params.get('tab')

  const [tab, setTab] = useState<'signin' | 'create' | 'join' | 'onboard'>(
    rawTab === 'onboard'
      ? 'onboard'
      : rawTab === 'join' || inviteParam
        ? 'join'
        : rawTab === 'create'
          ? 'create'
          : 'signin',
  )
  const [lang, setLang] = useState<AuthLang>('en')
  const c = COPY[lang]

  const [busy, setBusy] = useState(false)
  const [serverWaking, setServerWaking] = useState(false)
  const [error, setError] = useState('')
  const [errorCode, setErrorCode] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({})
  const [verifyNotice, setVerifyNotice] = useState(
    params.get('reset') === 'done' ? 'Password updated. You can sign in with your new password.' : '',
  )
  const [expiredNotice, setExpiredNotice] = useState(params.get('expired') === '1')
  const [unverifiedEmail, setUnverifiedEmail] = useState('')
  const [resendCooldown, setResendCooldown] = useState(0)
  const [rateLimitCountdown, setRateLimitCountdown] = useState(0)

  const [showSignInPassword, setShowSignInPassword] = useState(false)
  const [showCreatePassword, setShowCreatePassword] = useState(false)
  const [showJoinPassword, setShowJoinPassword] = useState(false)
  const [createPassword, setCreatePassword] = useState('')
  const [createEmail, setCreateEmail] = useState('')
  const [joinPassword, setJoinPassword] = useState('')
  const [joinEmail, setJoinEmail] = useState(emailParam)
  const [onboardMode, setOnboardMode] = useState<'create' | 'join'>('create')
  const [mfa, setMfa] = useState<MfaStep | null>(null)

  const googleBtnRef = useRef<HTMLDivElement>(null)
  const next = safeNextPath(params.get('next'))

  useEffect(() => {
    if (needsOnboarding && tab !== 'onboard') {
      setTab('onboard')
    }
  }, [needsOnboarding, tab])

  useEffect(() => {
    const onWaking = (e: Event) => {
      const detail = (e as CustomEvent<{ waking?: boolean }>).detail
      setServerWaking(Boolean(detail?.waking))
    }
    window.addEventListener(SERVER_WAKING_EVENT, onWaking)
    return () => window.removeEventListener(SERVER_WAKING_EVENT, onWaking)
  }, [])

  useEffect(() => {
    if (resendCooldown <= 0 && rateLimitCountdown <= 0) return
    const timer = setInterval(() => {
      setResendCooldown((v) => (v > 0 ? v - 1 : 0))
      setRateLimitCountdown((v) => (v > 0 ? v - 1 : 0))
    }, 1000)
    return () => clearInterval(timer)
  }, [resendCooldown, rateLimitCountdown])

  const applyError = useCallback((err: unknown, attemptedEmail = '') => {
    const apiErr = err as ApiError
    const msg = apiErr instanceof Error ? apiErr.message : 'Something went wrong.'
    setError(msg)
    setErrorCode(apiErr?.code || (apiErr?.status === 409 ? 'email_exists' : ''))
    setFieldErrors(apiErr?.fields || {})
    if (apiErr?.code === 'email_unverified' && attemptedEmail) {
      setUnverifiedEmail(attemptedEmail)
    }
    if (apiErr?.status === 429 && apiErr?.retryAfter) {
      setRateLimitCountdown(apiErr.retryAfter)
    }
  }, [])

  // Google Identity Services initialization
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) {
      if (process.env.NODE_ENV !== 'production') {
        console.warn('[Deskwise Auth] NEXT_PUBLIC_GOOGLE_CLIENT_ID is not set; hiding Continue with Google button.')
      }
      return
    }
    if (tab === 'onboard' || mfa) return

    let cancelled = false
    const initGoogle = () => {
      if (cancelled || !window.google?.accounts?.id || !googleBtnRef.current) return
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        ux_mode: 'popup',
        callback: async (response: { credential?: string }) => {
          if (!response?.credential) {
            setError('Google sign-in was cancelled or did not return a credential.')
            return
          }
          setError('')
          setErrorCode('')
          setBusy(true)
          try {
            const res = await googleLogin(response.credential)
            if (res.onboarding_required) {
              setTab('onboard')
            } else {
              router.push(next)
            }
          } catch (err) {
            const mfaStep = (err as { mfa?: MfaLoginResponse }).mfa
            if (mfaStep) {
              setMfa({
                kind: mfaStep.enrollment ? 'activate' : 'verify',
                challenge: mfaStep.challenge,
                enrollment: mfaStep.enrollment,
              })
            } else {
              applyError(err)
            }
          } finally {
            setBusy(false)
          }
        },
      })
      googleBtnRef.current.innerHTML = ''
      window.google.accounts.id.renderButton(googleBtnRef.current, {
        theme: 'outline',
        size: 'large',
        width: 360,
        text: tab === 'signin' ? 'continue_with' : 'signup_with',
        shape: 'pill',
      })
    }

    const existing = document.getElementById('google-gsi-script') as HTMLScriptElement | null
    if (existing) {
      if (window.google?.accounts?.id) initGoogle()
      else existing.addEventListener('load', initGoogle)
      return () => {
        cancelled = true
        existing.removeEventListener('load', initGoogle)
      }
    }

    const script = document.createElement('script')
    script.id = 'google-gsi-script'
    script.src = 'https://accounts.google.com/gsi/client'
    script.async = true
    script.defer = true
    script.onload = initGoogle
    script.onerror = () => {
      if (!cancelled) setError('Could not load Google Sign-In. Check your network or ad-blocker.')
    }
    document.head.appendChild(script)
    return () => {
      cancelled = true
    }
  }, [tab, mfa, googleLogin, router, next, applyError])

  async function onResendVerification(targetEmail: string) {
    if (!targetEmail || resendCooldown > 0) return
    setError('')
    try {
      await authApi.requestVerification(targetEmail)
      setResendCooldown(60)
      setVerifyNotice(`Verification link sent to ${targetEmail}. Check your inbox and spam folder.`)
    } catch (err) {
      const apiErr = err as ApiError
      if (apiErr?.retryAfter) setResendCooldown(apiErr.retryAfter)
      applyError(err, targetEmail)
    }
  }

  async function onSignIn(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (busy || rateLimitCountdown > 0) return
    setError('')
    setErrorCode('')
    setFieldErrors({})
    setVerifyNotice('')
    setExpiredNotice(false)
    setBusy(true)
    const f = new FormData(e.currentTarget)
    const email = String(f.get('email') || '').trim()
    try {
      const loggedIn = await enterpriseLogin(email, String(f.get('password') || ''))
      if (!loggedIn.is_platform_admin && !loggedIn.company_id) {
        setTab('onboard')
      } else {
        router.push(next)
      }
    } catch (err) {
      const mfaStep = (err as { mfa?: MfaLoginResponse }).mfa
      if (mfaStep) {
        setMfa({
          kind: mfaStep.enrollment ? 'activate' : 'verify',
          challenge: mfaStep.challenge,
          enrollment: mfaStep.enrollment,
        })
        setError('')
      } else {
        applyError(err, email)
      }
    } finally {
      setBusy(false)
    }
  }

  async function onMfaCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!mfa || busy) return
    setError('')
    setBusy(true)
    try {
      await completeMfa(mfa, String(new FormData(e.currentTarget).get('code') || '').trim())
      router.push(next)
    } catch (err) {
      applyError(err)
    } finally {
      setBusy(false)
    }
  }

  async function onCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (busy || rateLimitCountdown > 0) return
    setError('')
    setErrorCode('')
    setFieldErrors({})
    setVerifyNotice('')
    setExpiredNotice(false)
    setBusy(true)
    const f = new FormData(e.currentTarget)
    const email = String(f.get('email') || '').trim()
    try {
      const res = await enterpriseRegister({
        admin_name: String(f.get('admin_name') || '').trim(),
        company_name: String(f.get('company_name') || '').trim(),
        email,
        password: String(f.get('password') || ''),
      })
      if (res.verification_required) {
        setUnverifiedEmail(email)
        setResendCooldown(60)
        setVerifyNotice(
          `Organization created! We sent a verification link to ${email}. Click the link in your email, then sign in below.`,
        )
        setTab('signin')
      } else {
        router.push(next)
      }
    } catch (err) {
      applyError(err, email)
    } finally {
      setBusy(false)
    }
  }

  async function onJoin(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (busy || rateLimitCountdown > 0) return
    setError('')
    setErrorCode('')
    setFieldErrors({})
    setVerifyNotice('')
    setExpiredNotice(false)
    setBusy(true)
    const f = new FormData(e.currentTarget)
    const email = String(f.get('email') || '').trim()
    try {
      const res = await joinCompany({
        access_code: String(f.get('access_code') || '').trim().toUpperCase(),
        invite_token: inviteParam || undefined,
        full_name: String(f.get('full_name') || '').trim(),
        email,
        password: String(f.get('password') || ''),
      })
      if (res.verification_required) {
        setUnverifiedEmail(email)
        setResendCooldown(60)
        setVerifyNotice(
          `Account created! We sent a verification link to ${email}. Verify your email, then sign in below.`,
        )
        setTab('signin')
      } else {
        router.push(next)
      }
    } catch (err) {
      applyError(err, email)
    } finally {
      setBusy(false)
    }
  }

  async function onOnboard(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (busy) return
    setError('')
    setErrorCode('')
    setBusy(true)
    const f = new FormData(e.currentTarget)
    try {
      await onboardCompany({
        action: onboardMode,
        company_name: onboardMode === 'create' ? String(f.get('company_name') || '').trim() : undefined,
        access_code: onboardMode === 'join' ? String(f.get('access_code') || '').trim().toUpperCase() : undefined,
        full_name: String(f.get('full_name') || '').trim() || undefined,
      })
      router.push(next)
    } catch (err) {
      applyError(err)
    } finally {
      setBusy(false)
    }
  }

  const labelClass = 'text-[10px] font-semibold uppercase tracking-[0.13em] text-muted-foreground'

  function tabClass(active: boolean) {
    return `relative pb-3 text-[12.5px] font-medium transition-colors after:absolute after:inset-x-0 after:-bottom-px after:h-px ${
      active
        ? 'text-foreground after:bg-accent'
        : 'text-muted-foreground after:bg-transparent hover:text-foreground'
    }`
  }

  return (
    <main className="min-h-screen bg-background">
      <div className="lg:grid lg:min-h-screen lg:grid-cols-[0.92fr_1.08fr]">
        {/* Brand / reassurance panel */}
        <aside className="relative overflow-hidden border-b border-white/[0.06] bg-[#1a1815] px-6 pb-10 pt-6 text-[#f3efe5] sm:px-10 lg:flex lg:min-h-screen lg:flex-col lg:border-b-0 lg:border-r lg:px-12 lg:py-10">
          <div aria-hidden className="dot-grid pointer-events-none absolute inset-0 opacity-[0.12]" />
          <div className="relative flex items-center justify-between">
            <Logo tone="inverse" />
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 text-[11px] text-[#f3efe5]/50 transition-colors hover:text-[#f3efe5]"
            >
              <ArrowLeft className="size-3" aria-hidden /> Back to site
            </Link>
          </div>

          <div className="relative mt-14 max-w-md lg:my-auto lg:mt-0">
            <p className="eyebrow text-[#d9a75f]">Deskwise for teams</p>
            <h1 className="display-lg mt-5">
              Knowledge works
              <br />
              <span className="serif text-[#d9a75f]">better together.</span>
            </h1>
            <p className="mt-5 max-w-sm text-[13px] leading-relaxed text-[#f3efe5]/55">
              Bring your organization&apos;s policies, contracts, and forms into one permission-locked workspace.
            </p>

            <ul className="mt-8 hidden flex-col gap-3 sm:flex">
              {[
                'Pre-retrieval RBAC by role, department, and clearance',
                'AI answers with exact document citations',
                'Tamper-evident, append-only audit trail',
              ].map((item) => (
                <li key={item} className="flex items-center gap-2.5 text-[11.5px] text-[#f3efe5]/65">
                  <Check className="size-3.5 shrink-0 text-[#d9a75f]" aria-hidden /> {item}
                </li>
              ))}
            </ul>
          </div>

          <div className="relative mt-12 hidden items-center gap-3 border-t border-white/10 pt-5 lg:flex">
            <ShieldCheck className="size-4 shrink-0 text-[#d9a75f]" aria-hidden />
            <p className="text-[10.5px] leading-relaxed text-[#f3efe5]/40">
              Tenant-isolated by design. No public library, no cross-company data access.
            </p>
          </div>
        </aside>

        {/* Access panel */}
        <section className="flex flex-col px-5 py-7 sm:px-8 lg:px-12 lg:py-12">
          <div className="mx-auto flex w-full max-w-[30rem] flex-1 flex-col">
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setLang((l) => (l === 'en' ? 'ur' : 'en'))}
                className="rounded-full border border-border px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
                title="Switch language (English / Roman Urdu)"
              >
                {lang === 'en' ? 'Roman Urdu' : 'English'}
              </button>
              <ThemeToggle />
            </div>

            <div className="my-auto">
              <div className="pt-6 lg:pt-0">
                <p className="eyebrow">Enterprise access</p>
                <h2 className="display-md mt-3">
                  {tab === 'onboard'
                    ? c.onboardTitle
                    : tab === 'create'
                      ? c.startOrg
                      : tab === 'join'
                        ? c.joinOrg
                        : c.welcomeBack}
                </h2>
                <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">
                  {tab === 'onboard'
                    ? c.onboardSub
                    : tab === 'create'
                      ? c.createSub
                      : tab === 'join'
                        ? c.joinSub
                        : c.signInSub}
                </p>
              </div>

              {tab !== 'onboard' && (
                <div
                  role="tablist"
                  aria-label="Enterprise access"
                  className="mt-6 flex gap-5 border-b border-border"
                >
                  <button
                    type="button"
                    role="tab"
                    id="tab-signin"
                    aria-selected={tab === 'signin'}
                    onClick={() => {
                      setTab('signin')
                      setError('')
                      setErrorCode('')
                    }}
                    className={tabClass(tab === 'signin')}
                  >
                    {c.signInTab}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="tab-create"
                    aria-selected={tab === 'create'}
                    onClick={() => {
                      setTab('create')
                      setError('')
                      setErrorCode('')
                    }}
                    className={tabClass(tab === 'create')}
                  >
                    {c.createTab}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="tab-join"
                    aria-selected={tab === 'join'}
                    onClick={() => {
                      setTab('join')
                      setError('')
                      setErrorCode('')
                    }}
                    className={tabClass(tab === 'join')}
                  >
                    {c.joinTab}
                  </button>
                </div>
              )}

              {/* Server cold-start banner */}
              {serverWaking && (
                <p
                  role="status"
                  className="mt-4 flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3.5 py-2.5 text-[12px] text-accent"
                >
                  <Loader2 className="size-3.5 animate-spin shrink-0" aria-hidden />
                  {c.wakingUp}
                </p>
              )}

              {/* Verification / Password reset success notice */}
              {!error && !mfa && verifyNotice && (
                <div
                  role="status"
                  className="mt-5 rounded-lg border border-ok/30 bg-ok-soft px-3.5 py-3 text-[12px] text-ok"
                >
                  <p className="flex items-center gap-2 font-medium">
                    <MailCheck className="size-4 shrink-0" aria-hidden />
                    {verifyNotice}
                  </p>
                  {unverifiedEmail && (
                    <button
                      type="button"
                      disabled={resendCooldown > 0}
                      onClick={() => onResendVerification(unverifiedEmail)}
                      className="mt-2 text-[11px] font-medium underline underline-offset-4 disabled:opacity-50"
                    >
                      {resendCooldown > 0
                        ? `Resend available in ${resendCooldown}s`
                        : c.resendVerify}
                    </button>
                  )}
                </div>
              )}

              {!error && !mfa && expiredNotice && (
                <p
                  role="status"
                  className="mt-5 rounded-lg border border-warn/30 bg-warn-soft px-3.5 py-2.5 text-[12px] text-warn"
                >
                  Session expired. Please sign in again.
                </p>
              )}

              {error && (
                <div
                  role="alert"
                  className="mt-5 rounded-lg border border-danger/25 bg-danger-soft px-3.5 py-3 text-[12px] text-danger"
                >
                  <p>{error}</p>
                  {rateLimitCountdown > 0 && (
                    <p className="mt-1 text-[11px] font-medium">
                      Please wait {rateLimitCountdown}s before trying again.
                    </p>
                  )}
                  {errorCode === 'email_unverified' && unverifiedEmail && (
                    <button
                      type="button"
                      disabled={resendCooldown > 0}
                      onClick={() => onResendVerification(unverifiedEmail)}
                      className="mt-2 inline-flex items-center gap-1.5 font-semibold underline underline-offset-4 disabled:opacity-50"
                    >
                      {resendCooldown > 0
                        ? `Resend available in ${resendCooldown}s`
                        : c.resendVerify}
                    </button>
                  )}
                  {errorCode === 'email_exists' && (
                    <div className="mt-2 flex flex-wrap gap-3 text-[11px] font-semibold">
                      <button
                        type="button"
                        onClick={() => {
                          setTab('signin')
                          setError('')
                        }}
                        className="underline underline-offset-4"
                      >
                        Go to Sign in
                      </button>
                      <Link href="/auth/forgot" className="underline underline-offset-4">
                        Reset password
                      </Link>
                    </div>
                  )}
                </div>
              )}

              {/* Continue with Google button (rendered whenever NEXT_PUBLIC_GOOGLE_CLIENT_ID is configured) */}
              {GOOGLE_CLIENT_ID && tab !== 'onboard' && !mfa && (
                <div className="mt-6">
                  <div ref={googleBtnRef} className="flex min-h-[42px] justify-center" />
                  <div className="relative my-4 flex items-center justify-center">
                    <div className="w-full border-t border-border" />
                    <span className="bg-background px-3 text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      or with work email
                    </span>
                    <div className="w-full border-t border-border" />
                  </div>
                </div>
              )}

              {/* Tab 1: Sign in / MFA */}
              {tab === 'signin' && mfa ? (
                <form
                  id="panel-mfa"
                  className="mt-6 flex flex-col gap-4"
                  onSubmit={onMfaCode}
                >
                  <p className="text-[13px] leading-relaxed text-muted-foreground">
                    Two-factor verification. Enter the 6-digit code from your authenticator app.
                  </p>
                  {mfa.enrollment ? (
                    <p className="rounded-lg border border-border bg-surface/65 p-3 font-mono text-[12px] break-all">
                      First-time setup — add this secret to your authenticator app, then confirm
                      the code below:<br />
                      <span className="text-accent">{mfa.enrollment.secret}</span>
                    </p>
                  ) : null}
                  <div>
                    <label htmlFor="mfa-code" className={labelClass}>
                      Authenticator code
                    </label>
                    <input
                      id="mfa-code"
                      name="code"
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      pattern="[0-9 ]*"
                      maxLength={7}
                      required
                      placeholder="000000"
                      autoFocus
                      className="field mt-1.5 text-center tracking-[0.4em]"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={busy}
                    className="btn btn-primary w-full disabled:opacity-60"
                  >
                    {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                    Verify &amp; sign in
                  </button>
                </form>
              ) : tab === 'signin' ? (
                <form
                  id="panel-signin"
                  role="tabpanel"
                  aria-labelledby="tab-signin"
                  className="mt-4 flex flex-col gap-4"
                  onSubmit={onSignIn}
                >
                  <div>
                    <label htmlFor="signin-email" className={labelClass}>
                      {c.workEmail}
                    </label>
                    <input
                      id="signin-email"
                      name="email"
                      type="email"
                      required
                      autoFocus
                      defaultValue={unverifiedEmail || emailParam}
                      placeholder="you@company.com"
                      autoComplete="email"
                      className="field mt-1.5"
                    />
                  </div>
                  <div>
                    <div className="flex items-center justify-between">
                      <label htmlFor="signin-password" className={labelClass}>
                        {c.password}
                      </label>
                      <Link
                        href="/auth/forgot"
                        className="text-[11px] text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {c.forgotPassword}
                      </Link>
                    </div>
                    <div className="relative mt-1.5">
                      <input
                        id="signin-password"
                        name="password"
                        type={showSignInPassword ? 'text' : 'password'}
                        required
                        placeholder="••••••••••"
                        autoComplete="current-password"
                        className="field pr-11"
                      />
                      <button
                        type="button"
                        onClick={() => setShowSignInPassword((v) => !v)}
                        aria-label={showSignInPassword ? 'Hide password' : 'Show password'}
                        className="absolute right-1.5 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground"
                      >
                        {showSignInPassword ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                      </button>
                    </div>
                  </div>
                  <button
                    type="submit"
                    disabled={busy || rateLimitCountdown > 0}
                    className="btn btn-primary mt-1 w-full disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                    {c.signInBtn} {!busy && <ArrowRight className="size-4" aria-hidden />}
                  </button>
                </form>
              ) : null}

              {/* Tab 2: Create a company (Owner signup — Path A) */}
              {tab === 'create' && (
                <form
                  id="panel-create"
                  role="tabpanel"
                  aria-labelledby="tab-create"
                  className="mt-4 flex flex-col gap-4"
                  onSubmit={onCreate}
                >
                  <div>
                    <label htmlFor="create-name" className={labelClass}>
                      {c.fullName}
                    </label>
                    <input
                      id="create-name"
                      name="admin_name"
                      type="text"
                      required
                      autoFocus
                      placeholder="Ada Lovelace"
                      autoComplete="name"
                      className="field mt-1.5"
                    />
                  </div>
                  <div>
                    <label htmlFor="create-company" className={labelClass}>
                      {c.companyName}
                    </label>
                    <input
                      id="create-company"
                      name="company_name"
                      type="text"
                      required
                      placeholder="Northstar Labs"
                      autoComplete="organization"
                      className="field mt-1.5"
                    />
                  </div>
                  <div>
                    <label htmlFor="create-email" className={labelClass}>
                      {c.workEmail}
                    </label>
                    <input
                      id="create-email"
                      name="email"
                      type="email"
                      required
                      value={createEmail}
                      onChange={(e) => setCreateEmail(e.target.value)}
                      placeholder="you@company.com"
                      autoComplete="email"
                      className="field mt-1.5"
                    />
                    {fieldErrors.email && (
                      <p className="mt-1 text-[11px] text-danger">{fieldErrors.email[0]}</p>
                    )}
                  </div>
                  <div>
                    <label htmlFor="create-password" className={labelClass}>
                      {c.password}
                    </label>
                    <div className="relative mt-1.5">
                      <input
                        id="create-password"
                        name="password"
                        type={showCreatePassword ? 'text' : 'password'}
                        required
                        minLength={10}
                        value={createPassword}
                        onChange={(e) => setCreatePassword(e.target.value)}
                        placeholder="At least 10 characters"
                        autoComplete="new-password"
                        className="field pr-11"
                      />
                      <button
                        type="button"
                        onClick={() => setShowCreatePassword((v) => !v)}
                        aria-label={showCreatePassword ? 'Hide password' : 'Show password'}
                        className="absolute right-1.5 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground"
                      >
                        {showCreatePassword ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                      </button>
                    </div>
                    <PasswordChecklist password={createPassword} email={createEmail} />
                  </div>
                  <button
                    type="submit"
                    disabled={busy || rateLimitCountdown > 0}
                    className="btn btn-primary mt-1 w-full disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                    {c.createBtn} {!busy && <ArrowRight className="size-4" aria-hidden />}
                  </button>
                </form>
              )}

              {/* Tab 3: Join a company (Employee signup — Path B) */}
              {tab === 'join' && (
                <form
                  id="panel-join"
                  role="tabpanel"
                  aria-labelledby="tab-join"
                  className="mt-4 flex flex-col gap-4"
                  onSubmit={onJoin}
                >
                  {inviteParam ? (
                    <p className="rounded-lg border border-accent/30 bg-accent/10 px-3.5 py-2.5 text-[12px] text-accent">
                      Invitation link detected. Confirm your email and choose a password to join your team.
                    </p>
                  ) : (
                    <div>
                      <label htmlFor="join-code" className={labelClass}>
                        {c.joinCode}
                      </label>
                      <input
                        id="join-code"
                        name="access_code"
                        type="text"
                        required
                        maxLength={8}
                        autoFocus
                        placeholder="e.g. 7K9P2M4Q"
                        className="field mt-1.5 font-mono uppercase tracking-widest"
                      />
                    </div>
                  )}
                  <div>
                    <label htmlFor="join-name" className={labelClass}>
                      {c.fullName}
                    </label>
                    <input
                      id="join-name"
                      name="full_name"
                      type="text"
                      required
                      placeholder="Ada Lovelace"
                      autoComplete="name"
                      className="field mt-1.5"
                    />
                  </div>
                  <div>
                    <label htmlFor="join-email" className={labelClass}>
                      {c.workEmail}
                    </label>
                    <input
                      id="join-email"
                      name="email"
                      type="email"
                      required
                      value={joinEmail}
                      onChange={(e) => setJoinEmail(e.target.value)}
                      placeholder="you@company.com"
                      autoComplete="email"
                      className="field mt-1.5"
                    />
                  </div>
                  <div>
                    <label htmlFor="join-password" className={labelClass}>
                      {c.password}
                    </label>
                    <div className="relative mt-1.5">
                      <input
                        id="join-password"
                        name="password"
                        type={showJoinPassword ? 'text' : 'password'}
                        required
                        minLength={10}
                        value={joinPassword}
                        onChange={(e) => setJoinPassword(e.target.value)}
                        placeholder="At least 10 characters"
                        autoComplete="new-password"
                        className="field pr-11"
                      />
                      <button
                        type="button"
                        onClick={() => setShowJoinPassword((v) => !v)}
                        aria-label={showJoinPassword ? 'Hide password' : 'Show password'}
                        className="absolute right-1.5 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground"
                      >
                        {showJoinPassword ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                      </button>
                    </div>
                    <PasswordChecklist password={joinPassword} email={joinEmail} />
                  </div>
                  <button
                    type="submit"
                    disabled={busy || rateLimitCountdown > 0}
                    className="btn btn-primary mt-1 w-full disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                    {c.joinBtn} {!busy && <ArrowRight className="size-4" aria-hidden />}
                  </button>
                </form>
              )}

              {/* Tab 4: Post-Google Onboarding (Create a company OR Enter join code) */}
              {tab === 'onboard' && (
                <form className="mt-6 flex flex-col gap-4" onSubmit={onOnboard}>
                  <div className="grid grid-cols-2 gap-2 rounded-xl border border-border bg-surface p-1">
                    <button
                      type="button"
                      onClick={() => setOnboardMode('create')}
                      className={`rounded-lg py-2 text-xs font-semibold transition-colors ${
                        onboardMode === 'create'
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      {c.createTab}
                    </button>
                    <button
                      type="button"
                      onClick={() => setOnboardMode('join')}
                      className={`rounded-lg py-2 text-xs font-semibold transition-colors ${
                        onboardMode === 'join'
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      {c.joinTab}
                    </button>
                  </div>

                  <div>
                    <label htmlFor="onboard-name" className={labelClass}>
                      {c.fullName}
                    </label>
                    <input
                      id="onboard-name"
                      name="full_name"
                      type="text"
                      defaultValue={user?.full_name || ''}
                      placeholder="Ada Lovelace"
                      autoComplete="name"
                      className="field mt-1.5"
                    />
                  </div>

                  {onboardMode === 'create' ? (
                    <div>
                      <label htmlFor="onboard-company" className={labelClass}>
                        {c.companyName}
                      </label>
                      <input
                        id="onboard-company"
                        name="company_name"
                        type="text"
                        required
                        autoFocus
                        placeholder="Northstar Labs"
                        className="field mt-1.5"
                      />
                    </div>
                  ) : (
                    <div>
                      <label htmlFor="onboard-code" className={labelClass}>
                        {c.joinCode}
                      </label>
                      <input
                        id="onboard-code"
                        name="access_code"
                        type="text"
                        required
                        maxLength={8}
                        autoFocus
                        placeholder="e.g. 7K9P2M4Q"
                        className="field mt-1.5 font-mono uppercase tracking-widest"
                      />
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={busy}
                    className="btn btn-primary mt-1 w-full disabled:opacity-60"
                  >
                    {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                    {onboardMode === 'create' ? c.createBtn : c.joinBtn}
                  </button>
                </form>
              )}

              <div className="mt-7 flex items-start gap-2 border-t border-border pt-4">
                <Sparkles className="mt-0.5 size-3 shrink-0 text-accent" aria-hidden />
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  By continuing you agree to the{' '}
                  <Link href="/policy" className="text-foreground underline underline-offset-4">
                    privacy and security model
                  </Link>
                  . Your workspace is isolated from every other organization.
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}

export default function EnterprisePage() {
  return (
    <Suspense
      fallback={
        <main className="grid min-h-screen place-items-center bg-background text-sm text-muted-foreground">
          <span className="inline-flex items-center gap-2">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Loading secure access…
          </span>
        </main>
      }
    >
      <EnterpriseInner />
    </Suspense>
  )
}
