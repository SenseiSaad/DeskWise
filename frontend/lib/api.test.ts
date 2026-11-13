import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, authApi, SESSION_EXPIRED_EVENT } from './api'

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('API auth & session refresh handling', () => {
  const origFetch = globalThis.fetch

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    globalThis.fetch = origFetch
  })

  it('surfaces backend credential errors on login without triggering refresh', async () => {
    const calls: string[] = []
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      return jsonResponse({ detail: 'Invalid email or password.' }, 401)
    }) as typeof fetch

    await expect(
      authApi.enterpriseLogin({ email: 'bad@acme.test', password: 'wrong' }),
    ).rejects.toThrow('Invalid email or password.')
    expect(calls).toHaveLength(1)
    expect(calls[0]).toContain('/api/auth/login')
  })

  it('coalesces parallel 401 refreshes into one /api/auth/refresh and replays', async () => {
    let authed = false
    let refreshCount = 0
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/auth/refresh')) {
        refreshCount += 1
        authed = true
        return jsonResponse({ ok: true }, 200)
      }
      if (!authed) return jsonResponse({ detail: 'Unauthorized' }, 401)
      return jsonResponse({ ok: true, path: url }, 200)
    }) as typeof fetch

    const [a, b] = await Promise.all([api.get('/documents'), api.get('/analytics')])
    expect(a.ok).toBe(true)
    expect(b.ok).toBe(true)
    expect(refreshCount).toBe(1)
  })

  it('stops after one failed replay without infinite refresh recursion', async () => {
    let refreshCount = 0
    let expiredEvents = 0
    const handler = () => {
      expiredEvents += 1
    }
    if (typeof window !== 'undefined') {
      window.addEventListener(SESSION_EXPIRED_EVENT, handler)
    }
    try {
      globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/api/auth/refresh')) {
          refreshCount += 1
          return jsonResponse({ ok: true }, 200)
        }
        return jsonResponse({ detail: 'Unauthorized' }, 401)
      }) as typeof fetch

      await expect(api.get('/documents')).rejects.toThrow('Session expired. Please sign in again.')
      expect(refreshCount).toBe(1)
      if (typeof window !== 'undefined') {
        expect(expiredEvents).toBe(1)
      }
    } finally {
      if (typeof window !== 'undefined') {
        window.removeEventListener(SESSION_EXPIRED_EVENT, handler)
      }
    }
  })
})
