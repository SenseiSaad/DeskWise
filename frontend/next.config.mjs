/** @type {import('next').NextConfig} */
// Build targets (see docs/security/hardening.md):
// 1. Server build (default; Vercel or `next start`): proxy.ts sets a strict,
//    per-request nonce Content-Security-Policy and the security headers.
// 2. Docker (DOCKER_STANDALONE=true): same as 1, standalone server output.
// 3. Static export (BUILD_TARGET=static, or legacy STATIC_EXPORT=true), e.g.
//    AWS Amplify: no server, so no proxy and no nonce. A weaker, hash/nonce-free
//    CSP must be sent by the static host (amplify.yml customHeaders).
const dockerStandalone = process.env.DOCKER_STANDALONE === 'true'
const staticExport = process.env.BUILD_TARGET === 'static' || process.env.STATIC_EXPORT === 'true'

/** @type {import('next').NextConfig} */
const nextConfig = {
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  devIndicators: false,
}

if (staticExport) {
  nextConfig.output = 'export'
} else if (dockerStandalone) {
  nextConfig.output = 'standalone'
  nextConfig.trailingSlash = false
}

export default nextConfig
