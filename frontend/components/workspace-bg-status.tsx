'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { CheckCircle2, FileText, Loader2, Sparkles, X, AlertCircle } from 'lucide-react'
import { useWorkspaceStore } from '@/lib/workspace-store'

/** Floating background-activity indicator kept mounted across all /workspace tabs.
 * Shows live upload/indexing progress and background AI stream completion so users
 * can navigate freely while uploads or chat generation finish. */
export function WorkspaceBackgroundStatusPill() {
  const pathname = usePathname()
  const { uploadJobs, dismissUploadJobs, chat } = useWorkspaceStore()
  const [expanded, setExpanded] = useState(false)

  const queuedOrUploading = uploadJobs.filter(
    (j) => j.status === 'queued' || j.status === 'uploading',
  ).length
  const indexingCount = uploadJobs.filter((j) => j.status === 'indexing').length
  const readyCount = uploadJobs.filter((j) => j.status === 'ready').length
  const failedCount = uploadJobs.filter((j) => j.status === 'failed').length
  const activeUploadWork = queuedOrUploading + indexingCount > 0
  const onChatPage = pathname.replace(/\/$/, '') === '/workspace/chat'
  const showBgChat = chat.streaming && !onChatPage

  // Auto-clear completed job tray 10s after all jobs finish cleanly without failures.
  useEffect(() => {
    if (!uploadJobs.length || activeUploadWork || failedCount > 0) return
    const timer = window.setTimeout(() => {
      dismissUploadJobs()
    }, 10_000)
    return () => window.clearTimeout(timer)
  }, [uploadJobs.length, activeUploadWork, failedCount, dismissUploadJobs])

  if (!uploadJobs.length && !showBgChat) return null

  return (
    <div
      aria-live="polite"
      className="fixed bottom-5 right-5 z-40 flex max-w-sm flex-col gap-2"
    >
      {showBgChat && (
        <Link
          href="/workspace/chat"
          className="flex items-center gap-2.5 rounded-xl border border-emerald-500/30 bg-zinc-950/95 px-3.5 py-2.5 text-xs text-zinc-100 shadow-lg backdrop-blur transition hover:border-emerald-400/60"
        >
          <Sparkles className="size-4 shrink-0 animate-pulse text-emerald-400" />
          <span className="font-medium">Ask AI is streaming your reply…</span>
          <span className="ml-auto text-[11px] text-emerald-400 underline underline-offset-2">
            Open
          </span>
        </Link>
      )}

      {uploadJobs.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/95 text-zinc-100 shadow-xl backdrop-blur">
          <div className="flex items-center gap-2.5 px-3.5 py-2.5">
            {activeUploadWork ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-sky-400" />
            ) : failedCount > 0 ? (
              <AlertCircle className="size-4 shrink-0 text-amber-400" />
            ) : (
              <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
            )}
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="min-w-0 flex-1 text-left text-xs"
            >
              <div className="truncate font-medium">
                {queuedOrUploading > 0
                  ? `Uploading ${queuedOrUploading} file${queuedOrUploading === 1 ? '' : 's'}…`
                  : indexingCount > 0
                    ? `Indexing ${indexingCount} document${indexingCount === 1 ? '' : 's'} in background…`
                    : failedCount > 0
                      ? `${readyCount} ready · ${failedCount} failed`
                      : `${readyCount} document${readyCount === 1 ? '' : 's'} indexed and ready`}
              </div>
              <div className="mt-0.5 text-[11px] text-zinc-400">
                {activeUploadWork
                  ? 'Safe to browse other tabs — click for details'
                  : 'Ready for Ask AI search'}
              </div>
            </button>
            <Link
              href="/workspace/documents"
              className="rounded-md bg-zinc-800 px-2 py-1 text-[11px] font-medium text-zinc-200 transition hover:bg-zinc-700"
            >
              Docs
            </Link>
            {!queuedOrUploading && (
              <button
                type="button"
                aria-label="Dismiss upload status"
                onClick={dismissUploadJobs}
                className="rounded p-1 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>

          {expanded && (
            <div className="max-h-44 space-y-1 overflow-y-auto border-t border-zinc-800/80 px-3.5 py-2 text-[11px]">
              {uploadJobs.map((job) => (
                <div key={job.id} className="flex items-center gap-2 text-zinc-300">
                  <FileText className="size-3 shrink-0 text-zinc-500" />
                  <span className="min-w-0 flex-1 truncate">{job.filename}</span>
                  <span
                    className={
                      job.status === 'ready'
                        ? 'text-emerald-400'
                        : job.status === 'failed'
                          ? 'text-rose-400'
                          : job.status === 'indexing'
                            ? 'text-amber-300'
                            : 'text-sky-300'
                    }
                  >
                    {job.status === 'queued'
                      ? 'Queued'
                      : job.status === 'uploading'
                        ? 'Uploading…'
                        : job.status === 'indexing'
                          ? 'Indexing…'
                          : job.status === 'ready'
                            ? 'Ready'
                            : 'Failed'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
