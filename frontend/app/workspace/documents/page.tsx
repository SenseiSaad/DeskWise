'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import {
  AlertCircle,
  Building2,
  Check,
  CheckCircle2,
  ChevronDown,
  CloudUpload,
  Download,
  Eye,
  FileText,
  History,
  Loader2,
  Lock,
  Pencil,
  RefreshCw,
  Search,
  Share2,
  Shield,
  ShieldAlert,
  Sparkles,
  Tag,
  Trash2,
  Upload,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import {
  companyApi,
  companyApi2,
  downloadOwnDocument,
  shareApi,
  workApi,
  type CompanyDirectory,
  type Department,
  type DocumentShareRow,
  type EnterpriseDoc,
  type MemberDirectory,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { toast } from '@/components/toaster'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { SmoothCollapse, SmoothDialogFrame, SmoothSelect } from '@/components/ui/smooth-select'
import { useWorkspaceStore } from '@/lib/workspace-store'

const EASE = [0.22, 1, 0.36, 1] as const

type Sort = 'recent' | 'downloads' | 'name' | 'size'
const eyebrow = 'text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground'
const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/25 focus-visible:ring-offset-2 focus-visible:ring-offset-background'
const inputClass =
  'h-11 w-full rounded-xl border border-border-strong bg-surface-elevated px-3.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-foreground'
const primaryBtn = `inline-flex h-10 items-center justify-center gap-2 rounded-full bg-primary px-4 text-xs font-medium text-primary-foreground transition-all duration-150 hover:opacity-90 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`
const ghostBtn = `inline-flex items-center justify-center gap-1.5 rounded-full border border-border-strong bg-surface-elevated px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-150 hover:border-foreground hover:bg-surface active:scale-[0.98] disabled:opacity-60 ${focusRing}`
const dangerBtn = `inline-flex items-center gap-1.5 rounded-full border border-danger/30 bg-surface-elevated px-3 py-1.5 text-xs font-medium text-danger transition-all duration-150 hover:border-danger hover:bg-danger-soft active:scale-[0.98] disabled:opacity-50 ${focusRing}`

function formatBytes(n: number) {
  if (!n || n < 0) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function displayTitle(filename: string) {
  const base = filename.replace(
    /\.(md|markdown|txt|pdf|docx?|pptx?|xlsx?|csv|rtf|json|ya?ml|html?|xml)$/i,
    '',
  )
  return base.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) || filename
}

function AccessBadge({
  scope,
  deptName,
}: {
  scope: EnterpriseDoc['access_scope']
  deptName?: string | null
}) {
  if (scope === 'restricted') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2.5 py-0.5 text-[11px] font-medium text-warn">
        <Lock className="size-3" /> Selected people
      </span>
    )
  }
  if (scope === 'department') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-info-soft px-2.5 py-0.5 text-[11px] font-medium text-info">
        <Users className="size-3" /> {deptName || 'Department'}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-ok-soft px-2.5 py-0.5 text-[11px] font-medium text-ok">
      <Building2 className="size-3" /> Company-wide
    </span>
  )
}

function IndexingBadge({
  status,
  onRetry,
}: {
  status: EnterpriseDoc['indexing_status']
  onRetry?: () => void
}) {
  if (status === 'pending') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2.5 py-0.5 text-[10px] font-medium text-warn ring-1 ring-warn/30">
        <Loader2 className="size-3 animate-spin" /> Preparing…
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="inline-flex items-center gap-1">
        <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft px-2.5 py-0.5 text-[10px] font-medium text-danger">
          Needs retry
        </span>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            title="Retry preparation"
            className="rounded-full p-1 text-xs text-danger transition-colors hover:bg-danger-soft"
          >
            <RefreshCw className="size-3" />
          </button>
        )}
      </span>
    )
  }
  return null
}

