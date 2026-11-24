import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import { headers } from 'next/headers'
import { Instrument_Sans, Instrument_Serif } from 'next/font/google'
import { AuthProvider } from '@/lib/auth'
import { ThemeProvider } from '@/components/theme-provider'
import { Toaster } from '@/components/toaster'
import { SmoothScroll } from '@/components/smooth-scroll'
import './globals.css'

const instrumentSans = Instrument_Sans({
  subsets: ['latin'],
  variable: '--font-instrument-sans',
  display: 'swap',
})

const instrumentSerif = Instrument_Serif({
  subsets: ['latin'],
  weight: '400',
  style: ['normal', 'italic'],
  variable: '--font-instrument-serif',
  display: 'swap',
})

export const metadata: Metadata = {
  title: {
    default: 'Deskwise — Private company knowledge, permission-aware AI',
    template: '%s · Deskwise',
  },
  description:
    'Deskwise is a private, permission-aware knowledge system for registered organizations. Search company documents, get cited AI answers, and share precisely — without exposing the rest of your library.',
  applicationName: 'Deskwise',
  keywords: [
    'Deskwise',
    'permission-aware AI',
    'enterprise knowledge management',
    'private document repository',
    'secure document sharing',
    'RAG assistant',
    'multi-tenant knowledge base',
  ],
  generator: 'Deskwise',
  icons: {
    icon: [
      { url: '/icon-light-32x32.png', media: '(prefers-color-scheme: light)' },
      { url: '/icon-dark-32x32.png', media: '(prefers-color-scheme: dark)' },
      { url: '/icon.svg', type: 'image/svg+xml' },
    ],
    apple: '/apple-icon.png',
  },
}

export const viewport: Viewport = {
  colorScheme: 'light dark',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f5f2ea' },
    { media: '(prefers-color-scheme: dark)', color: '#131210' },
  ],
}

// Apply the saved theme before first paint so there is no light/dark flash.
// Dark is the default; only an explicit light choice opts out.
const themeScript = `(function(){try{var d=localStorage.getItem('theme')!=='light';var r=document.documentElement;r.classList.toggle('dark',d);r.classList.toggle('light',!d);r.style.colorScheme=d?'dark':'light';r.dataset.theme=d?'dark':'light';}catch(e){}})();`

// BUILD_TARGET=static (static export) cannot read request headers; the server
// build reads the per-request CSP nonce set by proxy.ts, which also makes every
// page dynamically rendered (required for nonces). See docs/security/hardening.md.
const isStaticBuild = process.env.BUILD_TARGET === 'static' || process.env.STATIC_EXPORT === 'true'

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const nonce = isStaticBuild ? undefined : ((await headers()).get('x-nonce') ?? undefined)
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${instrumentSans.variable} ${instrumentSerif.variable}`}
    >
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeScript }} />
        <noscript>
          <style>{`.reveal{opacity:1!important;transform:none!important}`}</style>
        </noscript>
      </head>
      <body className="min-h-screen antialiased">
        <ThemeProvider defaultTheme="dark">
          <AuthProvider>
            <SmoothScroll>{children}</SmoothScroll>
          </AuthProvider>
          <Toaster />
          {process.env.NODE_ENV === 'production' && <Analytics />}
        </ThemeProvider>
      </body>
    </html>
  )
}
