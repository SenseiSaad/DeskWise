// Tiny API client for the Deskwise backend (Django REST at :8000).
// Sessions use HttpOnly cookies: the browser sends them automatically
// (credentials: 'include') and the raw token never touches JS-land, so XSS
// cannot steal it. On a 401 we try one silent refresh then replay the request.

function detectBase(): string {
  const env = process.env.NEXT_PUBLIC_API_URL
  if (env && env.trim()) return env.trim().replace(/\/$/, '')
  if (typeof window !== 'undefined') {
    // Local dev runs Django on :8000. Split deployments (Amplify + Render)
    // must set NEXT_PUBLIC_API_URL at build time; without it, production is
    // assumed to use a same-origin reverse proxy.
    const { protocol, hostname, origin } = window.location
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return `${protocol}//${hostname}:8000`
    }
    return origin
  }
  // SSR fallback; real calls happen client-side after hydration.
  return 'http://localhost:8000'
}

export const API_BASE = detectBase()

const AUTH_SESSION_PATHS = new Set(['/auth/me', '/auth/update-me', '/auth/mfa/setup', '/auth/onboard'])
export const SESSION_EXPIRED_EVENT = 'deskwise:session-expired'
export const SERVER_WAKING_EVENT = 'deskwise:server-waking'

export interface ApiError extends Error {
  status?: number
  code?: string
  retryAfter?: number
  fields?: Record<string, string[]>
}

function canRefreshPath(path: string): boolean {
  return !path.startsWith('/auth/') || AUTH_SESSION_PATHS.has(path)
}

function notifySessionExpired() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
  }
}

let refreshing: Promise<boolean> | null = null
let lastRefreshOkAt = 0