function UploadPanel({
  open,
  onToggle,
  categories,
  departments,
}: {
  open: boolean
  onToggle: () => void
  categories: string[]
  departments: Department[]
  onUploaded?: (doc: EnterpriseDoc) => void
}) {
  const { user } = useAuth()
  const canSetConfidential = Boolean(user?.role === 'admin' || user?.is_platform_admin || user?.is_dept_admin)
  const {
    stagedFiles: files,
    setStagedFiles: setFiles,
    docsState,
    setDocsState,
    enqueueUploads,
  } = useWorkspaceStore()
  const draft = docsState.uploadDraft
  const category = draft.category
  const description = draft.description
  const tagsInput = draft.tagsInput
  const scope = draft.accessScope
  const sensitivity = draft.sensitivity || 'standard'
  const deptId = draft.departmentId
  const isOkf = draft.isOkf
  const setCategory = (v: string) =>
    setDocsState((s) => ({ ...s, uploadDraft: { ...s.uploadDraft, category: v } }))
  const setDescription = (v: string) =>
    setDocsState((s) => ({ ...s, uploadDraft: { ...s.uploadDraft, description: v } }))
  const setTagsInput = (v: string) =>
    setDocsState((s) => ({ ...s, uploadDraft: { ...s.uploadDraft, tagsInput: v } }))
  const setScope = (v: 'company' | 'restricted' | 'department') =>
    setDocsState((s) => ({ ...s, uploadDraft: { ...s.uploadDraft, accessScope: v } }))
  const setSensitivity = (v: 'standard' | 'internal' | 'confidential') =>
    setDocsState((s) => ({ ...s, uploadDraft: { ...s.uploadDraft, sensitivity: v } }))
  const setDeptId = (v: number | '') =>
    setDocsState((s) => ({ ...s, uploadDraft: { ...s.uploadDraft, departmentId: v } }))
  const setIsOkf = (v: boolean) =>
    setDocsState((s) => ({ ...s, uploadDraft: { ...s.uploadDraft, isOkf: v } }))
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  function handleDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    const dropped = Array.from(e.dataTransfer.files || [])
    if (dropped.length > 0) {
      setFiles([...files, ...dropped])
    }
  }

  function removeFileAt(index: number) {
    const next = files.filter((_, i) => i !== index)
    setFiles(next)
    if (next.length === 0 && fileRef.current) fileRef.current.value = ''
  }

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (files.length === 0) {
      toast.error('Choose at least one file to upload.')
      return
    }
    if (scope === 'department' && !deptId) {
      toast.error('Please select a department.')
      return
    }
    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)

    enqueueUploads(files, {
      category: category.trim(),
      description: description.trim(),
      tags,
      isOkf,
      accessScope: scope,
      sensitivity,
      departmentId: deptId,
    })

    setDocsState((s) => ({
      ...s,
      uploadOpen: false,
      uploadDraft: {
        category: '',
        description: '',
        tagsInput: '',
        accessScope: 'company',
        sensitivity: 'standard',
        departmentId: '',
        isOkf: false,
      },
    }))
    if (fileRef.current) fileRef.current.value = ''
  }

  const departmentOptions = [
    { value: '', label: 'Choose department…', description: 'Select which team can access these files' },
    ...departments.map((d) => ({
      value: String(d.id),
      label: d.name,
      badge: `${d.member_count} members`,
    })),
  ]

  const step1Done = files.length > 0
  const step2Done = step1Done && (scope !== 'department' || Boolean(deptId))

  return (
    <div className="overflow-hidden rounded-2xl border border-border-strong bg-surface-elevated shadow-sm shadow-black/5 transition-shadow hover:shadow-md">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={`flex w-full items-center justify-between gap-3 rounded-2xl px-5 py-4 text-left transition-colors hover:bg-surface ${focusRing}`}
      >
        <span className="flex items-center gap-3.5">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <Upload className="size-4" />
          </span>
          <span>
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-foreground">Upload a document</span>
              {files.length > 0 && (
                <span className="rounded-full bg-ok-soft px-2 py-0.5 text-[10px] font-medium text-ok">
                  {files.length} staged
                </span>
              )}
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              Drop files, set who can open them, and track every step live.
            </span>
          </span>
        </span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2, ease: EASE }}
          className="grid size-8 shrink-0 place-items-center rounded-full bg-surface-2 text-muted-foreground"
        >
          <ChevronDown className="size-4" />
        </motion.span>
      </button>

      <SmoothCollapse open={open}>
        <form onSubmit={submit} className="space-y-5 border-t border-border p-5">
          {/* Visible 3-step upload pipeline */}
          <div className="grid grid-cols-3 gap-2 rounded-2xl border border-border bg-surface p-2.5 text-[11px]">
            <div className={`flex items-center gap-2 rounded-xl px-2.5 py-1.5 transition-colors ${step1Done ? 'bg-ok-soft text-ok' : 'bg-surface-elevated text-foreground shadow-xs'}`}>
              <span className={`grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold ${step1Done ? 'bg-ok text-primary-foreground' : 'bg-primary text-primary-foreground'}`}>
                {step1Done ? <Check className="size-3" /> : '1'}
              </span>
              <span className="truncate font-medium">Choose files</span>
            </div>
            <div className={`flex items-center gap-2 rounded-xl px-2.5 py-1.5 transition-colors ${step2Done ? 'bg-ok-soft text-ok' : step1Done ? 'bg-surface-elevated text-foreground shadow-xs' : 'text-muted-foreground'}`}>
              <span className={`grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold ${step2Done ? 'bg-ok text-primary-foreground' : step1Done ? 'bg-primary text-primary-foreground' : 'bg-surface-2 text-muted-foreground'}`}>
                {step2Done ? <Check className="size-3" /> : '2'}
              </span>
              <span className="truncate font-medium">Set access</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl px-2.5 py-1.5 text-muted-foreground">
              <span className="grid size-5 shrink-0 place-items-center rounded-full bg-surface-2 text-[10px] font-semibold text-muted-foreground">
                3
              </span>
              <span className="truncate font-medium">Upload & prepare</span>
            </div>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label htmlFor="up-file" className="text-xs font-medium text-foreground">
                Files
              </label>
              <span className="text-[11px] text-muted-foreground">PDF, DOCX, XLSX, TXT, MD, CSV</span>
            </div>
            <label
              htmlFor="up-file"
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={`group flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-6 text-center transition-all duration-150 ${
                dragOver
                  ? 'scale-[1.01] border-foreground bg-surface-2'
                  : 'border-border-strong bg-surface hover:border-foreground/50 hover:bg-surface-2'
              }`}
            >
              <input
                ref={fileRef}
                id="up-file"
                type="file"
                multiple
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
                className="sr-only"
              />
              <span className="grid size-11 place-items-center rounded-2xl bg-surface-2 text-foreground transition-transform duration-150 group-hover:scale-105">
                <CloudUpload className="size-5" />
              </span>
              <span className="mt-3 text-xs font-semibold text-foreground">
                Click to browse or drag & drop files here
              </span>
              <span className="mt-1 text-[11px] text-muted-foreground">
                Uploads continue in the background even if you switch tabs
              </span>
            </label>

            <AnimatePresence>
              {files.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  transition={{ duration: 0.16, ease: EASE }}
                  className="mt-3 rounded-xl border border-border bg-surface p-3"
                >
                  <div className="mb-2 flex items-center justify-between text-[11px] text-foreground/85">
                    <span className="font-semibold">
                      {files.length} {files.length === 1 ? 'file' : 'files'} ready ({formatBytes(files.reduce((acc, f) => acc + f.size, 0))})
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setFiles([])
                        if (fileRef.current) fileRef.current.value = ''
                      }}
                      className="font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    >
                      Clear all
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {files.map((f, idx) => (
                      <motion.span
                        key={`${f.name}-${f.size}-${idx}`}
                        layout
                        initial={{ opacity: 0, scale: 0.94 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.94 }}
                        className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border-strong bg-surface-elevated px-2.5 py-1 text-[11px] text-foreground shadow-2xs"
                      >
                        <FileText className="size-3 shrink-0 text-muted-foreground" />
                        <span className="max-w-[11rem] truncate font-medium">{f.name}</span>
                        <span className="text-[10px] text-muted-foreground">{formatBytes(f.size)}</span>
                        <button
                          type="button"
                          onClick={() => removeFileAt(idx)}
                          aria-label={`Remove ${f.name}`}
                          className="ml-0.5 rounded-full p-0.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
                        >
                          <X className="size-3" />
                        </button>
                      </motion.span>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="up-category" className="mb-1.5 block text-xs font-medium text-foreground">
                Category
              </label>
              <input
                id="up-category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g. HR, Finance, Operations"
                className={inputClass}
              />
              {categories.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {categories.slice(0, 5).map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setCategory(c)}
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors ${
                        category === c
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-surface-2 text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      {c}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label htmlFor="up-tags" className="mb-1.5 block text-xs font-medium text-foreground">
                Tags <span className="font-normal text-muted-foreground">(optional, comma-separated)</span>
              </label>
              <input
                id="up-tags"
                value={tagsInput}
                onChange={(e) => setTagsInput(e.target.value)}
                placeholder="policy, 2026, handbook"
                className={inputClass}
              />
            </div>
          </div>

          <div>
            <label htmlFor="up-description" className="mb-1.5 block text-xs font-medium text-foreground">
              Short description <span className="font-normal text-muted-foreground">(optional)</span>
            </label>
            <input
              id="up-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this file for?"
              className={inputClass}
            />
          </div>

          <fieldset className="rounded-2xl border border-border bg-surface p-4">
            <legend className="px-1 text-xs font-semibold text-foreground">Who can access this document?</legend>
            <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
              {[
                {
                  id: 'company' as const,
                  title: 'Entire company',
                  desc: 'All active members can open and ask AI about it.',
                  icon: Building2,
                },
                {
                  id: 'department' as const,
                  title: 'Department only',
                  desc: 'Visible only to members of one team.',
                  icon: Users,
                },
                {
                  id: 'restricted' as const,
                  title: 'Selected people',
                  desc: 'Private to you and people you share with.',
                  icon: Lock,
                },
              ].map((item) => {
                const Icon = item.icon
                const active = scope === item.id
                return (
                  <label
                    key={item.id}
                    className={`relative cursor-pointer rounded-xl border p-3.5 transition-all duration-150 ${
                      active
                        ? 'border-foreground bg-surface-elevated shadow-sm ring-2 ring-foreground/10'
                        : 'border-border-strong bg-surface-elevated/60 hover:border-foreground/50 hover:bg-surface-elevated'
                    }`}
                  >
                    <input
                      type="radio"
                      className="sr-only"
                      checked={active}
                      onChange={() => setScope(item.id)}
                    />
                    <span className="flex items-center justify-between gap-2 text-xs font-semibold text-foreground">
                      <span className="flex items-center gap-2">
                        <Icon className="size-3.5" /> {item.title}
                      </span>
                      {active && (
                        <span className="grid size-4 place-items-center rounded-full bg-primary text-primary-foreground">
                          <Check className="size-2.5" />
                        </span>
                      )}
                    </span>
                    <span className="mt-1.5 block text-[11px] leading-relaxed text-muted-foreground">
                      {item.desc}
                    </span>
                  </label>
                )
              })}
            </div>

            <SmoothCollapse open={scope === 'department'}>
              <div className="mt-3">
                <label className="mb-1.5 block text-xs font-medium text-foreground">Select Department</label>
                <SmoothSelect
                  value={deptId === '' ? '' : String(deptId)}
                  onChange={(val) => setDeptId(val ? Number(val) : '')}
                  options={departmentOptions}
                  placeholder="Choose department…"
                  ariaLabel="Select department"
                />
              </div>
            </SmoothCollapse>

            <div className="mt-3">
              <label className="mb-1.5 block text-xs font-medium text-foreground">Sensitivity clearance</label>
              <SmoothSelect<'standard' | 'internal' | 'confidential'>
                value={sensitivity}
                onChange={setSensitivity}
                ariaLabel="Sensitivity clearance"
                options={[
                  { value: 'standard', label: 'Standard', description: 'Follows scope (all roles incl. viewers)' },
                  { value: 'internal', label: 'Internal (Employees+)', description: 'Hidden from read-only viewers' },
                  ...(canSetConfidential
                    ? [{ value: 'confidential' as const, label: 'Confidential (Admin Only)', description: 'Locked to admins & explicit grants' }]
                    : []),
                ]}
              />
            </div>
          </fieldset>

          <label className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-border bg-surface px-3.5 py-2.5 text-xs text-foreground transition-colors hover:bg-surface-2">
            <span className="flex items-center gap-2.5">
              <Sparkles className="size-4 text-muted-foreground" />
              <span>
                <span className="block font-medium text-foreground">Official reference document</span>
                <span className="block text-[11px] text-muted-foreground">
                  Prioritize this file as a verified source when answering team questions
                </span>
              </span>
            </span>
            <span className="relative inline-flex shrink-0 items-center">
              <input
                type="checkbox"
                checked={isOkf}
                onChange={(e) => setIsOkf(e.target.checked)}
                className="sr-only"
              />
              <span
                className={`flex h-5 w-9 items-center rounded-full p-0.5 transition-colors duration-200 ${
                  isOkf ? 'bg-primary' : 'bg-border-strong'
                }`}
              >
                <span
                  className={`size-4 rounded-full bg-background shadow-xs transition-transform duration-200 ${
                    isOkf ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </span>
            </span>
          </label>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <span className="text-xs text-muted-foreground">
              {files.length === 0
                ? 'Choose at least one file to continue'
                : files.length === 1
                ? `Ready to upload: ${files[0].name}`
                : `${files.length} files queued for background preparation`}
            </span>
            <button type="submit" disabled={files.length === 0} className={primaryBtn}>
              <Upload className="size-3.5" />
              {files.length > 1 ? `Upload ${files.length} documents` : 'Upload document'}
            </button>
          </div>
        </form>
      </SmoothCollapse>
    </div>
  )
}

function PreviewModal({
  doc,
  onClose,
}: {
  doc: EnterpriseDoc
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

function VersionsModal({
  doc,
  onClose,
  onUpdated,
}: {
  doc: EnterpriseDoc
  onClose: () => void
  onUpdated: (doc: EnterpriseDoc) => void
}) {
  const [versions, setVersions] = useState<
    { id: number; version_number: number; filename: string; size: number; created_at: string }[]
  >([])
  const [loading, setLoading] = useState(true)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    workApi
      .versions(doc.id)
      .then(setVersions)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load versions.'))
      .finally(() => setLoading(false))
  }, [doc.id])

  useEffect(() => {
    load()
  }, [load])

  async function handleUpload(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    setUploading(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const updated = await workApi.newVersion(doc.id, form)
      toast.success('New version uploaded.')
      setFile(null)
      onUpdated(updated)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload new version.')
    } finally {
      setUploading(false)
    }
  }

  return (
    <SmoothDialogFrame
      onClose={onClose}
      maxWidthClass="max-w-lg"
      panelClassName="flex max-h-[85vh] flex-col p-6"
      ariaLabel={`Version history for ${doc.filename}`}
    >
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div className="flex min-w-0 items-center gap-2">
          <History className="size-4 shrink-0 text-foreground" />
          <h2 className="truncate text-sm font-semibold text-foreground">
            Version history: {displayTitle(doc.filename)}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto py-4">
        <form onSubmit={handleUpload} className="rounded-2xl border border-border bg-surface p-3.5">
          <p className="text-xs font-semibold text-foreground">Upload new version</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            The current file will be saved in version history.
          </p>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
            <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-xl border border-dashed border-border-strong bg-surface-elevated px-3 py-2 text-xs text-muted-foreground transition-colors hover:border-foreground">
              <input
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="sr-only"
              />
              <CloudUpload className="size-4 shrink-0 text-foreground" />
              <span className="truncate font-medium text-foreground">
                {file ? file.name : 'Choose replacement file…'}
              </span>
            </label>
            <button
              type="submit"
              disabled={uploading || !file}
              className={primaryBtn}
            >
              {uploading ? <Loader2 className="size-3 animate-spin" /> : <Upload className="size-3" />}
              Upload
            </button>
          </div>
          {error && <p className="mt-2 text-xs text-danger">{error}</p>}
        </form>

        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">Past versions</p>
          {loading ? (
            <p className="text-xs text-muted-foreground">Loading versions…</p>
          ) : versions.length === 0 ? (
            <p className="text-xs text-muted-foreground">No previous versions on file.</p>
          ) : (
            <ul className="space-y-2">
              {versions.map((v) => (
                <li
                  key={v.id}
                  className="flex items-center justify-between rounded-xl border border-border bg-surface-elevated p-3 text-xs"
                >
                  <div>
                    <span className="font-semibold text-foreground">Version {v.version_number}</span>
                    <p className="text-muted-foreground">
                      {v.filename} · {formatBytes(v.size)} · {formatDate(v.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="flex justify-end border-t border-border pt-3">
        <button type="button" onClick={onClose} className={ghostBtn}>
          Done
        </button>
      </div>
    </SmoothDialogFrame>
  )
}

function EditMetadataModal({
  doc,
  departments,
  onClose,
  onSaved,
}: {
  doc: EnterpriseDoc
  departments: Department[]
  onClose: () => void
  onSaved: (doc: EnterpriseDoc) => void
}) {
  const { user } = useAuth()
  const isCompanyAdmin = Boolean(user?.role === 'admin' || user?.is_platform_admin)
  const canSetConfidential = Boolean(isCompanyAdmin || (user?.is_dept_admin && doc.department === user.department_id))
  const [description, setDescription] = useState(doc.description || '')
  const [category, setCategory] = useState(doc.category || '')
  const [tagsInput, setTagsInput] = useState((doc.tags || []).join(', '))
  const [scope, setScope] = useState<EnterpriseDoc['access_scope']>(doc.access_scope)
  const [sensitivity, setSensitivity] = useState<'standard' | 'internal' | 'confidential'>(
    doc.sensitivity || 'standard',
  )
  const [legalHold, setLegalHold] = useState(Boolean(doc.legal_hold))
  const [deptId, setDeptId] = useState<number | ''>(doc.department ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSave(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      const tags = tagsInput
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
      const payload: Partial<EnterpriseDoc> = {
        description: description.trim(),
        category: category.trim(),
        tags,
        access_scope: scope,
        sensitivity,
        department: scope === 'department' && deptId ? Number(deptId) : null,
      }
      if (isCompanyAdmin) payload.legal_hold = legalHold
      const updated = await workApi.updateDoc(doc.id, payload)
      toast.success('Document updated.')
      onSaved(updated)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Update failed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <SmoothDialogFrame
      onClose={onClose}
      maxWidthClass="max-w-md"
      panelClassName="p-6"
      ariaLabel="Edit document details"
    >
      <div className="flex items-center justify-between border-b border-border pb-3">
        <h2 className="text-sm font-semibold text-foreground">Edit document details</h2>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>

      <form onSubmit={handleSave} className="mt-4 space-y-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-foreground">Description</label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className={inputClass}
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-foreground">Category</label>
          <input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className={inputClass}
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-foreground">Tags (comma separated)</label>
          <input
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            className={inputClass}
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-foreground">Who can view</label>
          <SmoothSelect<EnterpriseDoc['access_scope']>
            value={scope}
            onChange={setScope}
            ariaLabel="Access scope"
            options={[
              { value: 'company', label: 'Company-wide', description: 'All active team members' },
              { value: 'department', label: 'Department only', description: 'Restricted to one department' },
              { value: 'restricted', label: 'Restricted (selected people)', description: 'Only you and named recipients' },
            ]}
          />
        </div>

        <SmoothCollapse open={scope === 'department'}>
          <div>
            <label className="mb-1 block text-xs font-medium text-foreground">Department</label>
            <SmoothSelect
              value={deptId === '' ? '' : String(deptId)}
              onChange={(val) => setDeptId(val ? Number(val) : '')}
              ariaLabel="Department"
              placeholder="Select department…"
              options={[
                { value: '', label: 'Select department…' },
                ...departments.map((d) => ({ value: String(d.id), label: d.name })),
              ]}
            />
          </div>
        </SmoothCollapse>

        <div>
          <label className="mb-1 block text-xs font-medium text-foreground">Sensitivity clearance</label>
          <SmoothSelect<'standard' | 'internal' | 'confidential'>
            value={sensitivity}
            onChange={setSensitivity}
            ariaLabel="Sensitivity clearance"
            options={[
              { value: 'standard', label: 'Standard', description: 'All roles matching access scope' },
              { value: 'internal', label: 'Internal (Employees+)', description: 'Blocks viewer accounts' },
              ...(canSetConfidential
                ? [{ value: 'confidential' as const, label: 'Confidential (Admin Only)', description: 'Restricted to admins & explicit grants' }]
                : []),
            ]}
          />
        </div>

        {isCompanyAdmin && (
          <label className="flex cursor-pointer items-center justify-between rounded-xl border border-border bg-surface px-3 py-2 text-xs">
            <span className="font-medium text-foreground">Legal hold (prevent deletion)</span>
            <input
              type="checkbox"
              checked={legalHold}
              onChange={(e) => setLegalHold(e.target.checked)}
              className="size-4 rounded accent-primary"
            />
          </label>
        )}

        {error && <p className="text-xs text-danger">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className={ghostBtn}>
            Cancel
          </button>
          <button type="submit" disabled={saving} className={primaryBtn}>
            {saving ? <Loader2 className="size-3.5 animate-spin" /> : 'Save changes'}
          </button>
        </div>
      </form>
    </SmoothDialogFrame>
  )
}

function ShareDialog({ doc, onClose }: { doc: EnterpriseDoc; onClose: () => void }) {
  const [shares, setShares] = useState<DocumentShareRow[]>([])
  const [code, setCode] = useState('')
  const [company, setCompany] = useState<CompanyDirectory | null>(null)
  const [members, setMembers] = useState<MemberDirectory[]>([])
  const [selectedId, setSelectedId] = useState<number | ''>('')
  const [expiresDays, setExpiresDays] = useState<string>('')
  const [allowPii, setAllowPii] = useState(false)
  const [loading, setLoading] = useState(true)
  const [searching, setSearching] = useState(false)
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    shareApi
      .list(doc.id)
      .then(setShares)
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Could not load access.'))
      .finally(() => setLoading(false))
  }, [doc.id])

  useEffect(() => {
    load()
  }, [load])

  async function findCompany(e: FormEvent) {
    e.preventDefault()
    setCompany(null)
    setMembers([])
    setSelectedId('')
    setSearching(true)
    const normalized = code.trim().toUpperCase()
    try {
      const found = await companyApi.search(normalized)
      const people = await companyApi.members(found.access_code)
      setCompany(found)
      setMembers(people)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Company lookup failed.')
    } finally {
      setSearching(false)
    }
  }

  async function addShare(e: FormEvent) {
    e.preventDefault()
    if (!company || selectedId === '') return
    setAdding(true)
    try {
      const row = await shareApi.add(doc.id, {
        access_code: company.access_code,
        user_id: selectedId,
        ...(expiresDays ? { expires_in_days: Number(expiresDays) } : {}),
        ...(doc.contains_pii && allowPii ? { allow_pii: true } : {}),
      })
      setShares((prev) => [row, ...prev.filter((x) => x.user_id !== row.user_id)])
      setSelectedId('')
      toast.success('Access granted.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not grant access.')
    } finally {
      setAdding(false)
    }
  }

  async function revoke(id: number) {
    setRemoving(id)
    try {
      await shareApi.remove(doc.id, id)
      setShares((prev) => prev.filter((x) => x.user_id !== id))
      toast.success('Access revoked.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not revoke access.')
    } finally {
      setRemoving(null)
    }
  }

  return (
    <SmoothDialogFrame
      onClose={onClose}
      maxWidthClass="max-w-2xl"
      ariaLabel="Control document access"
    >
      <div className="flex items-start justify-between gap-3 border-b border-border p-5">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Share2 className="size-4 shrink-0" /> Control document access
          </p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{displayTitle(doc.filename)}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="space-y-4 p-5">
        <div className="rounded-2xl border border-border bg-surface p-4">
          <p className="text-xs font-semibold text-foreground">Find a registered company</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Enter a partner company code to grant specific people access to this document.
          </p>
          <form onSubmit={findCompany} className="mt-3 flex flex-col gap-2 sm:flex-row">
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              maxLength={8}
              placeholder="Company code, e.g. A7K2Q9XB"
              className={`${inputClass} uppercase`}
            />
            <button
              type="submit"
              disabled={searching || code.trim().length < 3}
              className={primaryBtn}
            >
              {searching ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}
              Find
            </button>
          </form>
        </div>

        <AnimatePresence>
          {company && (
            <motion.form
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.18, ease: EASE }}
              onSubmit={addShare}
              className="rounded-2xl border border-border-strong bg-surface-elevated p-4"
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold text-foreground">{company.name}</p>
                  <p className="text-[11px] text-muted-foreground">
                    Code {company.access_code} · {company.member_count} members
                  </p>
                </div>
                <Building2 className="size-4 text-muted-foreground" />
              </div>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <div className="flex-1">
                  <SmoothSelect
                    value={selectedId === '' ? '' : String(selectedId)}
                    onChange={(val) => setSelectedId(val ? Number(val) : '')}
                    placeholder="Choose employee…"
                    ariaLabel="Choose employee"
                    options={[
                      { value: '', label: 'Choose employee…' },
                      ...members.map((m) => ({
                        value: String(m.id),
                        label: `${m.full_name || `Member #${m.id}`}${m.title ? ` · ${m.title}` : ''}`,
                        badge: m.role,
                      })),
                    ]}
                  />
                </div>
                <button
                  type="submit"
                  disabled={adding || selectedId === ''}
                  className={primaryBtn}
                >
                  {adding ? <Loader2 className="size-3.5 animate-spin" /> : <UserPlus className="size-3.5" />}
                  Share
                </button>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
                <label className="flex items-center gap-2 text-muted-foreground">
                  <span>Expires:</span>
                  <select
                    value={expiresDays}
                    onChange={(e) => setExpiresDays(e.target.value)}
                    className="rounded-lg border border-border bg-surface px-2 py-1 text-xs text-foreground outline-none"
                  >
                    <option value="">Never</option>
                    <option value="1">1 day</option>
                    <option value="7">7 days</option>
                    <option value="30">30 days</option>
                  </select>
                </label>
                {doc.contains_pii && (
                  <label className="flex cursor-pointer items-center gap-1.5 text-warn">
                    <input
                      type="checkbox"
                      checked={allowPii}
                      onChange={(e) => setAllowPii(e.target.checked)}
                      className="size-3.5 rounded accent-primary"
                    />
                    <span>Admin override: allow sharing PII-flagged file</span>
                  </label>
                )}
              </div>
            </motion.form>
          )}
        </AnimatePresence>

        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Named people with access
          </p>
          {loading ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" /> Loading…
            </p>
          ) : shares.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border-strong px-4 py-4 text-center text-xs text-muted-foreground">
              No named recipients yet.
            </p>
          ) : (
            <ul className="max-h-52 space-y-2 overflow-y-auto pr-1">
              {shares.map((s) => (
                <li
                  key={s.user_id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface px-3.5 py-2.5"
                >
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-foreground">
                      {s.full_name || s.email}
                      {s.title ? ` · ${s.title}` : ''}
                    </p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {s.email} · {s.company_name || 'Company'}
                      {s.expires_at ? ` · Expires ${formatDate(s.expires_at)}` : ''}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => revoke(s.user_id)}
                    disabled={removing === s.user_id}
                    className={dangerBtn}
                  >
                    {removing === s.user_id ? (
                      <Loader2 className="size-3 animate-spin" />
                    ) : (
                      <Trash2 className="size-3" />
                    )}
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </SmoothDialogFrame>
  )
}

export default function DocumentsPage() {
  const { user } = useAuth()
  const {
    docsState,
    setDocsState,
    docsRevision,
    bumpDocsRevision,
    uploadJobs,
    dismissUploadJobs,
  } = useWorkspaceStore()
  const [docs, setDocs] = useState<EnterpriseDoc[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [pages, setPages] = useState(1)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const { query, category, selectedTag, sort, uploadOpen, page } = docsState
  const setPage = useCallback(
    (v: number | ((cur: number) => number)) =>
      setDocsState((s) => ({ ...s, page: typeof v === 'function' ? v(s.page) : v })),
    [setDocsState],
  )
  const setQuery = useCallback(
    (v: string) => setDocsState((s) => ({ ...s, query: v, page: 1 })),
    [setDocsState],
  )
  const setCategory = useCallback(
    (v: string) => setDocsState((s) => ({ ...s, category: v, page: 1 })),
    [setDocsState],
  )
  const setSelectedTag = useCallback(
    (v: string) => setDocsState((s) => ({ ...s, selectedTag: v, page: 1 })),
    [setDocsState],
  )
  const setSort = useCallback(
    (v: Sort) => setDocsState((s) => ({ ...s, sort: v })),
    [setDocsState],
  )
  const setUploadOpen = useCallback(
    (v: boolean | ((cur: boolean) => boolean)) =>
      setDocsState((s) => ({ ...s, uploadOpen: typeof v === 'function' ? v(s.uploadOpen) : v })),
    [setDocsState],
  )

  const [departments, setDepartments] = useState<Department[]>([])

  // Selection & Actions state
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [shareDoc, setShareDoc] = useState<EnterpriseDoc | null>(null)
  const [confirmDoc, setConfirmDoc] = useState<EnterpriseDoc | null>(null)
  const [confirmBatch, setConfirmBatch] = useState(false)
  const [previewDoc, setPreviewDoc] = useState<EnterpriseDoc | null>(null)
  const [versionsDoc, setVersionsDoc] = useState<EnterpriseDoc | null>(null)
  const [editDoc, setEditDoc] = useState<EnterpriseDoc | null>(null)
  const [ephemeralNotice, setEphemeralNotice] = useState<string | null>(null)
  const shownEphemeralIdsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    for (const job of uploadJobs) {
      const notice = job.doc?.ephemeral_notice
      if (notice && !shownEphemeralIdsRef.current.has(job.id)) {
        shownEphemeralIdsRef.current.add(job.id)
        setEphemeralNotice(notice)
      }
    }
  }, [uploadJobs])

  const [busy, setBusy] = useState<Set<number>>(new Set())
  const [downloadedIds, setDownloadedIds] = useState<Set<number>>(new Set())
  const [actionError, setActionError] = useState('')

  const load = useCallback((targetPage = 1) => {
    setLoading(true)
    setLoadError('')
    workApi
      .documents(targetPage, 50)
      .then((res) => {
        setDocs(res.results || [])
        setTotalCount(res.count || 0)
        setPage(res.page || 1)
        setPages(res.pages || 1)
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : 'Could not load documents.'))
      .finally(() => setLoading(false))
  }, [])

  const refreshSilent = useCallback((targetPage = 1) => {
    workApi
      .documents(targetPage, 50)
      .then((res) => {
        setDocs(res.results || [])
        setTotalCount(res.count || 0)
        setPage(res.page || 1)
        setPages(res.pages || 1)
      })
      .catch(() => {})
  }, [])

  // Poll quietly every 2.5s while any document is in 'pending' indexing status
  const hasPending = useMemo(() => docs.some((d) => d.indexing_status === 'pending'), [docs])
  useEffect(() => {
    if (!hasPending) return
    const interval = setInterval(() => {
      refreshSilent(page)
    }, 2500)
    return () => clearInterval(interval)
  }, [hasPending, page, refreshSilent])

  // Refresh immediately when background uploads finish or change indexing state.
  useEffect(() => {
    if (docsRevision > 0) {
      refreshSilent(page)
    }
  }, [docsRevision, page, refreshSilent])

  useEffect(() => {
    load(1)
    companyApi2.departments().then(setDepartments).catch(() => setDepartments([]))
  }, [load])

  const categories = useMemo(
    () => [...new Set(docs.map((d) => d.category).filter(Boolean))].sort(),
    [docs],
  )

  const allTags = useMemo(() => {
    const s = new Set<string>()
    for (const d of docs) {
      if (Array.isArray(d.tags)) {
        for (const t of d.tags) if (t) s.add(t)
      }
    }
    return [...s].sort()
  }, [docs])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return docs
      .filter((d) => {
        if (category && d.category !== category) return false
        if (selectedTag && (!d.tags || !d.tags.includes(selectedTag))) return false
        if (q) {
          const tagsStr = (d.tags || []).join(' ')
          const target = `${d.filename} ${d.description} ${d.category} ${tagsStr}`.toLowerCase()
          if (!target.includes(q)) return false
        }
        return true
      })
      .sort((a, b) => {
        if (sort === 'name') return displayTitle(a.filename).localeCompare(displayTitle(b.filename))
        if (sort === 'downloads') return b.downloads - a.downloads
        if (sort === 'size') return b.size - a.size
        return +new Date(b.created_at) - +new Date(a.created_at)
      })
  }, [docs, query, category, selectedTag, sort])

  const setBusyFor = (id: number, val: boolean) =>
    setBusy((prev) => {
      const n = new Set(prev)
      val ? n.add(id) : n.delete(id)
      return n
    })

  async function download(doc: EnterpriseDoc) {
    setActionError('')
    setBusyFor(doc.id, true)
    try {
      await downloadOwnDocument(doc.id, doc.filename)
      setDocs((prev) =>
        prev.map((d) => (d.id === doc.id ? { ...d, downloads: d.downloads + 1 } : d)),
      )
      setDownloadedIds((prev) => new Set(prev).add(doc.id))
      window.setTimeout(() => {
        setDownloadedIds((prev) => {
          const next = new Set(prev)
          next.delete(doc.id)
          return next
        })
      }, 2200)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Download failed.')
    } finally {
      setBusyFor(doc.id, false)
    }
  }

  async function reviewDoc(doc: EnterpriseDoc, action: 'submit' | 'approve' | 'reject' | 'archive') {
    setBusyFor(doc.id, true)
    try {
      const updated = await workApi.reviewDoc(doc.id, { action })
      setDocs((prev) => prev.map((d) => (d.id === doc.id ? updated : d)))
      toast.success(`Document ${action === 'approve' ? 'approved' : action === 'reject' ? 'returned to draft' : 'updated'}.`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Review action failed.')
    } finally {
      setBusyFor(doc.id, false)
    }
  }

  async function retryIndex(doc: EnterpriseDoc) {
    setBusyFor(doc.id, true)
    try {
      const updated = await workApi.reindex(doc.id)
      setDocs((prev) => prev.map((d) => (d.id === doc.id ? updated : d)))
      toast.success(`Reindexing triggered for "${doc.filename}".`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Reindexing failed.')
    } finally {
      setBusyFor(doc.id, false)
    }
  }

  async function remove(doc: EnterpriseDoc) {
    setBusyFor(doc.id, true)
    try {
      await workApi.remove(doc.id)
      setDocs((prev) => prev.filter((d) => d.id !== doc.id))
      setSelectedIds((prev) => {
        const n = new Set(prev)
        n.delete(doc.id)
        return n
      })
      toast.success('Document deleted.')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not delete document.')
    } finally {
      setBusyFor(doc.id, false)
      setConfirmDoc(null)
    }
  }

  async function batchDelete() {
    if (selectedIds.size === 0) return
    const ids = Array.from(selectedIds)
    try {
      await Promise.all(ids.map((id) => workApi.remove(id)))
      setDocs((prev) => prev.filter((d) => !selectedIds.has(d.id)))
      setSelectedIds(new Set())
      toast.success(`${ids.length} documents deleted.`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Batch delete encountered errors.')
    } finally {
      setConfirmBatch(false)
    }
  }

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === visible.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(visible.map((d) => d.id)))
    }
  }

  if (!user) return null
  const editor = user.role === 'admin' || user.role === 'employee'

  return (
    <div className="pb-8">
      <header className="flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className={eyebrow}>Employer workspace</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.05em] sm:text-4xl">
            Your team&apos;s <span className="font-serif font-normal italic">vault.</span>
          </h1>
          <p className="mt-2 max-w-xl text-xs leading-relaxed text-muted-foreground">
            Store company knowledge, control access by person or department, and collaborate with registered partners.
          </p>
        </div>
        {editor && (
          <button
            type="button"
            onClick={() => setUploadOpen((v) => !v)}
            className={primaryBtn}
          >
            <Upload className="size-3.5" /> Upload document
          </button>
        )}
      </header>

      {/* Stats Cards */}
      <section className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-2xl border border-border bg-surface-elevated p-4 shadow-2xs transition-shadow hover:shadow-sm">
          <p className="text-[11px] uppercase tracking-[0.1em] text-muted-foreground">Documents</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">{totalCount || docs.length}</p>
        </div>
        <div className="rounded-2xl border border-border bg-surface-elevated p-4 shadow-2xs transition-shadow hover:shadow-sm">
          <p className="text-[11px] uppercase tracking-[0.1em] text-muted-foreground">Private</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">
            {docs.filter((d) => d.access_scope === 'restricted').length}
          </p>
        </div>
        <div className="rounded-2xl border border-border bg-surface-elevated p-4 shadow-2xs transition-shadow hover:shadow-sm">
          <p className="text-[11px] uppercase tracking-[0.1em] text-muted-foreground">Search-ready</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">
            {docs.filter((d) => d.indexing_status !== 'pending' && d.indexing_status !== 'failed').length}
          </p>
        </div>
        <div className="rounded-2xl border border-border bg-surface-elevated p-4 shadow-2xs transition-shadow hover:shadow-sm">
          <p className="text-[11px] uppercase tracking-[0.1em] text-muted-foreground">Downloads</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">
            {docs.reduce((n, d) => n + (d.downloads || 0), 0)}
          </p>
        </div>
      </section>

      {editor && (
        <section className="mt-5">
          <UploadPanel
            open={uploadOpen}
            onToggle={() => setUploadOpen((v) => !v)}
            categories={categories}
            departments={departments}
            onUploaded={(d) => {
              setDocs((prev) => [d, ...prev])
              setTotalCount((c) => c + 1)
              bumpDocsRevision()
            }}
          />
        </section>
      )}

      <AnimatePresence>
        {uploadJobs.length > 0 && (
          <motion.section
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2, ease: EASE }}
            className="mt-4 rounded-2xl border border-border bg-surface-elevated p-4 shadow-xs"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs font-medium text-foreground">
                {uploadJobs.some((j) => j.status === 'queued' || j.status === 'uploading' || j.status === 'indexing') ? (
                  <Loader2 className="size-3.5 animate-spin text-info" />
                ) : (
                  <CheckCircle2 className="size-3.5 text-ok" />
                )}
                <span>
                  Document progress ({uploadJobs.filter((j) => j.status === 'ready').length}/{uploadJobs.length} ready)
                </span>
              </div>
              {!uploadJobs.some((j) => j.status === 'queued' || j.status === 'uploading') && (
                <button
                  type="button"
                  onClick={dismissUploadJobs}
                  className="text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  Clear list
                </button>
              )}
            </div>
            <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
              {uploadJobs.map((job) => {
                const pct =
                  job.status === 'ready'
                    ? 100
                    : job.status === 'indexing'
                    ? 75
                    : job.status === 'uploading'
                    ? 40
                    : job.status === 'failed'
                    ? 100
                    : 15
                const stageLabel =
                  job.status === 'queued'
                    ? 'Queued'
                    : job.status === 'uploading'
                    ? 'Step 1/3 · Uploading'
                    : job.status === 'indexing'
                    ? 'Step 2/3 · Reading & preparing'
                    : job.status === 'ready'
                    ? 'Step 3/3 · Ready to search'
                    : job.error || 'Failed'
                const barColor =
                  job.status === 'ready'
                    ? 'bg-emerald-500'
                    : job.status === 'failed'
                    ? 'bg-rose-500'
                    : job.status === 'indexing'
                    ? 'bg-amber-500'
                    : 'bg-sky-500'
                return (
                  <div
                    key={job.id}
                    className="rounded-xl border border-border bg-surface p-3 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                        {job.filename}
                      </span>
                      <span
                        className={`shrink-0 text-[11px] font-medium ${
                          job.status === 'ready'
                            ? 'text-ok'
                            : job.status === 'failed'
                            ? 'text-danger'
                            : job.status === 'indexing'
                            ? 'text-warn'
                            : 'text-info'
                        }`}
                      >
                        {stageLabel}
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                      <motion.div
                        initial={{ width: '8%' }}
                        animate={{ width: `${pct}%` }}
                        transition={{ duration: 0.35, ease: EASE }}
                        className={`h-full rounded-full ${barColor}`}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      {/* Filter and search bar */}
      <section className="mt-6 space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex h-11 flex-1 items-center rounded-xl border border-border-strong bg-surface-elevated transition-colors focus-within:border-foreground">
            <Search className="absolute left-3.5 size-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search documents"
              placeholder="Search by title, description, category, tags…"
              className="h-full w-full bg-transparent pl-10 pr-4 text-xs text-foreground outline-none placeholder:text-muted-foreground"
            />
          </div>
          <div className="sm:w-48">
            <SmoothSelect
              value={category}
              onChange={setCategory}
              ariaLabel="Filter by category"
              options={[
                { value: '', label: 'All categories' },
                ...categories.map((c) => ({ value: c, label: c })),
              ]}
            />
          </div>
          <div className="sm:w-44">
            <SmoothSelect<Sort>
              value={sort}
              onChange={setSort}
              ariaLabel="Sort documents"
              options={[
                { value: 'recent', label: 'Most recent' },
                { value: 'downloads', label: 'Most downloaded' },
                { value: 'size', label: 'Largest size' },
                { value: 'name', label: 'Name A–Z' },
              ]}
            />
          </div>
        </div>

        {/* Tag Filter Chips */}
        {allTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-[11px] font-medium text-muted-foreground">Tags:</span>
            <button
              type="button"
              onClick={() => setSelectedTag('')}
              className={`rounded-full px-2.5 py-0.5 text-[11px] transition-colors ${
                !selectedTag ? 'bg-primary text-primary-foreground' : 'bg-surface-2 text-muted-foreground hover:text-foreground'
              }`}
            >
              All
            </button>
            {allTags.map((tg) => (
              <button
                key={tg}
                type="button"
                onClick={() => setSelectedTag(selectedTag === tg ? '' : tg)}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] transition-colors ${
                  selectedTag === tg
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-surface-2 text-muted-foreground hover:text-foreground'
                }`}
              >
                <Tag className="size-2.5" />
                {tg}
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Batch toolbar */}
      {editor && visible.length > 0 && (
        <div className="mt-4 flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-2 text-xs">
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={selectedIds.size > 0 && selectedIds.size === visible.length}
              onChange={toggleSelectAll}
              className="size-4 rounded accent-primary"
            />
            <span className="text-muted-foreground">
              {selectedIds.size > 0
                ? `${selectedIds.size} of ${visible.length} selected`
                : 'Select all'}
            </span>
          </div>
          {selectedIds.size > 0 && (
            <button
              type="button"
              onClick={() => setConfirmBatch(true)}
              className={dangerBtn}
            >
              <Trash2 className="size-3" /> Delete selected ({selectedIds.size})
            </button>
          )}
        </div>
      )}

      {actionError && (
        <p
          role="alert"
          className="mt-4 flex items-center gap-2 rounded-xl bg-danger-soft px-4 py-3 text-xs text-danger"
        >
          <AlertCircle className="size-4" />
          {actionError}
        </p>
      )}

      {/* Document List */}
      <section className="mt-4">
        {loading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((skeleton) => (
              <div
                key={skeleton}
                className="h-24 animate-pulse rounded-2xl border border-border bg-surface-elevated/80"
              />
            ))}
          </div>
        ) : loadError ? (
          <div className="rounded-3xl border border-danger/30 bg-danger-soft p-10 text-center">
            <p className="text-xs text-danger">{loadError}</p>
            <button onClick={() => load(page)} className={`mt-4 ${ghostBtn}`}>
              Try again
            </button>
          </div>
        ) : visible.length === 0 ? (
          <div className="rounded-3xl border border-border bg-surface-elevated p-12 text-center">
            <p className="font-serif text-xl italic">No documents found.</p>
            <p className="mt-1 text-xs text-muted-foreground">Upload a document or adjust your filters.</p>
          </div>
        ) : (
          <ul className="space-y-3">
            {visible.map((doc) => {
              const isBusy = busy.has(doc.id)
              const justDownloaded = downloadedIds.has(doc.id)
              const statusText =
                doc.indexing_status === 'pending'
                  ? 'Preparing for search…'
                  : doc.indexing_status === 'failed'
                  ? 'Needs retry'
                  : 'Search-ready'
              return (
                <li
                  key={doc.id}
                  className="rounded-2xl border border-border bg-surface-elevated p-4 shadow-2xs transition-all duration-150 hover:border-border-strong hover:shadow-md"
                >
                  <div className="flex flex-col gap-3.5 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex min-w-0 items-start gap-3">
                      {editor && (
                        <input
                          type="checkbox"
                          checked={selectedIds.has(doc.id)}
                          onChange={() => toggleSelect(doc.id)}
                          className="mt-1 size-4 rounded accent-primary"
                        />
                      )}
                      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-surface-2">
                        <FileText className="size-4 text-muted-foreground" />
                      </span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h2
                            className="truncate text-sm font-semibold text-foreground"
                            title={doc.filename}
                          >
                            {displayTitle(doc.filename)}
                          </h2>
                          <AccessBadge
                            scope={doc.access_scope}
                            deptName={doc.department_name}
                          />
                          <IndexingBadge
                            status={doc.indexing_status}
                            onRetry={() => retryIndex(doc)}
                          />
                          {doc.version > 1 && (
                            <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                              v{doc.version}
                            </span>
                          )}
                          {doc.sensitivity && doc.sensitivity !== 'standard' && (
                            <span
                              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                                doc.sensitivity === 'confidential'
                                  ? 'bg-danger-soft text-danger'
                                  : 'bg-warn-soft text-warn'
                              }`}
                            >
                              <Shield className="size-2.5" />
                              {doc.sensitivity}
                            </span>
                          )}
                          {doc.status && doc.status !== 'approved' && (
                            <span className="rounded-full bg-info-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-info">
                              {doc.status.replace('_', ' ')}
                            </span>
                          )}
                          {doc.contains_pii && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[10px] font-semibold text-warn">
                              <ShieldAlert className="size-2.5" /> PII
                            </span>
                          )}
                          {doc.legal_hold && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft px-2 py-0.5 text-[10px] font-semibold text-danger">
                              <Lock className="size-2.5" /> Legal Hold
                            </span>
                          )}
                        </div>

                        {doc.description && (
                          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                            {doc.description}
                          </p>
                        )}

                        <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-muted-foreground">
                          <span className="rounded-full bg-surface-2 px-2 py-0.5 font-medium text-foreground/85">
                            {doc.category || 'General'}
                          </span>
                          <span>{formatBytes(doc.size)}</span>
                          <span>·</span>
                          <span
                            className={
                              doc.indexing_status === 'failed'
                                ? 'font-medium text-danger'
                                : doc.indexing_status === 'pending'
                                ? 'font-medium text-warn'
                                : 'text-ok'
                            }
                          >
                            {statusText}
                          </span>
                          <span>·</span>
                          <span>{formatDate(doc.created_at)}</span>
                          {doc.downloads > 0 && (
                            <>
                              <span>·</span>
                              <span>{doc.downloads} downloads</span>
                            </>
                          )}

                          {doc.tags && doc.tags.length > 0 && (
                            <>
                              <span>·</span>
                              <div className="flex flex-wrap gap-1">
                                {doc.tags.map((tg) => (
                                  <span
                                    key={tg}
                                    className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] text-muted-foreground"
                                  >
                                    #{tg}
                                  </span>
                                ))}
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex shrink-0 flex-wrap items-center gap-1.5 pt-1 lg:pt-0">
                      <button
                        type="button"
                        onClick={() => setPreviewDoc(doc)}
                        className={ghostBtn}
                        title="Preview document content"
                      >
                        <Eye className="size-3.5" /> Preview
                      </button>
                      <button
                        type="button"
                        onClick={() => download(doc)}
                        disabled={isBusy}
                        className={
                          justDownloaded
                            ? `inline-flex items-center justify-center gap-1.5 rounded-full border border-ok/35 bg-ok-soft px-3 py-1.5 text-xs font-medium text-ok transition-all duration-150 ${focusRing}`
                            : ghostBtn
                        }
                      >
                        {isBusy ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : justDownloaded ? (
                          <Check className="size-3.5" />
                        ) : (
                          <Download className="size-3.5" />
                        )}
                        {isBusy ? 'Preparing…' : justDownloaded ? 'Downloaded ✓' : 'Download'}
                      </button>
                      {editor && (
                        <>
                          <button
                            type="button"
                            onClick={() => setVersionsDoc(doc)}
                            className={ghostBtn}
                            title="Version history"
                          >
                            <History className="size-3.5" /> Versions
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditDoc(doc)}
                            className={ghostBtn}
                            title="Edit details"
                          >
                            <Pencil className="size-3.5" /> Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => setShareDoc(doc)}
                            disabled={isBusy}
                            className={ghostBtn}
                          >
                            <Share2 className="size-3.5" /> Share
                          </button>
                          {doc.status === 'in_review' &&
                            (user?.role === 'admin' ||
                              user?.is_platform_admin ||
                              (user?.is_dept_admin && doc.department === user.department_id)) && (
                              <>
                                <button
                                  type="button"
                                  onClick={() => reviewDoc(doc, 'approve')}
                                  disabled={isBusy}
                                  className={ghostBtn}
                                  title="Approve document"
                                >
                                  <Check className="size-3.5 text-ok" /> Approve
                                </button>
                                <button
                                  type="button"
                                  onClick={() => reviewDoc(doc, 'reject')}
                                  disabled={isBusy}
                                  className={ghostBtn}
                                  title="Return to draft"
                                >
                                  <X className="size-3.5 text-danger" /> Reject
                                </button>
                              </>
                            )}
                          <button
                            type="button"
                            onClick={() => setConfirmDoc(doc)}
                            disabled={isBusy || Boolean(doc.legal_hold)}
                            title={doc.legal_hold ? 'Document is under legal hold' : 'Delete document'}
                            className={dangerBtn}
                          >
                            <Trash2 className="size-3.5" /> Delete
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}

        {/* Pagination controls */}
        {pages > 1 && (
          <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => load(page - 1)}
              className={ghostBtn}
            >
              Previous
            </button>
            <span className="text-xs text-muted-foreground">
              Page {page} of {pages} ({totalCount} total documents)
            </span>
            <button
              type="button"
              disabled={page >= pages || loading}
              onClick={() => load(page + 1)}
              className={ghostBtn}
            >
              Next
            </button>
          </div>
        )}
      </section>

      {/* Modals */}
      <AnimatePresence>
        {shareDoc && <ShareDialog key={`share-${shareDoc.id}`} doc={shareDoc} onClose={() => setShareDoc(null)} />}
        {previewDoc && <PreviewModal key={`preview-${previewDoc.id}`} doc={previewDoc} onClose={() => setPreviewDoc(null)} />}
        {versionsDoc && (
          <VersionsModal
            key={`versions-${versionsDoc.id}`}
            doc={versionsDoc}
            onClose={() => setVersionsDoc(null)}
            onUpdated={(updated) => {
              setDocs((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
            }}
          />
        )}
        {editDoc && (
          <EditMetadataModal
            key={`edit-${editDoc.id}`}
            doc={editDoc}
            departments={departments}
            onClose={() => setEditDoc(null)}
            onSaved={(updated) => {
              setDocs((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
            }}
          />
        )}
        {ephemeralNotice && (
          <SmoothDialogFrame onClose={() => setEphemeralNotice(null)} maxWidthClass="max-w-md">
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-warn-soft text-warn">
                  <AlertCircle className="size-4" aria-hidden />
                </span>
                <div>
                  <h3 className="text-sm font-semibold text-foreground">Temporary Beta Upload</h3>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{ephemeralNotice}</p>
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setEphemeralNotice(null)}
                  className="rounded-full bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
                >
                  Understood
                </button>
              </div>
            </div>
          </SmoothDialogFrame>
        )}
      </AnimatePresence>

      {/* Confirm Single Delete */}
      <ConfirmDialog
        open={!!confirmDoc}
        title="Delete document"
        message={
          confirmDoc
            ? `Delete “${displayTitle(confirmDoc.filename)}”? This cannot be undone.`
            : ''
        }
        confirmText="Delete"
        danger={true}
        loading={confirmDoc ? busy.has(confirmDoc.id) : false}
        onConfirm={() => confirmDoc && remove(confirmDoc)}
        onCancel={() => setConfirmDoc(null)}
      />

      {/* Confirm Batch Delete */}
      <ConfirmDialog
        open={confirmBatch}
        title="Delete selected documents"
        message={`Delete ${selectedIds.size} selected documents? This cannot be undone.`}
        confirmText="Delete all"
        danger={true}
        loading={false}
        onConfirm={batchDelete}
        onCancel={() => setConfirmBatch(false)}
      />
    </div>
  )
}
