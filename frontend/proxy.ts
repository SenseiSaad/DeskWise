import { NextResponse, type NextRequest } from 'next/server'

// Strict, nonce-based Content Security Policy for the server (Vercel) build.
// See docs/security/hardening.md. Not used by the static-export build
// (BUILD_TARGET=static), which cannot run a proxy.

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function apiOrigins(): string[] {
  try {
    const u = new URL(API_URL)
    const ws = `${u.protocol === 'https:' ? 'wss:' : 'ws:'}//${u.host}`
    return [u.origin, ws]
  } catch {
    return []
  }
}

export function buildCsp(nonce: string, isDev: boolean): string {
  const connect = ["'self'", ...apiOrigins(), 'https://accounts.google.com/gsi/']
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ''}`,
    // React style={{}} props and Radix/Base UI positioning write inline style
    // attributes, which a nonce cannot cover, so styles keep 'unsafe-inline'
    // (no nonce here: a nonce would make browsers ignore 'unsafe-inline').
    "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
    "img-src 'self' data: blob: https://*.googleusercontent.com",
    "font-src 'self' data:",
    `connect-src ${connect.join(' ')}`,
    'frame-src https://accounts.google.com/gsi/',
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(isDev ? [] : ['upgrade-insecure-requests']),
  ].join('; ')
}

export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64')
  const csp = buildCsp(nonce, process.env.NODE_ENV === 'development')

  const requestHeaders = new Headers(request.headers)
  requestHeaders.set('x-nonce', nonce)
  requestHeaders.set('Content-Security-Policy', csp)

  const response = NextResponse.next({ request: { headers: requestHeaders } })
  response.headers.set('Content-Security-Policy', csp)
  response.headers.set('X-Content-Type-Options', 'nosniff')
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin')
  response.headers.set('X-Frame-Options', 'DENY')
  response.headers.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()')
  // Google Sign-In uses a popup that must be able to message this window.
  response.headers.set('Cross-Origin-Opener-Policy', 'same-origin-allow-popups')
  if (process.env.NODE_ENV !== 'development') {
    response.headers.set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
  }
  return response
}

export const config = {
  matcher: [
    {
      source: '/((?!api|_next/static|_next/image|_vercel|favicon.ico|.*\\.(?:png|jpg|jpeg|svg|ico|webp|txt|xml)$).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
}
