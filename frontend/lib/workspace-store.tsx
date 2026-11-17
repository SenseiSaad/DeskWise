'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from 'react'
import { useAuth } from '@/lib/auth'
import { BETA_LOCKED_MODE } from '@/lib/beta'
import {
  askStream,
  chatApi,
  workApi,
  type Artifact,
  type ChatMode,
  type Conversation,
  type EnterpriseDoc,
  type LlmStatus,
  type Role,
  type WorkflowResult,
} from '@/lib/api'
import { toast } from '@/components/toaster'

export type WorkspaceChatMessage = {
  id?: number
  role: 'user' | 'assistant'
  content: string
  mode?: ChatMode
  question?: string
  sources?: string[]
  rating?: number | null
  error?: boolean
  flag?: { message: string; categories: string[] }
  workflow?: WorkflowResult
  artifacts?: Artifact[]
  missingFields?: string[]
}

export interface UploadJob {
  id: string
  filename: string
  size: number
  status: 'queued' | 'uploading' | 'indexing' | 'ready' | 'failed'
  docId?: number
  doc?: EnterpriseDoc
  error?: string
  createdAt: number
}

export interface UploadDraft {
  category: string
  description: string
  tagsInput: string
  isOkf: boolean
  accessScope: 'company' | 'department' | 'restricted'
  departmentId: number | ''
}

export interface UploadMeta {
  category: string
  description: string
  tags: string[]
  isOkf: boolean
  accessScope: 'company' | 'department' | 'restricted'
  departmentId: number | ''
}

export type DocSort = 'recent' | 'name' | 'size' | 'downloads'

export interface DocsPageState {
  query: string
  category: string
  selectedTag: string
  sort: DocSort
  uploadOpen: boolean
  page: number
  uploadDraft: UploadDraft
}

export interface AuditPageState {
  search: string
  actionFilter: string
  actorFilter: string
  page: number
}

export interface MembersPageDraft {
  fullName: string
  title: string
  departmentId: number | ''
  email: string
  password: string
  role: Role
}

export interface OverviewPageDraft {
  showAnnounceModal: boolean
  announceTitle: string
  announceBody: string
}

export type SettingsTab = 'company' | 'plan' | 'ai'

export interface SettingsPageState {
  tab: SettingsTab
}

interface PersistedWorkspaceSnapshot {
  docsState?: DocsPageState
  auditState?: AuditPageState
  membersDraft?: MembersPageDraft
  overviewDraft?: OverviewPageDraft
  settingsState?: SettingsPageState
  chat?: {
    currentConversationId: number | null
    input: string
    mode: ChatMode
    modeInit: boolean
    sidebarOpen: boolean
    messages: WorkspaceChatMessage[]
  }
}

const DEFAULT_UPLOAD_DRAFT: UploadDraft = {
  category: '',
  description: '',
  tagsInput: '',
  isOkf: false,
  accessScope: 'company',
  departmentId: '',
}

const DEFAULT_DOCS_STATE: DocsPageState = {
  query: '',
  category: '',
  selectedTag: '',
  sort: 'recent',
  uploadOpen: false,
  page: 1,
  uploadDraft: DEFAULT_UPLOAD_DRAFT,
}

const DEFAULT_AUDIT_STATE: AuditPageState = {
  search: '',
  actionFilter: 'all',
  actorFilter: 'all',
  page: 1,
}

const DEFAULT_MEMBERS_DRAFT: MembersPageDraft = {
  fullName: '',
  title: '',
  departmentId: '',
  email: '',
  password: '',
  role: 'viewer',
}

const DEFAULT_OVERVIEW_DRAFT: OverviewPageDraft = {
  showAnnounceModal: false,
  announceTitle: '',
  announceBody: '',
}

const DEFAULT_SETTINGS_STATE: SettingsPageState = {
  tab: 'company',
}

interface WorkspaceStoreValue {
  // ---- Background upload + indexing queue ----
  stagedFiles: File[]
  setStagedFiles: Dispatch<SetStateAction<File[]>>
  uploadJobs: UploadJob[]
  docsRevision: number
  bumpDocsRevision: () => void
  enqueueUploads: (files: File[], meta: UploadMeta) => void
  dismissUploadJobs: () => void
  clearFinishedUploads: () => void

