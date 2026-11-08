import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: { absolute: 'Reset your password · Deskwise' },
  description: 'Request a secure password-reset link for your Deskwise workspace account.',
}

export default function ForgotLayout({ children }: { children: React.ReactNode }) {
  return children
}
