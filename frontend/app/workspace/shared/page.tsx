'use client'

import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence } from 'motion/react'
import {
  AlertCircle,
  Building2,
  Check,
  Download,
  Eye,
  FileText,
  Loader2,
  Share2,
  X,
} from 'lucide-react'
import { downloadOwnDocument, workApi, type SharedDoc } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { formatDate } from '@/lib/utils'
import { SmoothDialogFrame } from '@/components/ui/smooth-select'

const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/25 focus-visible:ring-offset-2 focus-visible:ring-offset-background'
const eyebrow = 'text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground'
const iconBtn =
  `inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-elevated px-3.5 py-2 text-xs font-medium text-foreground transition-all duration-150 hover:border-foreground hover:bg-surface active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`
const ghostBtn =
  `inline-flex items-center justify-center gap-2 rounded-full border border-border-strong bg-surface-elevated px-4 py-2 text-xs font-medium text-foreground transition-all duration-150 hover:border-foreground hover:bg-surface active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`

function displayTitle(filename: string) {
  const base = filename.replace(/\.(md|markdown|txt|pdf|docx?|pptx?|xlsx?|csv|rtf|json|ya?ml|html?|xml)$/i, '')
  const words = base.replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim()
  return words.replace(/\b\w/g, (c) => c.toUpperCase()) || filename
}