  // ---- Persistent section states ----
  docsState: DocsPageState
  setDocsState: Dispatch<SetStateAction<DocsPageState>>
  auditState: AuditPageState
  setAuditState: Dispatch<SetStateAction<AuditPageState>>
  membersDraft: MembersPageDraft
  setMembersDraft: Dispatch<SetStateAction<MembersPageDraft>>
  overviewDraft: OverviewPageDraft
  setOverviewDraft: Dispatch<SetStateAction<OverviewPageDraft>>
  settingsState: SettingsPageState
  setSettingsState: Dispatch<SetStateAction<SettingsPageState>>

  // ---- Persistent Ask AI chat + background stream ----
  chat: {
    messages: WorkspaceChatMessage[]
    setMessages: Dispatch<SetStateAction<WorkspaceChatMessage[]>>
    input: string
    setInput: Dispatch<SetStateAction<string>>
    streaming: boolean
    llm: LlmStatus | null
    mode: ChatMode
    setMode: Dispatch<SetStateAction<ChatMode>>
    modeInit: boolean
    setModeInit: Dispatch<SetStateAction<boolean>>
    conversations: Conversation[]
    currentConversationId: number | null
    sidebarOpen: boolean
    setSidebarOpen: Dispatch<SetStateAction<boolean>>
    loadingConv: boolean
    refreshLlmStatus: () => Promise<LlmStatus | null>
    refreshConversations: () => Promise<void>
    selectConversation: (id: number) => Promise<void>
    newChat: () => void
    deleteConversation: (id: number) => Promise<void>
    rateMessage: (idx: number, messageId: number, rating: 1 | -1) => Promise<void>
    send: (text?: string) => Promise<void>
    stop: () => void
  }
}

const WorkspaceStoreContext = createContext<WorkspaceStoreValue | null>(null)

function readSnapshot(storageKey: string): PersistedWorkspaceSnapshot | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(storageKey)
    if (!raw) return null
    return JSON.parse(raw) as PersistedWorkspaceSnapshot
  } catch {
    return null
  }
}

function writeSnapshot(storageKey: string, snapshot: PersistedWorkspaceSnapshot) {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(storageKey, JSON.stringify(snapshot))
  } catch {
    /* ignore storage quota / private-browsing errors */
  }
}

function isModeOnline(mode: ChatMode, status: LlmStatus): boolean {
  if (mode === 'online') return Boolean(status.online_api?.online)
  if (mode === 'gemini') return Boolean(status.gemini?.online)
  if (mode === 'selfhosted') return Boolean(status.selfhosted?.online)
  return Boolean(status.local?.online)
}

function pickInitialMode(status: LlmStatus): ChatMode {
  // Beta lockdown: start on the only selectable provider.
  if (BETA_LOCKED_MODE) return BETA_LOCKED_MODE
  if (status.provider === 'bedrock' && status.online_api?.online) return 'online'
  if (status.provider === 'gemini' && status.gemini?.online) return 'gemini'
  if (status.provider === 'selfhosted' && status.selfhosted?.online) return 'selfhosted'
  if (status.online_api?.online) return 'online'
  if (status.local?.online) return 'local'
  if (status.gemini?.online) return 'gemini'
  if (status.selfhosted?.online) return 'selfhosted'
  return 'online'
}