// Try to renew the access cookie via the refresh cookie. Resolves true on success.
async function tryRefresh(requestStartedAt?: number): Promise<boolean> {
  if (requestStartedAt && lastRefreshOkAt > requestStartedAt) {
    return true
  }
  if (!refreshing) {
    refreshing = fetch(`${API_BASE}/api/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    })
      .then((r) => {
        if (r.ok) {
          lastRefreshOkAt = Date.now()
          return true
        }
        return false
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

async function fetchWithRefresh(
  run: () => Promise<Response>,
  allowRefresh = true,
  emitExpired = true,
): Promise<Response> {
  const startedAt = Date.now()
  let res = await run()
  if (res.status === 401 && allowRefresh) {
    const renewed = await tryRefresh(startedAt)
    if (renewed) {
      res = await run()
    }
    if (res.status === 401 && emitExpired) {
      notifySessionExpired()
    }
  }
  return res
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- tiny client: response shapes are typed at each call site
async function handle(res: Response, sessionExpiredOn401: boolean): Promise<any> {
  if (res.status === 401 && sessionExpiredOn401) {
    const err = new Error('Session expired. Please sign in again.') as ApiError
    err.status = 401
    throw err
  }
  if (!res.ok) {
    let detail =
      res.status >= 500
        ? 'The server could not complete this request right now. Please try again in a moment.'
        : `Request failed (${res.status})`
    let code: string | undefined
    let retryAfter: number | undefined
    let fields: Record<string, string[]> | undefined
    const headerRetry = res.headers?.get?.('Retry-After')
    if (headerRetry && !Number.isNaN(Number(headerRetry))) {
      retryAfter = Number(headerRetry)
    }
    try {
      const data = await res.json()
      if (data && typeof data === 'object') {
        if (typeof data.code === 'string') code = data.code
        if (typeof data.retry_after === 'number') retryAfter = data.retry_after
        const fieldMap: Record<string, string[]> = {}
        for (const [k, v] of Object.entries(data)) {
          if (k !== 'detail' && k !== 'code' && k !== 'retry_after' && Array.isArray(v)) {
            fieldMap[k] = v.map(String)
          }
        }
        if (Object.keys(fieldMap).length > 0) fields = fieldMap
      }
      // DRF returns {detail: "..."} or field-keyed {field: ["msg"]}
      const first = data.detail ?? Object.values(data)[0]
      detail = Array.isArray(first) ? first[0] : first || detail
    } catch {
      /* non-JSON error body */
    }
    const err = new Error(detail) as ApiError
    err.status = res.status
    if (code) err.code = code
    if (retryAfter !== undefined) err.retryAfter = retryAfter
    if (fields) err.fields = fields
    throw err
  }
  if (res.status === 204) return null
  return res.json()
}

async function fetchWithTimeoutAndRetry(url: string, init: RequestInit, timeoutMs = 15000): Promise<Response> {
  const attempt = async () => {
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null
    const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null
    try {
      return await fetch(url, ctrl ? { ...init, signal: ctrl.signal } : init)
    } finally {
      if (timer) clearTimeout(timer)
    }
  }
  try {
    return await attempt()
  } catch {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(SERVER_WAKING_EVENT, { detail: { waking: true } }))
    }
    try {
      return await attempt()
    } catch {
      const netErr = new Error('Server is taking too long to respond. Please check your connection and try again.') as ApiError
      netErr.code = 'network_timeout'
      throw netErr
    } finally {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent(SERVER_WAKING_EVENT, { detail: { waking: false } }))
      }
    }
  }
}

function request(method: string, path: string, body?: unknown, isForm = false) {
  const allowRefresh = canRefreshPath(path)
  const run = () =>
    fetchWithTimeoutAndRetry(`${API_BASE}/api${path}`, {
      method,
      credentials: 'include',
      headers: isForm || body == null ? undefined : { 'Content-Type': 'application/json' },
      body: isForm ? (body as FormData) : body == null ? undefined : JSON.stringify(body),
    })
  return fetchWithRefresh(run, allowRefresh).then((res) => handle(res, allowRefresh))
}

export const api = {
  get: (path: string) => request('GET', path),
  post: (path: string, body?: unknown) => request('POST', path, body),
  patch: (path: string, body?: unknown) => request('PATCH', path, body),
  put: (path: string, body?: unknown) => request('PUT', path, body),
  del: (path: string) => request('DELETE', path),
  upload: (path: string, formData: FormData) => request('POST', path, formData, true),
}

// Outcome of a Google Calendar sync attempt. `created` = a real
// event was booked; `simulated` = credentials absent so it was only prepared.
export interface WorkflowCalendar {
  status: 'created' | 'simulated' | 'error'
  reason?: string
  event_id?: string
  html_link?: string
}

// Outcome of the confirmation email.
export interface WorkflowEmail {
  status: 'sent' | 'skipped' | 'error'
  reason?: string
  recipients?: string[]
}

// A completed workflow action streamed after the assistant detects an intent.
export interface WorkflowResult {
  type: 'workflow'
  action: 'schedule_meeting' | 'leave_request' | string
  status: 'ok' | 'simulated' | 'error' | string
  message: string
  // schedule_meeting
  title?: string
  when?: string
  participants?: string[]
  calendar?: WorkflowCalendar
  email?: WorkflowEmail
  // leave_request
  filename?: string
  download_url?: string
  leave_reason?: string
  leave_date?: string
  // error
  detail?: string
}

// AI-01: the assistant only *proposes* an action. Nothing runs until the user
// confirms, which posts the signed single-use token to /api/workflow/confirm.
export interface WorkflowProposal {
  type: 'workflow_proposal'
  action: 'schedule_meeting' | 'leave_request' | string
  message: string
  preview: {
    title?: string
    date?: string
    time?: string
    participants?: string[]
    leave_reason?: string
  }
  token: string
}

export const workflowApi = {
  confirm: (token: string): Promise<WorkflowResult> => api.post('/workflow/confirm', { token }),
}

// One NDJSON line from POST /api/ask.
// A finished, copy/paste/send-ready document produced from a template.
export interface Artifact {
  id: number
  kind: 'email' | 'form' | 'policy' | 'table' | 'text' | string
  title: string
  subject: string
  content_md: string
  structured: {
    kind?: string
    title?: string
    subject?: string
    sections?: { heading: string; fields: { label: string; value: string; placeholder?: boolean }[]; checkboxes?: { checked: boolean; label: string }[]; lines?: string[] }[]
    table?: string[][] | null
    markdown?: string
    missing_fields?: string[]
  }
  missing_fields: string[]
  filled_fields?: string[]
  source?: string
  source_template_id?: number | null
  downloads: Record<string, string>
  created_at?: string
}

export const docgenApi = {
  generate: (
    question: string,
    outputs: string[],
    fields: Record<string, string>,
  ): Promise<{ outputs: string[]; artifacts: Artifact[]; missing_fields: string[] }> =>
    api.post('/docgen', { question, outputs, fields }),
}

export function artifactDownloadUrl(id: number, fmt: 'md' | 'txt' | 'docx' | 'pdf' | 'html' | 'json'): string {
  return `${API_BASE}/api/artifacts/${id}/download?fmt=${fmt}`
}

export const artifactsApi = {
  fromText: (content: string, kind = 'text', title = 'Deskwise document'): Promise<Artifact> =>
    api.post('/artifacts/from_text', { content, kind, title }),
  get: (id: number): Promise<Artifact> => api.get(`/artifacts/${id}`),
}

export interface AskCitation {
  document_id: number
  filename: string
  chunk_ord: number
  snippet: string
}

export type AskEvent =
  | { type: 'sources'; sources: string[]; citations?: AskCitation[] }
  | { type: 'conversation'; conversation_id: number }
  | { type: 'saved'; message_id: number }
  | { type: 'flag'; message: string; categories: string[] }
  | { type: 'redaction'; message: string; categories: string[] }
  | { type: 'token'; token: string }
  | { type: 'intent'; intent: string; data: Record<string, unknown> }
  | { type: 'artifact'; artifact: Artifact }
  | { type: 'missing_fields'; fields: string[] }
  | WorkflowResult
  | WorkflowProposal
  | { type: 'done' }
  | { type: 'error'; message: string }

export type ChatMode = 'local' | 'online' | 'gemini' | 'selfhosted'

// Ask the RAG assistant and stream the answer back line by line. `onEvent` is
// called for every parsed event; pass an AbortSignal to let the caller stop it.
export async function askStream(
  question: string,
  onEvent: (e: AskEvent) => void,
  signal?: AbortSignal,
  options?: { mode?: ChatMode; provider?: string; conversationId?: number | null },
): Promise<void> {
  const res = await fetchWithRefresh(() =>
    fetch(`${API_BASE}/api/ask`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        mode: options?.mode,
        provider: options?.provider,
        conversation_id: options?.conversationId ?? null,
      }),
      signal,
    }),
  )
  if (res.status === 401) {
    onEvent({ type: 'error', message: 'Session expired. Please sign in again.' })
    return
  }
  if (!res.ok || !res.body) {
    let detail = `Request failed (${res.status})`
    try {
      const d = await res.json()
      detail = d.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    onEvent({ type: 'error', message: detail })
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const drain = (final: boolean) => {
    let nl: number
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      if (line) {
        try {
          onEvent(JSON.parse(line) as AskEvent)
        } catch {
          /* ignore a partial/garbled line */
        }
      }
    }
    if (final && buffer.trim()) {
      try {
        onEvent(JSON.parse(buffer.trim()) as AskEvent)
      } catch {
        /* ignore */
      }
    }
  }
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    drain(false)
  }
  drain(true)
}

// ---- Types ---------------------------------------------------------------
export type Role = 'admin' | 'employee' | 'viewer'
export type Clearance = 'standard' | 'internal' | 'confidential'

export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Spanish (Español)' },
  { code: 'fr', label: 'French (Français)' },
  { code: 'de', label: 'German (Deutsch)' },
  { code: 'ar', label: 'Arabic (العربية)' },
  { code: 'pt', label: 'Portuguese (Português)' },
  { code: 'ur', label: 'Roman Urdu' },
] as const

export type UiLanguage = (typeof SUPPORTED_LANGUAGES)[number]['code']

const SUPPORTED_LANGUAGE_CODES: ReadonlySet<string> = new Set(
  SUPPORTED_LANGUAGES.map((l) => l.code),
)

export function isUiLanguage(value: unknown): value is UiLanguage {
  return typeof value === 'string' && SUPPORTED_LANGUAGE_CODES.has(value)
}

// Common job titles offered in the dropdowns. These are display labels only and
// do NOT affect permissions (which are governed by Role).
export const JOB_TITLES = [
  'CEO', 'CTO', 'CFO', 'COO', 'Founder', 'HR', 'Manager',
  'Team Lead', 'Engineer', 'Analyst', 'Other',
] as const

// Subscription plan (USD pricing; limits enforced server-side).
export interface Plan {
  id: number
  name: string
  price_usd: number
  billing_period: string
  max_members: number | null
  max_documents: number | null
  storage_mb: number | null
  monthly_ask_limit: number | null
  allow_versions: boolean
  allow_departments: boolean
  allow_custom_llm: boolean
  is_default: boolean
}

export interface Department {
  id: number
  name: string
  member_count: number
  created_at: string
}

// The caller's own company profile (null for platform admins with no company).
export interface CompanyProfile {
  id: number
  name: string
  slug: string
  access_code: string | null
  website: string
  contact_email: string
  phone: string
  max_employees: number | null
  plan: Plan | null
  hr_email?: string
  signature?: string
  tone?: string
  industry?: string
  enable_attendance?: boolean
  attendance_auto_freeze?: boolean
  enable_docgen?: boolean
  enable_ai_chat?: boolean
  enable_team_chat?: boolean
  enable_external_sharing?: boolean
  require_doc_approval?: boolean
  redact_pii_for_llm?: boolean
  doc_retention_days?: number | null
}

export interface User {
  id: number
  email: string
  username: string | null
  full_name: string
  title: string // display job title (CEO/CTO/HR/...), not a permission
  role: Role
  is_dept_admin?: boolean
  clearance?: '' | Clearance
  effective_clearance?: Clearance
  company_id: number | null
  company: CompanyProfile | null
  department_id: number | null
  department_name: string | null
  email_verified?: boolean
  language?: UiLanguage
  is_active?: boolean
  is_platform_admin?: boolean
  is_superuser?: boolean
  // Profile fields used when filling template documents (optional so older
  // backend responses still typecheck).
  manager?: string
  employee_id?: string
  join_date?: string | null
  direct_upload?: boolean
}

let _directUploadEnabled: boolean | null = null

export interface AuthResponse {
  user: User
  verification_required?: boolean
  onboarding_required?: boolean
}

// Platform-admin sign-ins stop after the password and return this instead —
// the second TOTP step completes via mfaActivate/mfaVerify.
export interface MfaLoginResponse {
  mfa_required: true
  enrollment?: { secret: string; uri: string }
  challenge: string
}

export function isMfaResponse(res: unknown): res is MfaLoginResponse {
  return !!res && typeof res === 'object' && (res as MfaLoginResponse).mfa_required === true
}

// ---- Auth endpoints ------------------------------------------------------
export const authApi = {
  me: async (): Promise<User> => {
    const u = (await api.get('/auth/me')) as User
    if (typeof u?.direct_upload === 'boolean') _directUploadEnabled = u.direct_upload
    return u
  },
  // Enterprise: sign in with EMAIL.
  enterpriseLogin: (p: { email: string; password: string }): Promise<AuthResponse | MfaLoginResponse> =>
    api.post('/auth/login', p),
  mfaActivate: (challenge: string, code: string): Promise<AuthResponse> =>
    api.post('/auth/mfa/activate', { challenge, code }),
  mfaVerify: (challenge: string, code: string): Promise<AuthResponse> =>
    api.post('/auth/mfa/verify', { challenge, code }),
  enterpriseRegister: (p: {
    company_name: string
    admin_name?: string
    admin_title?: string
    website?: string
    contact_email?: string
    phone?: string
    max_employees?: number | null
    email: string
    password: string
  }): Promise<AuthResponse> => api.post('/auth/register', p),
  joinCompany: (p: {
    access_code?: string
    invite_token?: string
    full_name?: string
    email: string
    password: string
  }): Promise<AuthResponse> => api.post('/auth/join', p),
  googleAuth: (credential: string): Promise<AuthResponse | MfaLoginResponse> =>
    api.post('/auth/google', { credential }),
  onboardCompany: (p: {
    action: 'create' | 'join'
    company_name?: string
    access_code?: string
    full_name?: string
  }): Promise<AuthResponse> => api.post('/auth/onboard', p),
  logout: (): Promise<{ ok: boolean }> => api.post('/auth/logout'),
  logoutAll: (): Promise<{ ok: boolean }> => api.post('/auth/logout-all'),
  updateMe: (p: { full_name?: string; title?: string; language?: UiLanguage;
                   current_password?: string; new_password?: string;
                   manager?: string; employee_id?: string; join_date?: string }): Promise<User> =>
    api.patch('/auth/update-me', p),
  requestVerification: (email: string): Promise<{ detail: string }> =>
    api.post('/auth/request-verification', { email }),
  verifyEmail: (token: string): Promise<{ detail: string }> =>
    api.post('/auth/verify', { token }),
  forgotPassword: (email: string): Promise<{ detail: string }> =>
    api.post('/auth/forgot-password', { email }),
  resetPassword: (token: string, password: string): Promise<{ detail: string }> =>
    api.post('/auth/reset-password', { token, password }),
}

// ---- Registered-company directory ---------------------------------------
export interface CompanyDirectory {
  id: number
  name: string
  access_code: string
  member_count: number
}

export interface MemberDirectory {
  id: number
  // Deliberately excludes email: the directory is pre-grant, so partner
  // companies must not be able to harvest staff addresses from a share code.
  full_name: string
  title: string
  role: Role
}

export const companyApi = {
  search: (accessCode: string): Promise<CompanyDirectory> =>
    api.get(`/companies/search?code=${encodeURIComponent(accessCode)}`),
  members: (accessCode: string): Promise<MemberDirectory[]> =>
    api.get(`/companies/${encodeURIComponent(accessCode)}/members`),
}

// ---- Enterprise workspace (authenticated, tenant-scoped) -----------------
export interface EnterpriseDoc {
  id: number
  filename: string
  content_type: string
  size: number
  category: string
  description: string
  downloads: number
  is_okf: boolean
  access_scope: 'company' | 'restricted' | 'department'
  sensitivity?: 'standard' | 'internal' | 'confidential'
  status?: 'draft' | 'in_review' | 'approved' | 'archived'
  reviewed_at?: string | null
  review_note?: string
  contains_pii?: boolean
  legal_hold?: boolean
  department: number | null
  department_name: string | null
  tags: string[]
  indexing_status: 'pending' | 'ready' | 'failed'
  index_error: string
  num_chunks: number
  version: number
  created_at: string
  updated_at: string
  company_name?: string
  ephemeral_notice?: string
  masked?: boolean
  requires_break_glass?: boolean
}

// Paginated list envelope returned by the documents endpoint.
export interface Paged<T> {
  results: T[]
  count: number
  page: number
  pages: number
  restricted_metadata?: EnterpriseDoc[]
}

// One row of the company audit trail.
export interface AuditRow {
  id: number
  user_id: number | null
  actor_id?: number | null
  actor_email?: string
  action: string
  outcome?: 'allowed' | 'denied'
  target_type?: string
  target_id?: string
  detail: string
  ip: string
  hash_version?: number
  prev_hash?: string
  entry_hash?: string
  created_at: string
}

export interface AuditVerifyReport {
  valid: boolean
  checked: number
  broken_id: number | null
  head_hash?: string
  verified_at?: string
  company_id?: number
  company_name?: string
  guarantee_note?: string
}

export interface AccessExplainResult {
  user: {
    id: number
    email: string
    full_name: string
    role: Role
    is_dept_admin: boolean
    department_name: string | null
    clearance: Clearance
  }
  document: {
    id: number
    filename: string
    access_scope: 'company' | 'department' | 'restricted'
    sensitivity: Clearance
    status: string
    department_name: string | null
    masked: boolean
  }
  action: string
  allowed: boolean
  reason_code: string
  rule_chain: string[]
  metadata_only: boolean
}

export interface EffectiveAccessResult {
  user: User
  summary: {
    total_documents: number
    total_approved: number
    searchable_count: number
    workspace_visible_count: number
    downloadable_count: number
  }
  documents: {
    id: number
    filename: string
    masked: boolean
    access_scope: 'company' | 'department' | 'restricted'
    sensitivity: Clearance
    status: string
    department_name: string | null
    can_search: boolean
    can_download: boolean
  }[]
}

export interface LlmStatus {
  online: boolean
  provider?: string
  model: string
  company_override?: boolean
  key_source?: 'platform_env' | 'company' | 'row' | 'iam' | 'none'
  local?: {
    online: boolean
    provider: string
    model: string
  }
  online_api?: {
    online: boolean
    provider: string
    model: string
    has_key: boolean
  }
  gemini?: {
    online: boolean
    provider: string
    model: string
    has_key: boolean
  }
  selfhosted?: {
    online: boolean
    provider: string
    model: string
    configured: boolean
  }
}

// A document from ANOTHER company shared directly with the current user.
export interface SharedDoc extends EnterpriseDoc {
  shared_by: string | null
  can_download: boolean
  expires_at?: string | null
}

// One grantee on a document the caller's company owns.
export interface DocumentShareRow {
  id: number
  user_id: number
  email: string
  full_name: string
  title: string
  role: Role
  company_name: string | null
  access_code: string | null
  can_download: boolean
  expires_at?: string | null
  is_expired?: boolean
  created_at: string
}

// Read legacy provider values from existing database rows, while the settings
// UI only offers the two supported launch modes.
export type LlmProvider = 'ollama' | 'openai' | 'anthropic' | 'gemini' | 'bedrock'

// LLM settings: the platform default (platform admins) or a company override.
export interface LlmConfig {
  provider: LlmProvider
  chat_model: string
  base_url: string
  temperature: number
  max_tokens: number
  has_api_key: boolean
  is_company_override: boolean
  key_source?: 'platform_env' | 'company' | 'row' | 'iam' | 'none'
  platform_key_in_use?: boolean
  updated_at: string
}

export interface LlmConfigUpdate {
  provider?: LlmProvider
  chat_model?: string
  base_url?: string
  temperature?: number
  max_tokens?: number
  api_key?: string
}

export interface LlmTestResult {
  ok: boolean
  provider: string
  model: string
  sample?: string
  detail?: string
}

export interface NewUser {
  full_name?: string
  title?: string
  department_id?: number | null
  email: string
  password?: string
  role: Role
  is_dept_admin?: boolean
  clearance?: '' | Clearance
  reason?: string
}

// Company documents. Access is filtered server-side; upload/delete/share
// require an editor (admin or employee).
export const workApi = {
  documents: (page = 1, pageSize = 200): Promise<Paged<EnterpriseDoc>> =>
    api.get(`/documents?page=${page}&page_size=${pageSize}`),
  upload: async (form: FormData): Promise<EnterpriseDoc> => {
    const file = form.get('file')
    // On Vercel serverless, bodies > 4.5 MB are rejected; try direct S3 presigned upload when supported.
    if (file instanceof File && file.size > 4 * 1024 * 1024 && _directUploadEnabled !== false) {
      try {
        const presign = await api.post('/documents/presign', {
          filename: file.name,
          size: file.size,
          content_type: file.type || 'application/octet-stream',
        })
        if (presign?.upload_url && presign?.key) {
          const putRes = await fetch(presign.upload_url, {
            method: 'PUT',
            // The server signs the content type it derives from the extension; send exactly that.
            headers: { 'Content-Type': presign.content_type || file.type || 'application/octet-stream' },
            body: file,
          })
          if (putRes.ok) {
            return api.post('/documents/confirm', {
              key: presign.key,
              filename: file.name,
              size: file.size,
              content_type: file.type || '',
              category: form.get('category') ?? 'Other',
              description: form.get('description') ?? '',
              tags: form.get('tags') ?? '',
              is_okf: form.get('is_okf') ?? 'false',
              access_scope: form.get('access_scope') ?? 'company',
              sensitivity: form.get('sensitivity') ?? 'standard',
              department_id: form.get('department_id') ?? null,
            })
          }
        }
      } catch {
        _directUploadEnabled = false
        // Fall back to standard multipart upload if S3 presigning is not enabled.
      }
    }
    return api.upload('/documents/upload', form)
  },
  docDetail: (id: number): Promise<EnterpriseDoc> => api.get(`/documents/${id}`),
  updateDoc: (id: number, p: Partial<EnterpriseDoc> & { department_id?: number | null }): Promise<EnterpriseDoc> =>
    api.patch(`/documents/${id}`, p),
  reviewDoc: (
    id: number,
    p: { action: 'submit' | 'approve' | 'reject' | 'archive'; note?: string },
  ): Promise<EnterpriseDoc> => api.post(`/documents/${id}/review`, p),
  breakGlass: (id: number, reason: string): Promise<EnterpriseDoc> =>
    api.post(`/documents/${id}/break-glass`, { reason }),
  remove: (id: number): Promise<null> => api.del(`/documents/${id}`),
  reindex: (id: number): Promise<EnterpriseDoc> => api.post(`/documents/${id}/reindex`),
  preview: (id: number): Promise<{ id: number; filename: string; text: string; truncated: boolean; num_chunks: number }> =>
    api.get(`/documents/${id}/preview`),
  versions: (id: number): Promise<{ id: number; version_number: number; filename: string; size: number; created_at: string }[]> =>
    api.get(`/documents/${id}/versions`),
  newVersion: (id: number, form: FormData): Promise<EnterpriseDoc> =>
    api.upload(`/documents/${id}/versions/new`, form),
  llmStatus: (): Promise<LlmStatus> => api.get('/llm-status'),
  // Documents other companies shared directly with me (cross-company collab).
  sharedWithMe: (): Promise<SharedDoc[]> => api.get('/shared-with-me'),
  search: (q: string): Promise<{
    query: string
    documents: EnterpriseDoc[]
    team_messages: { id: number; room_id: number; room_name: string; sender: string; content: string; created_at: string }[]
    artifacts: Artifact[]
  }> => api.get(`/search?q=${encodeURIComponent(q)}`),
}

// Granular cross-company sharing. Editors of the OWNING company manage who,
// outside their company, can access one specific document.
export const shareApi = {
  list: (docId: number): Promise<DocumentShareRow[]> => api.get(`/documents/${docId}/shares`),
  add: (
    docId: number,
    payload: {
      access_code?: string
      user_id: number
      can_download?: boolean
      expires_in_days?: number
      allow_pii?: boolean
      override_clearance?: boolean
      grant_reason?: string
    },
  ): Promise<DocumentShareRow> => api.post(`/documents/${docId}/shares`, payload),
  remove: (docId: number, userId: number): Promise<null> =>
    api.del(`/documents/${docId}/shares/${userId}`),
}

// Company settings (admin): profile + seat cap + feature switches.
export const companyApi2 = {
  settings: (): Promise<CompanyProfile> => api.get('/admin/company'),
  updateSettings: (
    p: Partial<
      Pick<
        CompanyProfile,
        | 'name'
        | 'website'
        | 'contact_email'
        | 'phone'
        | 'max_employees'
        | 'hr_email'
        | 'signature'
        | 'tone'
        | 'enable_attendance'
        | 'attendance_auto_freeze'
        | 'enable_docgen'
        | 'enable_ai_chat'
        | 'enable_team_chat'
        | 'enable_external_sharing'
        | 'require_doc_approval'
        | 'redact_pii_for_llm'
        | 'doc_retention_days'
      >
    >,
  ): Promise<CompanyProfile> => api.patch('/admin/company', p),
  departments: (): Promise<Department[]> => api.get('/admin/departments'),
  addDepartment: (name: string): Promise<Department> => api.post('/admin/departments', { name }),
  removeDepartment: (id: number): Promise<null> => api.del(`/admin/departments/${id}`),
  announcements: (): Promise<Announcement[]> => api.get('/admin/announcements'),
  addAnnouncement: (p: { title: string; body: string; require_ack?: boolean }): Promise<Announcement> =>
    api.post('/admin/announcements', p),
  removeAnnouncement: (id: number): Promise<null> => api.del(`/admin/announcements/${id}`),
  ackAnnouncement: (id: number): Promise<{ announcement_id: number; acknowledged: boolean; acknowledged_at: string }> =>
    api.post(`/announcements/${id}/ack`),
  announcementAcks: (id: number): Promise<{
    announcement_id: number
    require_ack: boolean
    acknowledged: { user_id: number; email: string; full_name: string; acknowledged_at: string }[]
    pending: { user_id: number; email: string; full_name: string }[]
  }> => api.get(`/announcements/${id}/acks`),
}

// Platform LLM provider settings + connectivity test.
export const settingsApi = {
  llmConfig: (): Promise<LlmConfig> => api.get('/admin/llm-config'),
  updateLlmConfig: (p: LlmConfigUpdate): Promise<LlmConfig> => api.put('/admin/llm-config', p),
  resetLlmConfig: (): Promise<LlmConfig> => api.del('/admin/llm-config'),
  llmTest: (): Promise<LlmTestResult> => api.post('/admin/llm-test'),
}

// Chat threads (persisted history + ratings).
export interface Conversation {
  id: number
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources: string[]
  rating: number | null
  created_at: string
}

export const chatApi = {
  conversations: (): Promise<Paged<Conversation>> => api.get('/conversations?page_size=50'),
  newConversation: (title?: string): Promise<Conversation> => api.post('/conversations', { title }),
  messages: (id: number): Promise<{ conversation: Conversation; messages: ChatMessage[] }> =>
    api.get(`/conversations/${id}`),
  remove: (id: number): Promise<null> => api.del(`/conversations/${id}`),
  rename: (id: number, title: string): Promise<Conversation> => api.patch(`/conversations/${id}`, { title }),
  rate: (messageId: number, rating: 1 | -1): Promise<{ ok: boolean }> =>
    api.post(`/messages/${messageId}/rate`, { rating }),
}

// Usage analytics (company admin).
export interface Analytics {
  range_days: number
  totals: { asks: number; unanswered: number; flagged: number; avg_latency_ms: number }
  by_user: { user__email: string | null; user__full_name: string | null; asks: number; unanswered: number }[]
  by_department: { department__name: string; asks: number; unanswered: number }[]
  unanswered_questions: { question: string; created_at: string; user__email: string | null }[]
  ratings: { up: number; down: number }
  top_documents: { filename: string; downloads: number }[]
  usage: { asks_this_month: number; monthly_ask_limit: number | null }
}

export const analyticsApi = {
  get: (days = 30): Promise<Analytics> => api.get(`/admin/analytics?days=${days}`),
}

// Usage & plan dashboard (company admin): current consumption of every plan
// quota this month plus the upgrade catalogue.
export interface UsageReport {
  plan: Plan
  usage: {
    asks: { used: number; limit: number | null; remaining: number | null }
    documents: { used: number; limit: number | null; remaining: number | null }
    storage: { used_bytes: number; limit_mb: number | null; used_mb: number }
    members: { used: number; limit: number | null; remaining: number | null }
    departments: { used: number; enabled: boolean }
  }
  upgrades: Plan[]
}

export const usageApi = {
  get: (): Promise<UsageReport> => api.get('/admin/usage'),
}

export interface AdminCompany {
  id: number
  name: string
  slug: string
  access_code: string
  member_count: number
  doc_count: number
  plan: Plan | null
}

export interface GovernanceSummary {
  pending_review_count: number
  pending_reviews: EnterpriseDoc[]
  pii_document_count: number
  pii_documents: EnterpriseDoc[]
  legal_hold_count: number
  legal_hold_documents: EnterpriseDoc[]
  stale_threshold_days: number
  stale_document_count: number
  stale_documents: EnterpriseDoc[]
  expiring_shares: DocumentShareRow[]
  expired_share_count: number
  mandatory_announcements: { id: number; title: string; acknowledged_count: number; pending_count: number }[]
  audit_integrity: { valid: boolean; checked: number; broken_id: number | null }
}

// Company administration: requires admin/platform authority.
export const adminApi = {
  users: (): Promise<User[]> => api.get('/admin/users'),
  createUser: (p: NewUser): Promise<User> => api.post('/admin/users', p),
  updateUser: (
    id: number,
    p: {
      role?: Role
      is_dept_admin?: boolean
      department_id?: number | null
      clearance?: '' | Clearance
      full_name?: string
      title?: string
      is_active?: boolean
      reason?: string
    },
  ): Promise<User> => api.patch(`/admin/users/${id}`, p),
  removeUser: (id: number): Promise<null> => api.del(`/admin/users/${id}`),
  explainAccess: (
    userId: number,
    documentId: number,
    action: 'view_ask' | 'download' = 'view_ask',
    includeUnapproved = false,
  ): Promise<AccessExplainResult> =>
    api.get(
      `/admin/access/explain?user_id=${userId}&document_id=${documentId}&action=${action}&include_unapproved=${includeUnapproved ? '1' : '0'}`,
    ),
  effectiveAccess: (userId: number): Promise<EffectiveAccessResult> =>
    api.get(`/admin/members/${userId}/effective-access`),
  audit: (page = 1, pageSize = 200): Promise<Paged<AuditRow>> =>
    api.get(`/admin/audit?page=${page}&page_size=${pageSize}`),
  verifyAudit: (): Promise<AuditVerifyReport> =>
    api.get('/admin/audit/verify'),
  auditCertificateUrl: () => `${API_BASE}/api/admin/audit/verify?certificate=1`,
  governance: (): Promise<GovernanceSummary> => api.get('/admin/governance'),
  exportAudit: () => `${API_BASE}/api/admin/audit?export=csv`,
  companies: (): Promise<AdminCompany[]> => api.get('/admin/companies'),
  switchCompany: (company_id: number): Promise<User> => api.post('/admin/switch-company', { company_id }),
  detachCompany: (): Promise<User> => api.post('/admin/detach-company'),
  setCompanyPlan: (companyId: number, planId: number): Promise<{ ok: boolean }> =>
    api.post(`/admin/companies/${companyId}/plan`, { plan_id: planId }),
  plans: (): Promise<Plan[]> => {
    // plans is AllowAny but goes through the same client for consistency
    return api.get('/plans')
  },
}

// ---- Stripe Billing & Subscriptions ---------------------------------------
export interface BillingStatus {
  has_stripe: boolean
  stripe_publishable_key: string
  plan: Plan | null
  stripe_customer_id: string
  stripe_subscription_id: string
  is_subscribed: boolean
}

export const billingApi = {
  status: (): Promise<BillingStatus> => api.get('/billing/status'),
  checkout: (planId: number, successUrl?: string, cancelUrl?: string): Promise<{ url: string; session_id: string }> =>
    api.post('/billing/checkout', { plan_id: planId, success_url: successUrl, cancel_url: cancelUrl }),
  portal: (returnUrl?: string): Promise<{ url: string }> =>
    api.post('/billing/portal', { return_url: returnUrl }),
}

// ---- Attendance + 3-strike discipline (Feature 5) ------------------------
export interface AttendanceRecord {
  id: number
  date: string
  scanned_at: string
  status: string
}

export interface UserStrike {
  absent_count: number
  strikes: number
  is_frozen: boolean
  last_evaluated_period: string | null
  last_updated: string
}

export interface AttendanceMe {
  today: string
  marked_today: boolean
  absences_this_month: number
  records: AttendanceRecord[]
  strike: UserStrike | null
}

export interface AttendanceQr {
  target: string
  svg: string | null
  qr_available: boolean
}

export const attendanceApi = {
  me: (): Promise<AttendanceMe> => api.get('/attendance/me'),
  // 201 with the new record, or throws "Attendance already marked for today." (409).
  // The office QR embeds a signed short-lived token (?t=...); scans send it
  // so a photographed/broadcast QR cannot check people in remotely.
  scan: (qrToken?: string): Promise<AttendanceRecord> =>
    api.post('/attendance/scan', qrToken ? { token: qrToken } : undefined),
  qr: (): Promise<AttendanceQr> => api.get('/attendance/qr'),
}

export interface Announcement {
  id: number
  title: string
  body: string
  require_ack?: boolean
  ack_count?: number
  acknowledged_by_me?: boolean
  created_by_name: string | null
  created_at: string
}

// ---- Employee Team Chatroom -----------------------------------------------
export type TeamRoomScope = 'company' | 'department' | 'private'

export interface TeamRoom {
  id: number
  name: string
  slug: string
  description: string
  scope: TeamRoomScope
  department_id: number | null
  department_name: string | null
  is_default: boolean
  member_count: number
  member_ids: number[]
  unread_count: number
  pinned_count: number
  created_at: string
}

export interface TeamChatMember {
  id: number
  full_name: string
  email: string
  title: string
  role: Role
  department_id: number | null
  department_name: string | null
  is_online?: boolean
}

export interface TeamMessageReaction {
  emoji: string
  count: number
  user_ids: number[]
}

export interface TeamMessageSource {
  filename: string
  document_id?: number | null
}

export interface TeamMessage {
  id: number
  room_id: number
  sender_type: 'user' | 'deskwise'
  sender_id: number | null
  sender: {
    id: number
    full_name: string
    email: string
    title: string
    role: Role
    department_name: string | null
  } | null
  content: string
  reply_to_id: number | null
  reply_to: {
    id: number
    sender_type: 'user' | 'deskwise'
    sender_id: number | null
    sender_name: string
    content: string
  } | null
  referenced_document: {
    id: number
    filename: string
    category: string
    access_scope: string
  } | null
  sources: TeamMessageSource[]
  metadata: Record<string, unknown>
  flag?: { message: string; categories: string[] } | null
  reactions: TeamMessageReaction[]
  is_pinned: boolean
  pinned_by_id: number | null
  pinned_by_name: string | null
  pinned_at: string | null
  is_edited: boolean
  edited_at: string | null
  edit_expires_at: string | null
  created_at: string
  client_nonce?: string
  replaces_stream_id?: string
  /** Local-only flag: message not yet confirmed by the server. */
  _pending?: boolean
}

export interface TeamChatRoomsResponse {
  rooms: TeamRoom[]
  members: TeamChatMember[]
  departments: { id: number; name: string }[]
  online_user_ids: number[]
  edit_window_seconds: number
  allowed_emojis: string[]
}

export interface TeamChatMessagesResponse {
  room: TeamRoom
  results: TeamMessage[]
  pinned: TeamMessage[]
  has_more: boolean
  edit_window_seconds: number
}

export function teamChatWsUrl(): string {
  const wsBase = API_BASE.replace(/^http/i, 'ws')
  return `${wsBase}/ws/team-chat/`
}

export const teamChatApi = {
  rooms: (): Promise<TeamChatRoomsResponse> => api.get('/team-chat/rooms'),
  createRoom: (p: {
    name: string
    description?: string
    scope?: TeamRoomScope
    department_id?: number | null
    member_ids?: number[]
  }): Promise<TeamRoom> => api.post('/team-chat/rooms', p),
  updateRoom: (
    roomId: number,
    p: {
      name?: string
      description?: string
      scope?: TeamRoomScope
      department_id?: number | null
      member_ids?: number[]
    },
  ): Promise<TeamRoom> => api.patch(`/team-chat/rooms/${roomId}`, p),
  deleteRoom: (roomId: number): Promise<{ ok: boolean; deleted_id: number }> =>
    api.del(`/team-chat/rooms/${roomId}`),
  messages: (
    roomId: number,
    opts?: { beforeId?: number; q?: string; limit?: number; markRead?: boolean },
  ): Promise<TeamChatMessagesResponse> => {
    const params = new URLSearchParams()
    if (opts?.beforeId) params.set('before_id', String(opts.beforeId))
    if (opts?.q) params.set('q', opts.q)
    if (opts?.limit) params.set('limit', String(opts.limit))
    if (opts?.markRead === false) params.set('mark_read', 'false')
    const qs = params.toString()
    return api.get(`/team-chat/rooms/${roomId}/messages${qs ? `?${qs}` : ''}`)
  },
  sendMessage: (
    roomId: number,
    p: {
      content: string
      reply_to_id?: number | null
      referenced_document_id?: number | null
      client_nonce?: string
    },
  ): Promise<{
    message: TeamMessage
    deskwise_triggered: boolean
    stream_id: string | null
    deskwise_message?: TeamMessage | null
  }> =>
    api.post(`/team-chat/rooms/${roomId}/messages`, p),
  markRead: (roomId: number, lastMessageId?: number): Promise<{ ok: boolean; last_read_message_id: number }> =>
    api.post(`/team-chat/rooms/${roomId}/read`, lastMessageId ? { last_message_id: lastMessageId } : {}),
  editMessage: (msgId: number, content: string): Promise<{ message: TeamMessage }> =>
    api.patch(`/team-chat/messages/${msgId}`, { content }),
  deleteMessage: (msgId: number): Promise<{ ok: boolean; room_id: number; deleted_id: number }> =>
    api.del(`/team-chat/messages/${msgId}`),
  pinMessage: (msgId: number, pinned?: boolean): Promise<{ message: TeamMessage }> =>
    api.post(`/team-chat/messages/${msgId}/pin`, pinned === undefined ? {} : { pinned }),
  reactMessage: (msgId: number, emoji: string): Promise<{ message: TeamMessage }> =>
    api.post(`/team-chat/messages/${msgId}/react`, { emoji }),
  summarizeRoom: (roomId: number): Promise<{
    room_id: number
    message_count: number
    summary: string
    action_items: string[]
    open_questions: string[]
    pinned: string[]
    mode: string
  }> => api.post(`/team-chat/rooms/${roomId}/summarize`),
}

// Authenticated download of a permitted enterprise document.
export async function downloadOwnDocument(id: number, filename: string) {
  const res = await fetchWithRefresh(() =>
    fetch(`${API_BASE}/api/documents/${id}/download`, { credentials: 'include' }),
  )
  if (res.status === 401) throw new Error('Session expired. Please sign in again.')
  if (!res.ok) throw new Error(`Download failed (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'document'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// Authenticated download of an AI-generated workflow form (e.g. the leave
// application .docx). `downloadUrl` may be relative or absolute.
export async function downloadGeneratedForm(downloadUrl: string, filename?: string) {
  const url = /^https?:\/\//i.test(downloadUrl) ? downloadUrl : `${API_BASE}${downloadUrl}`
  const res = await fetchWithRefresh(() => fetch(url, { credentials: 'include' }))
  if (res.status === 401) throw new Error('Session expired. Please sign in again.')
  if (!res.ok) throw new Error(`Download failed (${res.status})`)
  const blob = await res.blob()
  const objectUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = filename || 'Leave_Application.docx'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(objectUrl)
}
