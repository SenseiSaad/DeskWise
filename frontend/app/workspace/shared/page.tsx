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
import { SmoothDialogFrame } from '@/components/ui/smooth-select'

const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1d1d1b]/25 focus-visible:ring-offset-2 focus-visible:ring-offset-[#f7f6f2]'
const eyebrow = 'text-xs font-semibold uppercase tracking-[0.16em] text-[#6b6862]'
const iconBtn =
  `inline-flex items-center gap-1.5 rounded-full border border-[#dcdad3] bg-[#fffdfa] px-3.5 py-2 text-xs font-medium text-[#1d1d1b] transition-all duration-150 hover:border-[#1d1d1b] hover:bg-[#faf8f3] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`
const ghostBtn =
  `inline-flex items-center justify-center gap-2 rounded-full border border-[#dcdad3] bg-[#fffdfa] px-4 py-2 text-xs font-medium text-[#1d1d1b] transition-all duration-150 hover:border-[#1d1d1b] hover:bg-[#faf8f3] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`

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
      <div className="flex items-center justify-between border-b border-[#eae7df] pb-3">
        <div className="flex min-w-0 items-center gap-2">
          <Eye className="size-4 shrink-0 text-[#1d1d1b]" />
          <h2 className="truncate text-sm font-semibold text-[#1d1d1b]">{doc.filename}</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full p-1.5 text-[#6b6862] transition-colors hover:bg-[#efece4] hover:text-[#1d1d1b]"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-4">
        {loading ? (
          <div className="grid h-48 place-items-center text-xs text-[#6b6862]">
            <span className="inline-flex items-center gap-2">
              <Loader2 className="size-4 animate-spin" /> Loading document preview…
            </span>
          </div>
        ) : error ? (
          <p className="rounded-xl bg-[#fbe4e0] p-4 text-xs text-[#9a3b2c]">{error}</p>
        ) : (
          <div>
            <p className="mb-2 text-[11px] text-[#6b6862]">
              Readable content prepared for instant search and AI answers
              {data?.truncated ? ' (showing excerpt)' : ''}
            </p>
            <div className="rounded-2xl border border-[#eae7df] bg-[#f9f8f5] p-4 font-mono text-xs leading-relaxed text-[#2c2b29] whitespace-pre-wrap">
              {data?.text || '(No readable text extracted from this file)'}
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end border-t border-[#eae7df] pt-3">
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
      <header className="border-b border-[#e6e3dc] pb-8">
        <p className={eyebrow}>Cross-company collaboration</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-0.05em] sm:text-4xl sm:tracking-[-0.06em]">
          Shared <span className="font-serif font-normal italic">with you.</span>
        </h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-[#6b6862]">
          Individual documents that people at other organizations have granted you access to. You can
          read and search these alongside your own company&apos;s library, but nobody else at your
          company can see them unless they were shared too.
        </p>
      </header>

      <section className="mt-8">
        {actionError && (
          <div role="alert" className="mb-4 flex items-start gap-2 rounded-xl bg-[#fbe4e0] px-4 py-3 text-sm text-[#9a3b2c]">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span className="flex-1">{actionError}</span>
          </div>
        )}

        {loading ? (
          <div className="space-y-3">
            {[0, 1].map((idx) => (
              <div key={idx} className="h-24 animate-pulse rounded-2xl border border-[#eae7df] bg-[#fffdfa]/80" />
            ))}
          </div>
        ) : loadError ? (
          <div role="alert" className="rounded-3xl border border-[#e6c9c1] bg-[#fbe4e0] p-10 text-center">
            <AlertCircle className="mx-auto size-6 text-[#9a3b2c]" aria-hidden />
            <p className="mt-3 text-sm font-medium text-[#9a3b2c]">{loadError}</p>
            <button type="button" onClick={load} className={`mt-5 ${ghostBtn}`}>Try again</button>
          </div>
        ) : docs.length === 0 ? (
          <div className="rounded-3xl border border-[#e6e3dc] bg-[#fffdfa] p-12 text-center">
            <span className="mx-auto grid size-12 place-items-center rounded-2xl bg-[#f2efe8] text-[#5d5b55]">
              <Share2 className="size-6" aria-hidden />
            </span>
            <p className="mt-4 font-serif text-2xl italic">Nothing shared yet.</p>
            <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-[#6b6862]">
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
                  className="rounded-2xl border border-[#e6e3dc] bg-[#fffdfa] p-4 shadow-2xs transition-all duration-150 hover:border-[#d5d1c6] hover:shadow-md hover:shadow-[#1d1d1b]/[0.04] sm:p-5"
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex min-w-0 items-start gap-3">
                      <span className="mt-0.5 grid size-10 shrink-0 place-items-center rounded-xl bg-[#f2efe8] text-[#5d5b55]">
                        <FileText className="size-5" aria-hidden />
                      </span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="truncate text-sm font-semibold text-[#1d1d1b]" title={doc.filename}>{displayTitle(doc.filename)}</h3>
                          <span className="inline-flex items-center gap-1 rounded-full bg-[#eef1f7] px-2.5 py-0.5 text-[11px] font-medium text-[#3c5a8a]">
                            <Building2 className="size-3" aria-hidden /> {doc.company_name || 'External company'}
                          </span>
                        </div>
                        {doc.description && <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-[#6b6862]">{doc.description}</p>}
                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[#6b6862]">
                          <span className="rounded-full bg-[#f2efe8] px-2.5 py-0.5 font-medium text-[#5d5b55]">{doc.category || 'General'}</span>
                          {doc.shared_by && <span>Shared by {doc.shared_by}</span>}
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
                              ? `inline-flex items-center gap-1.5 rounded-full border border-[#b7dcc0] bg-[#e6f1e4] px-3.5 py-2 text-xs font-medium text-[#2f5b36] transition-all duration-150 ${focusRing}`
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
                        <span className="rounded-full bg-[#f4f2ec] px-3 py-1.5 text-xs text-[#6b6862]">View only</span>
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
