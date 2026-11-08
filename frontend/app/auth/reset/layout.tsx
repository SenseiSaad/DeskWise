import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: { absolute: 'Choose a new password · Deskwise' },
  description: 'Set a new password for your Deskwise workspace account.',
}

export default function ResetLayout({ children }: { children: React.ReactNode }) {
  return children
}