function PreviewModal({
  doc,
  onClose,
}: {
  doc: SharedDoc
  onClose: () => void
}) {
  const [data, setData] = useState<{
    id: number
    filename: string
    text: string
    truncated: boolean
    num_chunks: number
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    workApi
      .preview(doc.id)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not preview document.'))
      .finally(() => setLoading(false))
  }, [doc.id])

  return (
    <SmoothDialogFrame
      onClose={onClose}
      maxWidthClass="max-w-2xl"
      panelClassName="flex max-h-[85vh] flex-col p-6"
      ariaLabel={`Preview ${doc.filename}`}
    >
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div className="flex min-w-0 items-center gap-2">
          <Eye className="size-4 shrink-0 text-foreground" />
          <h2 className="truncate text-sm font-semibold text-foreground">{doc.filename}</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-4">
        {loading ? (
          <div className="grid h-48 place-items-center text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-2">
              <Loader2 className="size-4 animate-spin" /> Loading document preview…
            </span>
          </div>
        ) : error ? (
          <p className="rounded-xl bg-danger-soft p-4 text-xs text-danger">{error}</p>
        ) : (
          <div>
            <p className="mb-2 text-[11px] text-muted-foreground">
              Readable content prepared for instant search and AI answers
              {data?.truncated ? ' (showing excerpt)' : ''}
            </p>
            <div className="rounded-2xl border border-border bg-surface p-4 font-mono text-xs leading-relaxed text-foreground whitespace-pre-wrap">
              {data?.text || '(No readable text extracted from this file)'}
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end border-t border-border pt-3">
        <button type="button" onClick={onClose} className={ghostBtn}>
          Close
        </button>
      </div>
    </SmoothDialogFrame>
  )
}

// Documents that OTHER companies granted this specific user access to, the
// visible half of granular cross-company collaboration (see DocumentShare).
export default function SharedWithMePage() {
  const { user } = useAuth()
  const [docs, setDocs] = useState<SharedDoc[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [busy, setBusy] = useState<Set<number>>(() => new Set())
  const [downloadedIds, setDownloadedIds] = useState<Set<number>>(() => new Set())
  const [actionError, setActionError] = useState('')
  const [previewDoc, setPreviewDoc] = useState<SharedDoc | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError('')
    workApi
      .sharedWithMe()
      .then(setDocs)
      .catch((e) => setLoadError(e instanceof Error ? e.message : 'Could not load shared documents.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleDownload(doc: SharedDoc) {
    setActionError('')
    setBusy((p) => new Set(p).add(doc.id))
    try {
      await downloadOwnDocument(doc.id, doc.filename)
      setDownloadedIds((prev) => new Set(prev).add(doc.id))
      window.setTimeout(() => {
        setDownloadedIds((prev) => {
          const next = new Set(prev)
          next.delete(doc.id)
          return next
        })
      }, 2200)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : `Could not download "${doc.filename}".`)
    } finally {
      setBusy((p) => {
        const n = new Set(p)
        n.delete(doc.id)
        return n
      })
    }
  }

  if (!user) return null

  return (
    <div className="pb-6">
      <header className="border-b border-border pb-8">
        <p className={eyebrow}>Cross-company collaboration</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-0.05em] sm:text-4xl sm:tracking-[-0.06em]">
          Shared <span className="font-serif font-normal italic">with you.</span>
        </h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Individual documents that people at other organizations have granted you access to. You can
          read and search these alongside your own company&apos;s library, but nobody else at your
          company can see them unless they were shared too.
        </p>
      </header>

      <section className="mt-8">
        {actionError && (
          <div role="alert" className="mb-4 flex items-start gap-2 rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span className="flex-1">{actionError}</span>
          </div>
        )}

        {loading ? (
          <div className="space-y-3">
            {[0, 1].map((idx) => (
              <div key={idx} className="h-24 animate-pulse rounded-2xl border border-border bg-surface-elevated/80" />
            ))}
          </div>
        ) : loadError ? (
          <div role="alert" className="rounded-3xl border border-danger/30 bg-danger-soft p-10 text-center">
            <AlertCircle className="mx-auto size-6 text-danger" aria-hidden />
            <p className="mt-3 text-sm font-medium text-danger">{loadError}</p>
            <button type="button" onClick={load} className={`mt-5 ${ghostBtn}`}>Try again</button>
          </div>
        ) : docs.length === 0 ? (
          <div className="rounded-3xl border border-border bg-surface-elevated p-12 text-center">
            <span className="mx-auto grid size-12 place-items-center rounded-2xl bg-surface-2 text-muted-foreground">
              <Share2 className="size-6" aria-hidden />
            </span>
            <p className="mt-4 font-serif text-2xl italic">Nothing shared yet.</p>
            <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
              When someone at another company shares a specific document with you, it will appear here.
            </p>
          </div>
        ) : (
          <ul className="space-y-3">
            {docs.map((doc) => {
              const isBusy = busy.has(doc.id)
              const justDownloaded = downloadedIds.has(doc.id)
              return (
                <li
                  key={doc.id}
                  className="rounded-2xl border border-border bg-surface-elevated p-4 shadow-2xs transition-all duration-150 hover:border-border-strong hover:shadow-md sm:p-5"
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex min-w-0 items-start gap-3">
                      <span className="mt-0.5 grid size-10 shrink-0 place-items-center rounded-xl bg-surface-2 text-muted-foreground">
                        <FileText className="size-5" aria-hidden />
                      </span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="truncate text-sm font-semibold text-foreground" title={doc.filename}>{displayTitle(doc.filename)}</h3>
                          <span className="inline-flex items-center gap-1 rounded-full bg-info-soft px-2.5 py-0.5 text-[11px] font-medium text-info">
                            <Building2 className="size-3" aria-hidden /> {doc.company_name || 'External company'}
                          </span>
                        </div>
                        {doc.description && <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-muted-foreground">{doc.description}</p>}
                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                          <span className="rounded-full bg-surface-2 px-2.5 py-0.5 font-medium text-foreground/85">{doc.category || 'General'}</span>
                          {doc.shared_by && <span>Shared by {doc.shared_by}</span>}
                          {doc.expires_at && <span className="text-warn">Expires {formatDate(doc.expires_at)}</span>}
                        </div>
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-2 lg:justify-end">
                      <button
                        type="button"
                        onClick={() => setPreviewDoc(doc)}
                        className={ghostBtn}
                      >
                        <Eye className="size-3.5" aria-hidden />
                        Preview
                      </button>
                      {doc.can_download ? (
                        <button
                          type="button"
                          onClick={() => handleDownload(doc)}
                          disabled={isBusy}
                          className={
                            justDownloaded
                              ? `inline-flex items-center gap-1.5 rounded-full border border-ok/35 bg-ok-soft px-3.5 py-2 text-xs font-medium text-ok transition-all duration-150 ${focusRing}`
                              : iconBtn
                          }
                        >
                          {isBusy ? (
                            <Loader2 className="size-3.5 animate-spin" aria-hidden />
                          ) : justDownloaded ? (
                            <Check className="size-3.5" aria-hidden />
                          ) : (
                            <Download className="size-3.5" aria-hidden />
                          )}
                          {isBusy ? 'Preparing…' : justDownloaded ? 'Downloaded ✓' : 'Download'}
                        </button>
                      ) : (
                        <span className="rounded-full bg-surface-2 px-3 py-1.5 text-xs text-muted-foreground">View only</span>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <AnimatePresence>
        {previewDoc && (
          <PreviewModal key={previewDoc.id} doc={previewDoc} onClose={() => setPreviewDoc(null)} />
        )}
      </AnimatePresence>
    </div>
  )
}
