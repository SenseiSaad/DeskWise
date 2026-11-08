import { Download, FileText, Lock, ShieldCheck } from 'lucide-react'

/** Small token-colored illustrations used by the hero and the scroll story. */

export function ChatMockup({ step = 3 }: { step?: number }) {
  return (
    <div className="space-y-3 text-sm">
      <div
        className={`ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-primary-foreground transition-all duration-500 ${
          step >= 1 ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0'
        }`}
      >
        How many paid leave days do we get?
      </div>
      <div
        className={`max-w-[92%] rounded-2xl rounded-bl-md border border-border bg-surface-2 px-4 py-3 transition-all duration-500 ${
          step >= 2 ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0'
        }`}
      >
        <p>Full-time employees get <strong>20 paid leave days</strong> each year. Please apply 5 working days ahead.</p>
        <span className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground">
          <FileText className="size-3.5 text-accent" aria-hidden /> Employee Handbook · page 18
        </span>
      </div>
      <div
        className={`max-w-[92%] rounded-2xl border border-border bg-background px-4 py-3 transition-all duration-500 ${
          step >= 3 ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0'
        }`}
      >
        <p className="font-medium">Leave request — ready to send</p>
        <div className="mt-2 flex gap-2 text-xs">
          <span className="rounded-md bg-accent px-2.5 py-1 font-medium text-accent-foreground">Download DOCX</span>
          <span className="rounded-md border border-border px-2.5 py-1 text-muted-foreground">PDF</span>
        </div>
      </div>
    </div>
  )
}

export function FormMockup() {
  const rows = [
    ['Employee', 'Ayesha Khan'],
    ['Role', 'Accountant'],
    ['Leave dates', '12 – 14 Nov'],
    ['Reason', 'Family event'],
  ]
  return (
    <div className="rounded-xl border border-border bg-background p-4 text-sm">
      <p className="font-semibold">Leave Request</p>
      <dl className="mt-3 divide-y divide-border">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 py-2">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-medium">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 flex gap-2 text-xs">
        <span className="inline-flex items-center gap-1 rounded-md bg-accent px-2.5 py-1.5 font-medium text-accent-foreground">
          <Download className="size-3.5" aria-hidden /> DOCX
        </span>
        <span className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-muted-foreground">
          <Download className="size-3.5" aria-hidden /> PDF
        </span>
      </div>
    </div>
  )
}

export function AccessMockup() {
  const files = [
    ['Employee Handbook.pdf', 'Everyone', false],
    ['Payroll 2026.xlsx', 'HR only', true],
    ['Vendor Contract.pdf', 'Finance only', true],
  ] as const
  return (
    <div className="rounded-xl border border-border bg-background p-4 text-sm">
      <ul className="divide-y divide-border">
        {files.map(([name, who, locked]) => (
          <li key={name} className="flex items-center justify-between gap-3 py-2.5">
            <span className="flex min-w-0 items-center gap-2">
              {locked ? (
                <Lock className="size-4 shrink-0 text-accent" aria-hidden />
              ) : (
                <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              )}
              <span className="truncate">{name}</span>
            </span>
            <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">{who}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
        <ShieldCheck className="size-3.5 text-accent" aria-hidden /> Marketing can&apos;t see HR or Finance files.
      </p>
    </div>
  )
}

export function AuditMockup() {
  const rows = [
    ['09:41', 'Ayesha signed in'],
    ['09:44', 'Handbook.pdf uploaded'],
    ['09:52', 'Access granted to Hira'],
    ['10:03', 'Download blocked'],
  ]
  return (
    <ol className="rounded-xl border border-border bg-background p-4 text-sm">
      {rows.map(([t, label], i) => (
        <li key={t} className="relative flex gap-3 pb-3 last:pb-0">
          {i < rows.length - 1 && <span aria-hidden className="absolute left-[5px] top-3 h-full w-px bg-border" />}
          <span aria-hidden className="relative mt-1.5 size-[11px] shrink-0 rounded-full bg-accent" />
          <span>
            <span className="mr-2 font-mono text-xs text-muted-foreground">{t}</span>
            {label}
          </span>
        </li>
      ))}
    </ol>
  )
}
