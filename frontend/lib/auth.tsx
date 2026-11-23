'use client'

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import {
  authApi, isMfaResponse, isUiLanguage, SESSION_EXPIRED_EVENT,
  type AuthResponse, type MfaLoginResponse, type User, type UiLanguage,
} from './api'

export interface MfaStep {
  kind: 'activate' | 'verify'
  challenge: string
  enrollment?: { secret: string; uri: string }
}

interface AuthContextValue {
  user: User | null
  loading: boolean // true while restoring the session on first load
  sessionExpired: boolean
  isEnterprise: boolean
  isPlatformAdmin: boolean
  needsOnboarding: boolean
  language: UiLanguage
  setLanguage: (lang: UiLanguage) => Promise<void>
  enterpriseLogin: (email: string, password: string) => Promise<User>
  enterpriseRegister: (p: {
    company_name: string
    admin_name?: string
    admin_title?: string
    website?: string
    contact_email?: string
    phone?: string
    max_employees?: number | null
    email: string
    password: string
  }) => Promise<AuthResponse>
  joinCompany: (p: {
    access_code?: string
    invite_token?: string
    full_name?: string
    email: string
    password: string
  }) => Promise<AuthResponse>
  googleLogin: (credential: string) => Promise<AuthResponse>
  onboardCompany: (p: {
    action: 'create' | 'join'
    company_name?: string
    access_code?: string
    full_name?: string
  }) => Promise<AuthResponse>
  completeMfa: (step: MfaStep, code: string) => Promise<User>
  refreshUser: () => Promise<User | null>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [sessionExpired, setSessionExpired] = useState(false)
  const userRef = useRef<User | null>(null)
  userRef.current = user

  // The session lives in HttpOnly cookies: ask the server who we are.
  // A 401 triggers one silent refresh inside the API client automatically.
  useEffect(() => {
    authApi
      .me()
      .then((u) => {
        setUser(u)
        setSessionExpired(false)
      })
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    const onExpired = () => {
      if (userRef.current !== null) {
        setSessionExpired(true)
        setUser(null)
      }
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'deskwise:logout-at') {
        setSessionExpired(false)
        setUser(null)
      }
    }
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  const apply = useCallback((res: AuthResponse) => {
    setSessionExpired(false)
    setUser(res.user)
    return res.user
  }, [])

  const enterpriseLogin = useCallback(
    (email: string, password: string) =>
      authApi.enterpriseLogin({ email, password }).then((res) => {
        // Platform admins must finish a TOTP step; surface it as a typed error
        // the login form can catch and turn into a code input.
        if (isMfaResponse(res)) {
          const err = new Error('mfa_required') as Error & { mfa?: MfaLoginResponse }
          err.mfa = res
          throw err
        }
        return apply(res)
      }),
    [apply],
  )

  const completeMfa = useCallback(
    async (step: MfaStep, code: string) =>
      apply(step.kind === 'activate'
        ? await authApi.mfaActivate(step.challenge, code)
        : await authApi.mfaVerify(step.challenge, code)),
    [apply],
  )
  const enterpriseRegister = useCallback(
    (p: {
      company_name: string
      admin_name?: string
      admin_title?: string
      website?: string
      contact_email?: string
      phone?: string
      max_employees?: number | null
      email: string
      password: string
    }) =>
      authApi.enterpriseRegister(p).then((res) => {
        if (!res.verification_required) {
          apply(res)
        }
        return res
      }),
    [apply],
  )

  const joinCompany = useCallback(
    (p: {
      access_code?: string
      invite_token?: string
      full_name?: string
      email: string
      password: string
    }) =>
      authApi.joinCompany(p).then((res) => {
        if (!res.verification_required) {
          apply(res)
        }
        return res
      }),
    [apply],
  )

  const googleLogin = useCallback(
    (credential: string) =>
      authApi.googleAuth(credential).then((res) => {
        if (isMfaResponse(res)) {
          const err = new Error('mfa_required') as Error & { mfa?: MfaLoginResponse }
          err.mfa = res
          throw err
        }
        apply(res)
        return res
      }),
    [apply],
  )

  const onboardCompany = useCallback(
    (p: {
      action: 'create' | 'join'
      company_name?: string
      access_code?: string
      full_name?: string
    }) =>
      authApi.onboardCompany(p).then((res) => {
        apply(res)
        return res
      }),
    [apply],
  )
  const refreshUser = useCallback(() => {
    return authApi
      .me()
      .then((u) => {
        setUser(u)
        return u
      })
      .catch(() => null)
  }, [])

  const setLanguage = useCallback(
    async (lang: UiLanguage) => {
      setUser((u) => (u ? { ...u, language: lang } : u)) // optimistic
      try {
        const updated = await authApi.updateMe({ language: lang })
        setUser(updated)
      } catch {
        /* keep the optimistic value; next refresh reconciles */
      }
    },
    [],
  )

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      /* clearing cookies server-side is best-effort */
    }
    try {
      window.localStorage.setItem('deskwise:logout-at', String(Date.now()))
    } catch {
      /* ignore storage errors */
    }
    setSessionExpired(false)
    setUser(null)
  }, [])

  const isPlat = !!user && (!!user.is_platform_admin || !!user.is_superuser)
  const needsOnboarding = !!user && !isPlat && !user.company_id

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        sessionExpired,
        isEnterprise: !!user,
        isPlatformAdmin: isPlat,
        needsOnboarding,
        language: isUiLanguage(user?.language) ? user.language : 'en',
        setLanguage,
        enterpriseLogin,
        enterpriseRegister,
        joinCompany,
        googleLogin,
        onboardCompany,
        completeMfa,
        refreshUser,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be within <AuthProvider>')
  return ctx
}