export function WorkspaceStoreProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const userKey = user ? `${user.id}:${user.company_id ?? 'none'}` : null
  const storageKey = userKey ? `deskwise_ws_${userKey}` : null

  const userKeyRef = useRef<string | null>(userKey)
  const hydratedKeyRef = useRef<string | null>(null)
  userKeyRef.current = userKey

  // ---- Per-section persistent state ----
  const [docsState, setDocsState] = useState<DocsPageState>(DEFAULT_DOCS_STATE)
  const [auditState, setAuditState] = useState<AuditPageState>(DEFAULT_AUDIT_STATE)
  const [membersDraft, setMembersDraft] = useState<MembersPageDraft>(DEFAULT_MEMBERS_DRAFT)
  const [overviewDraft, setOverviewDraft] = useState<OverviewPageDraft>(DEFAULT_OVERVIEW_DRAFT)
  const [settingsState, setSettingsState] = useState<SettingsPageState>(DEFAULT_SETTINGS_STATE)

  // ---- Background uploads + staged files ----
  const [stagedFiles, setStagedFiles] = useState<File[]>([])
  const [uploadJobs, setUploadJobs] = useState<UploadJob[]>([])
  const [docsRevision, setDocsRevision] = useState(0)
  const bumpDocsRevision = useCallback(() => setDocsRevision((n) => n + 1), [])

  interface QueuedTask {
    jobId: string
    file: File
    meta: UploadMeta
    expectedUserKey: string | null
  }
  const uploadQueueRef = useRef<QueuedTask[]>([])
  const activeWorkersRef = useRef(0)
  const batchNotifiedRef = useRef(false)

  // ---- Chat state ----
  const [messages, setMessages] = useState<WorkspaceChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [llm, setLlm] = useState<LlmStatus | null>(null)
  const [mode, setMode] = useState<ChatMode>(BETA_LOCKED_MODE ?? 'online')
  const [modeInit, setModeInit] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<number | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [loadingConv, setLoadingConv] = useState(false)

  const chatAbortRef = useRef<AbortController | null>(null)
  const streamingRef = useRef(false)
  streamingRef.current = streaming
  const modeRef = useRef<ChatMode>(mode)
  modeRef.current = mode
  const currentConvIdRef = useRef<number | null>(currentConversationId)
  currentConvIdRef.current = currentConversationId

  // Reset and rehydrate whenever user/company identity changes.
  useEffect(() => {
    // Abort any running chat stream from a prior session/tenant.
    chatAbortRef.current?.abort()
    chatAbortRef.current = null
    setStreaming(false)
    uploadQueueRef.current = []
    setUploadJobs([])
    setStagedFiles([])
    setConversations([])
    setLlm(null)

    if (!storageKey) {
      hydratedKeyRef.current = null
      setDocsState(DEFAULT_DOCS_STATE)
      setAuditState(DEFAULT_AUDIT_STATE)
      setMembersDraft(DEFAULT_MEMBERS_DRAFT)
      setOverviewDraft(DEFAULT_OVERVIEW_DRAFT)
      setSettingsState(DEFAULT_SETTINGS_STATE)
      setMessages([])
      setInput('')
      setCurrentConversationId(null)
      setMode(BETA_LOCKED_MODE ?? 'online')
      setModeInit(false)
      setSidebarOpen(true)
      return
    }

    const snap = readSnapshot(storageKey)
    setDocsState(snap?.docsState ? { ...DEFAULT_DOCS_STATE, ...snap.docsState, uploadDraft: { ...DEFAULT_UPLOAD_DRAFT, ...(snap.docsState.uploadDraft || {}) } } : DEFAULT_DOCS_STATE)
    setAuditState(snap?.auditState ? { ...DEFAULT_AUDIT_STATE, ...snap.auditState } : DEFAULT_AUDIT_STATE)
    setMembersDraft(snap?.membersDraft ? { ...DEFAULT_MEMBERS_DRAFT, ...snap.membersDraft } : DEFAULT_MEMBERS_DRAFT)
    setOverviewDraft(snap?.overviewDraft ? { ...DEFAULT_OVERVIEW_DRAFT, ...snap.overviewDraft } : DEFAULT_OVERVIEW_DRAFT)
    setSettingsState(snap?.settingsState ? { ...DEFAULT_SETTINGS_STATE, ...snap.settingsState } : DEFAULT_SETTINGS_STATE)

    if (snap?.chat) {
      setMessages(Array.isArray(snap.chat.messages) ? snap.chat.messages : [])
      setInput(snap.chat.input || '')
      setCurrentConversationId(snap.chat.currentConversationId ?? null)
      setMode(BETA_LOCKED_MODE ?? snap.chat.mode ?? 'online')
      setModeInit(Boolean(snap.chat.modeInit))
      setSidebarOpen(snap.chat.sidebarOpen !== false)
    } else {
      setMessages([])
      setInput('')
      setCurrentConversationId(null)
      setMode(BETA_LOCKED_MODE ?? 'online')
      setModeInit(false)
      setSidebarOpen(true)
    }

    hydratedKeyRef.current = storageKey
  }, [storageKey])

  // Persist snapshot to sessionStorage (strictly after hydrating current key).
  useEffect(() => {
    if (!storageKey || hydratedKeyRef.current !== storageKey) return
    // Strip heavy base64 or ephemeral streaming errors; preserve message content + artifacts metadata.
    const compactMessages = messages.slice(-50)
    writeSnapshot(storageKey, {
      docsState,
      auditState,
      membersDraft,
      overviewDraft,
      settingsState,
      chat: {
        currentConversationId,
        input,
        mode,
        modeInit,
        sidebarOpen,
        messages: compactMessages,
      },
    })
  }, [
    storageKey,
    docsState,
    auditState,
    membersDraft,
    overviewDraft,
    settingsState,
    currentConversationId,
    input,
    mode,
    modeInit,
    sidebarOpen,
    messages,
  ])

  // ---- Background upload workers (concurrency = 3) ----
  const pumpUploadQueue = useCallback((expectedKey: string | null) => {
    const MAX_CONCURRENT = 3
    while (activeWorkersRef.current < MAX_CONCURRENT && uploadQueueRef.current.length > 0) {
      const task = uploadQueueRef.current.shift()!
      if (task.expectedUserKey !== userKeyRef.current) continue

      activeWorkersRef.current += 1
      setUploadJobs((prev) =>
        prev.map((j) => (j.id === task.jobId ? { ...j, status: 'uploading' } : j)),
      )

      const form = new FormData()
      form.append('file', task.file)
      form.append('category', task.meta.category)
      form.append('description', task.meta.description)
      if (task.meta.tags.length > 0) {
        form.append('tags', task.meta.tags.join(', '))
      }
      form.append('is_okf', String(task.meta.isOkf))
      form.append('access_scope', task.meta.accessScope)
      if (task.meta.accessScope === 'department' && task.meta.departmentId !== '') {
        form.append('department_id', String(task.meta.departmentId))
      }

      workApi
        .upload(form)
        .then((created) => {
          if (userKeyRef.current !== expectedKey) return
          const nextStatus: UploadJob['status'] =
            created.indexing_status === 'ready'
              ? 'ready'
              : created.indexing_status === 'failed'
                ? 'failed'
                : 'indexing'
          setUploadJobs((prev) =>
            prev.map((j) =>
              j.id === task.jobId
                ? {
                    ...j,
                    status: nextStatus,
                    docId: created.id,
                    doc: created,
                    error: created.index_error || undefined,
                  }
                : j,
            ),
          )
          setDocsRevision((n) => n + 1)
        })
        .catch((err) => {
          if (userKeyRef.current !== expectedKey) return
          const msg = err instanceof Error ? err.message : 'Upload failed'
          setUploadJobs((prev) =>
            prev.map((j) => (j.id === task.jobId ? { ...j, status: 'failed', error: msg } : j)),
          )
          toast.error(`Failed to upload ${task.file.name}: ${msg}`)
        })
        .finally(() => {
          activeWorkersRef.current = Math.max(0, activeWorkersRef.current - 1)
          if (userKeyRef.current === expectedKey) {
            pumpUploadQueue(expectedKey)
          }
        })
    }
  }, [])

  const enqueueUploads = useCallback(
    (files: File[], meta: UploadMeta) => {
      if (!files.length) return
      const expectedKey = userKeyRef.current
      batchNotifiedRef.current = false
      const now = Date.now()
      const newJobs: UploadJob[] = files.map((file, idx) => {
        const jobId = `${now}_${idx}_${Math.random().toString(36).slice(2, 7)}`
        uploadQueueRef.current.push({
          jobId,
          file,
          meta: { ...meta, tags: [...meta.tags] },
          expectedUserKey: expectedKey,
        })
        return {
          id: jobId,
          filename: file.name,
          size: file.size,
          status: 'queued',
          createdAt: now,
        }
      })
      setUploadJobs((prev) => [...newJobs, ...prev].slice(0, 30))
      setStagedFiles([])
      toast.success(
        files.length === 1
          ? `Uploading "${files[0].name}" in the background…`
          : `Uploading ${files.length} documents in the background — you can switch tabs freely.`,
      )
      pumpUploadQueue(expectedKey)
    },
    [pumpUploadQueue],
  )

  const clearFinishedUploads = useCallback(() => {
    setUploadJobs((prev) => prev.filter((j) => j.status === 'queued' || j.status === 'uploading' || j.status === 'indexing'))
  }, [])

  const dismissUploadJobs = useCallback(() => {
    setUploadJobs((prev) => prev.filter((j) => j.status === 'queued' || j.status === 'uploading'))
  }, [])

  // Background indexing poller — stays alive across ALL workspace routes!
  const hasIndexingJobs = uploadJobs.some((j) => j.status === 'indexing')
  useEffect(() => {
    if (!user?.company_id || !hasIndexingJobs) return
    const expectedKey = userKeyRef.current

    const pollOnce = async () => {
      try {
        const res = await workApi.documents(1, 100)
        if (userKeyRef.current !== expectedKey) return
        const byId = new Map(res.results.map((d) => [d.id, d]))
        let anyChanged = false
        setUploadJobs((prev) =>
          prev.map((job) => {
            if (job.status !== 'indexing' || !job.docId) return job
            const fresh = byId.get(job.docId)
            if (!fresh) {
              // Document was deleted before indexing completed.
              anyChanged = true
              return { ...job, status: 'failed', error: 'Removed' }
            }
            if (fresh.indexing_status === 'ready') {
              anyChanged = true
              return { ...job, status: 'ready', doc: fresh }
            }
            if (fresh.indexing_status === 'failed') {
              anyChanged = true
              return { ...job, status: 'failed', doc: fresh, error: fresh.index_error || 'Indexing failed' }
            }
            return job
          }),
        )
        if (anyChanged) {
          setDocsRevision((n) => n + 1)
        }
      } catch {
        /* ignore transient polling failures */
      }
    }

    const id = window.setInterval(pollOnce, 1500)
    return () => window.clearInterval(id)
  }, [user?.company_id, hasIndexingJobs])

  // Notify once when all queued/uploading/indexing jobs complete.
  useEffect(() => {
    if (!uploadJobs.length) {
      batchNotifiedRef.current = false
      return
    }
    const stillBusy = uploadJobs.some(
      (j) => j.status === 'queued' || j.status === 'uploading' || j.status === 'indexing',
    )
    if (!stillBusy && !batchNotifiedRef.current) {
      batchNotifiedRef.current = true
      const readyCount = uploadJobs.filter((j) => j.status === 'ready').length
      if (readyCount > 0) {
        const latestReady = uploadJobs.find((j) => j.status === 'ready')
        toast.success(
          readyCount === 1 && latestReady
            ? `"${latestReady.filename}" indexed and ready for Ask AI!`
            : `${readyCount} documents indexed and ready for Ask AI!`,
        )
      }
    }
  }, [uploadJobs])

  // ---- Persistent Chat actions ----
  const refreshLlmStatus = useCallback(async () => {
    const expectedKey = userKeyRef.current
    try {
      const s = await workApi.llmStatus()
      if (userKeyRef.current !== expectedKey) return null
      setLlm(s)
      setMode((cur) => {
        if (!modeInit) {
          setModeInit(true)
          return pickInitialMode(s)
        }
        if (!isModeOnline(cur, s)) {
          return pickInitialMode(s)
        }
        return cur
      })
      return s
    } catch {
      return null
    }
  }, [modeInit])

  const refreshConversations = useCallback(async () => {
    const expectedKey = userKeyRef.current
    if (!expectedKey) return
    try {
      const res = await chatApi.conversations()
      if (userKeyRef.current !== expectedKey) return
      setConversations(res.results)
    } catch {
      /* empty list is fine */
    }
  }, [])

  const selectConversation = useCallback(async (id: number) => {
    if (streamingRef.current) return
    const expectedKey = userKeyRef.current
    setLoadingConv(true)
    setCurrentConversationId(id)
    try {
      const res = await chatApi.messages(id)
      if (userKeyRef.current !== expectedKey) return
      setMessages(
        res.messages.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          sources: m.sources || [],
          rating: m.rating,
        })),
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not load conversation.')
    } finally {
      if (userKeyRef.current === expectedKey) setLoadingConv(false)
    }
  }, [])

  const newChat = useCallback(() => {
    chatAbortRef.current?.abort()
    chatAbortRef.current = null
    setStreaming(false)
    setCurrentConversationId(null)
    setMessages([])
  }, [])

  const deleteConversation = useCallback(async (id: number) => {
    const expectedKey = userKeyRef.current
    try {
      await chatApi.remove(id)
      if (userKeyRef.current !== expectedKey) return
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (currentConvIdRef.current === id) {
        setCurrentConversationId(null)
        setMessages([])
      }
      toast.success('Conversation removed.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not delete conversation.')
    }
  }, [])

  const rateMessage = useCallback(async (idx: number, messageId: number, rating: 1 | -1) => {
    try {
      await chatApi.rate(messageId, rating)
      setMessages((prev) => prev.map((m, i) => (i === idx ? { ...m, rating } : m)))
      toast.success(rating === 1 ? 'Feedback noted.' : "Thanks, we'll improve.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not save rating.')
    }
  }, [])

  const stop = useCallback(() => {
    chatAbortRef.current?.abort()
  }, [])

  const send = useCallback(
    async (text?: string) => {
      const q = (text ?? input).trim()
      if (!q || streamingRef.current) return
      const expectedKey = userKeyRef.current
      const activeMode = modeRef.current

      setInput('')
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: q, mode: activeMode },
        { role: 'assistant', content: '', mode: activeMode, question: q, sources: [] },
      ])
      setStreaming(true)

      const ctrl = new AbortController()
      chatAbortRef.current = ctrl

      let finishedCleanly = false
      try {
        await askStream(
          q,
          (e) => {
            if (userKeyRef.current !== expectedKey) return
            if (e.type === 'conversation') {
              setCurrentConversationId(e.conversation_id)
              void refreshConversations()
              return
            }
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              if (!last || last.role !== 'assistant') return prev
              const updated: WorkspaceChatMessage = { ...last }
              if (e.type === 'sources') updated.sources = e.sources
              else if (e.type === 'saved') updated.id = e.message_id
              else if (e.type === 'flag') {
                updated.flag = { message: e.message, categories: e.categories }
              } else if (e.type === 'token') updated.content += e.token
              else if (e.type === 'workflow') updated.workflow = e
              else if (e.type === 'artifact') {
                updated.artifacts = [...(updated.artifacts || []), e.artifact]
                if (!updated.content) updated.content = e.artifact.content_md
                else if (updated.artifacts.length > 1) {
                  updated.content += '\n\n---\n\n' + e.artifact.content_md
                }
              } else if (e.type === 'missing_fields') {
                updated.missingFields = e.fields
              } else if (e.type === 'error') {
                updated.error = true
                updated.content = e.message || 'AI provider error.'
              }
              next[next.length - 1] = updated
              return next
            })
          },
          ctrl.signal,
          {
            mode: activeMode,
            conversationId: currentConvIdRef.current,
          },
        )
        finishedCleanly = true
      } catch (err) {
        if (userKeyRef.current === expectedKey && !(err instanceof DOMException && err.name === 'AbortError')) {
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.role === 'assistant' && !last.content) {
              next[next.length - 1] = {
                ...last,
                content: err instanceof Error ? err.message : 'Something went wrong.',
                error: true,
              }
            }
            return next
          })
        }
      } finally {
        if (userKeyRef.current === expectedKey) {
          setStreaming(false)
          if (chatAbortRef.current === ctrl) chatAbortRef.current = null
          void refreshConversations()
          if (
            finishedCleanly &&
            typeof window !== 'undefined' &&
            window.location.pathname.replace(/\/$/, '') !== '/workspace/chat'
          ) {
            toast.success('Ask AI finished generating your answer.')
          }
        }
      }
    },
    [input, refreshConversations],
  )

  const value = useMemo<WorkspaceStoreValue>(
    () => ({
      stagedFiles,
      setStagedFiles,
      uploadJobs,
      docsRevision,
      bumpDocsRevision,
      enqueueUploads,
      dismissUploadJobs,
      clearFinishedUploads,
      docsState,
      setDocsState,
      auditState,
      setAuditState,
      membersDraft,
      setMembersDraft,
      overviewDraft,
      setOverviewDraft,
      settingsState,
      setSettingsState,
      chat: {
        messages,
        setMessages,
        input,
        setInput,
        streaming,
        llm,
        mode,
        setMode,
        modeInit,
        setModeInit,
        conversations,
        currentConversationId,
        sidebarOpen,
        setSidebarOpen,
        loadingConv,
        refreshLlmStatus,
        refreshConversations,
        selectConversation,
        newChat,
        deleteConversation,
        rateMessage,
        send,
        stop,
      },
    }),
    [
      stagedFiles,
      uploadJobs,
      docsRevision,
      bumpDocsRevision,
      enqueueUploads,
      dismissUploadJobs,
      clearFinishedUploads,
      docsState,
      auditState,
      membersDraft,
      overviewDraft,
      settingsState,
      messages,
      input,
      streaming,
      llm,
      mode,
      modeInit,
      conversations,
      currentConversationId,
      sidebarOpen,
      loadingConv,
      refreshLlmStatus,
      refreshConversations,
      selectConversation,
      newChat,
      deleteConversation,
      rateMessage,
      send,
      stop,
    ],
  )

  return (
    <WorkspaceStoreContext.Provider value={value}>{children}</WorkspaceStoreContext.Provider>
  )
}

export function useWorkspaceStore(): WorkspaceStoreValue {
  const ctx = useContext(WorkspaceStoreContext)
  if (!ctx) {
    throw new Error('useWorkspaceStore must be used inside WorkspaceStoreProvider')
  }
  return ctx
}
