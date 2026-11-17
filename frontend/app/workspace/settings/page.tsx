'use client'

import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  Building2,
  Check,
  Cpu,
  CreditCard,
  KeyRound,
  Loader2,
  MessageSquare,
  PlugZap,
  RotateCcw,
  Save,
  Users,
} from 'lucide-react'
import {
  adminApi,
  analyticsApi,
  billingApi,
  companyApi2,
  settingsApi,
  type Analytics,
  type CompanyProfile,
  type LlmConfig,
  type LlmProvider,
  type LlmTestResult,
  type Plan,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { authApi } from '@/lib/api'
import { toast } from '@/components/toaster'
import { SmoothSelect } from '@/components/ui/smooth-select'
import { useWorkspaceStore } from '@/lib/workspace-store'

const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/25 focus-visible:ring-offset-2 focus-visible:ring-offset-background'
const eyebrow = 'text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground'
const inputClass =
  'h-11 w-full rounded-xl border border-border-strong bg-surface-elevated px-3.5 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-foreground'
const primaryBtn =
  `inline-flex h-10 items-center justify-center gap-2 rounded-full bg-primary px-5 text-xs font-medium text-primary-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`
const ghostBtn =
  `inline-flex h-10 items-center justify-center gap-2 rounded-full border border-border-strong bg-surface-elevated px-4 text-xs font-medium text-foreground transition-colors hover:border-foreground disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`
const label = 'mb-1 block text-xs font-medium text-foreground'

const BEDROCK_DEFAULT_MODEL = 'us.amazon.nova-lite-v1:0'
const BEDROCK_DEFAULT_REGION = 'us-east-1'
const OLLAMA_DEFAULT_MODEL = 'qwen2.5:0.5b'
const OLLAMA_DEFAULT_URL = 'http://localhost:11434'
type ActiveLlmProvider = Extract<LlmProvider, 'bedrock' | 'ollama'>

const PROVIDERS: {
  value: ActiveLlmProvider
  label: string
  blurb: string
  badge?: string
  keyLabel?: string
  modelHint: string
  usesBaseUrl?: boolean
}[] = [
  {
    value: 'bedrock',
    label: 'AWS Bedrock',
    blurb: 'Cloud answers via your configured AWS account. Only permission-approved passages are sent to Bedrock.',
    badge: 'Fast & low cost',
    keyLabel: 'Bedrock API key or ACCESS_KEY_ID:SECRET_ACCESS_KEY',
    modelHint: BEDROCK_DEFAULT_MODEL,
    usesBaseUrl: true,
  },
  {
    value: 'ollama',
    label: 'Local model (Ollama)',
    blurb: 'Uses an Ollama server reachable by the API for chat generation; embeddings remain on the configured platform provider.',
    badge: 'Local & free',
    modelHint: OLLAMA_DEFAULT_MODEL,
    usesBaseUrl: true,
  },
]

type Tab = 'company' | 'plan' | 'ai'

export default function SettingsPage() {
  const { user, isPlatformAdmin } = useAuth()
  // Company profile / plan / AI engine are admin-only (the API enforces it);
  // everyone else just gets "My Profile".
  const isAdmin = user?.role === 'admin' || isPlatformAdmin
  const { settingsState, setSettingsState } = useWorkspaceStore()
  const tab = settingsState.tab
  const setTab = (v: Tab) => setSettingsState((s) => ({ ...s, tab: v }))

  // Company profile
  const [profile, setProfile] = useState<CompanyProfile | null>(null)
  const [compLoading, setCompLoading] = useState(true)
  const [compName, setCompName] = useState('')
  const [compWebsite, setCompWebsite] = useState('')
  const [compEmail, setCompEmail] = useState('')
  const [compPhone, setCompPhone] = useState('')
  const [compMaxSeats, setCompMaxSeats] = useState<string>('')
  const [compHrEmail, setCompHrEmail] = useState('')
  const [compSignature, setCompSignature] = useState('')
  const [compTone, setCompTone] = useState('')
  const [savingComp, setSavingComp] = useState(false)

  // My profile (template filling uses only non-empty fields)
  const [myName, setMyName] = useState('')
  const [myTitle, setMyTitle] = useState('')
  const [myManager, setMyManager] = useState('')
  const [myEmployeeId, setMyEmployeeId] = useState('')
  const [myJoinDate, setMyJoinDate] = useState('')
  const [savingMe, setSavingMe] = useState(false)

  // Plans & usage
  const [plans, setPlans] = useState<Plan[]>([])
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [planLoading, setPlanLoading] = useState(true)
  const [upgradingPlanId, setUpgradingPlanId] = useState<number | null>(null)

  // AI config
  const [cfg, setCfg] = useState<LlmConfig | null>(null)
  const [aiLoading, setAiLoading] = useState(true)
  const [provider, setProvider] = useState<ActiveLlmProvider>('bedrock')
  const [chatModel, setChatModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [temperature, setTemperature] = useState('0.2')
  const [maxTokens, setMaxTokens] = useState('512')
  const [savingAi, setSavingAi] = useState(false)
  const [resettingAi, setResettingAi] = useState(false)
  const [testingAi, setTestingAi] = useState(false)
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null)

  const hydrateAi = useCallback((c: LlmConfig) => {
    setCfg(c)
    const supportedProvider: ActiveLlmProvider = c.provider === 'ollama' ? 'ollama' : 'bedrock'
    const isLegacyProvider = c.provider !== 'bedrock' && c.provider !== 'ollama'
    setProvider(supportedProvider)
    setChatModel(
      isLegacyProvider || !c.chat_model
        ? supportedProvider === 'bedrock'
          ? BEDROCK_DEFAULT_MODEL
          : OLLAMA_DEFAULT_MODEL
        : c.chat_model,
    )
    setBaseUrl(
      isLegacyProvider || !c.base_url
        ? supportedProvider === 'bedrock'
          ? BEDROCK_DEFAULT_REGION
          : OLLAMA_DEFAULT_URL
        : c.base_url,
    )
    setTemperature(String(c.temperature))
    setMaxTokens(String(c.max_tokens))
    setApiKey('')
  }, [])

  // Loaders
  const loadCompany = useCallback(() => {
    setCompLoading(true)
    companyApi2
      .settings()
      .then((res) => {
        setProfile(res)
        setCompName(res.name || '')
        setCompWebsite(res.website || '')
        setCompEmail(res.contact_email || '')
        setCompPhone(res.phone || '')
        setCompMaxSeats(res.max_employees != null ? String(res.max_employees) : '')
        setCompHrEmail(res.hr_email || '')
        setCompSignature(res.signature || '')
        setCompTone(res.tone || '')
      })
      .catch(() => setProfile(null))
      .finally(() => setCompLoading(false))
  }, [])

  useEffect(() => {
    if (!user) return
    setMyName(user.full_name || '')
    setMyTitle(user.title || '')
    setMyManager(user.manager || '')
    setMyEmployeeId(user.employee_id || '')
    setMyJoinDate(user.join_date || '')
  }, [user])

  const loadPlans = useCallback(() => {
    setPlanLoading(true)
    Promise.all([
      adminApi.plans().catch(() => []),
      analyticsApi.get(30).catch(() => null),
    ])
      .then(([plansRes, analyticsRes]) => {
        setPlans(plansRes)
        setAnalytics(analyticsRes)
      })
      .finally(() => setPlanLoading(false))
  }, [])

  const loadAi = useCallback(() => {
    setAiLoading(true)
    settingsApi
      .llmConfig()
      .then(hydrateAi)
      .catch(() => setCfg(null))
      .finally(() => setAiLoading(false))
  }, [hydrateAi])

  useEffect(() => {
    if (!isAdmin) {
      setCompLoading(false)
      setPlanLoading(false)
      setAiLoading(false)
      return
    }
    loadCompany()
    loadPlans()
    loadAi()
  }, [isAdmin, loadCompany, loadPlans, loadAi])

  async function onSaveCompany(e: FormEvent) {
    e.preventDefault()
    setSavingComp(true)
    try {
      const updated = await companyApi2.updateSettings({
        name: compName.trim(),
        website: compWebsite.trim(),
        contact_email: compEmail.trim(),
        phone: compPhone.trim(),
        max_employees: compMaxSeats ? Number(compMaxSeats) : null,
        hr_email: compHrEmail.trim(),
        signature: compSignature.trim(),
        tone: compTone.trim(),
      })
      setProfile(updated)
      toast.success('Company settings saved.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not save company settings.')
    } finally {
      setSavingComp(false)
    }
  }

  function currentAiUpdate() {
    const update: Parameters<typeof settingsApi.updateLlmConfig>[0] = {
      provider,
      chat_model: chatModel.trim(),
      base_url: baseUrl.trim(),
      temperature: Number(temperature) || 0,
      max_tokens: Number(maxTokens) || 0,
    }
    if (apiKey.trim()) {
      update.api_key = apiKey.trim()
    } else if (cfg && cfg.provider !== provider) {
      // Don't accidentally send a saved Gemini/OpenAI secret as a Bedrock key.
      // An empty key clears that legacy secret and lets Render's Bedrock secret
      // be used instead.
      update.api_key = ''
    }
    return update
  }

  async function persistAiConfig() {
    const updated = await settingsApi.updateLlmConfig(currentAiUpdate())
    hydrateAi(updated)
    return updated
  }

  async function onSaveAi(e: FormEvent) {
    e.preventDefault()
    setSavingAi(true)
    setTestResult(null)
    try {
      await persistAiConfig()
      toast.success('AI settings saved.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not save AI settings.')
    } finally {
      setSavingAi(false)
    }
  }

  async function onResetAi() {
    setResettingAi(true)
    try {
      const updated = await settingsApi.resetLlmConfig()
      hydrateAi(updated)
      toast.success('Reset to platform default AI settings.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not reset AI settings.')
    } finally {
      setResettingAi(false)
    }
  }

  async function onTestAi() {
    setTestingAi(true)
    setTestResult(null)
    try {
      // Test the values currently shown in the form, not a stale database row.
      await persistAiConfig()
      const res = await settingsApi.llmTest()
      setTestResult(res)
    } catch (err) {
      setTestResult({
        ok: false,
        provider,
        model: chatModel,
        detail: err instanceof Error ? err.message : 'Test failed.',
      })
    } finally {
      setTestingAi(false)
    }
  }

  async function onSelectPlan(planId: number) {
    if (!profile || !isPlatformAdmin) return
    try {
      await adminApi.setCompanyPlan(profile.id, planId)
      toast.success('Plan updated for company.')
      loadCompany()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not update plan.')
    }
  }

  async function onCheckout(planId: number) {
    try {
      setUpgradingPlanId(planId)
      const res = await billingApi.checkout(planId)
      if (res.url) {
        window.location.href = res.url
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not launch checkout.')
      setUpgradingPlanId(null)
    }
  }

  if (!user) return null

  const activeProvider = PROVIDERS.find((p) => p.value === provider) ?? PROVIDERS[0]
  const hasLegacyProviderConfig = !!cfg && cfg.provider !== 'bedrock' && cfg.provider !== 'ollama'
  const currentPlan = profile?.plan

  async function onSaveProfile(e: FormEvent) {
    e.preventDefault()
    setSavingMe(true)
    try {
      await authApi.updateMe({
        full_name: myName.trim(),
        title: myTitle.trim(),
        manager: myManager.trim(),
        employee_id: myEmployeeId.trim(),
        join_date: myJoinDate.trim(),
      })
      toast.success('Your profile saved.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not save your profile.')
    } finally {
      setSavingMe(false)
    }
  }

  return (
    <div className="mx-auto max-w-4xl pb-10">
      <header className="border-b border-border pb-6">
        <p className={eyebrow}>Workspace Management</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-[-0.05em] sm:text-4xl">
          Settings &amp; <span className="font-serif font-normal italic">plans.</span>
        </h1>
        <p className="mt-2 max-w-xl text-xs leading-relaxed text-muted-foreground">
          Manage company profile, subscription quotas (USD), and AI model configurations.
        </p>

        {/* Tab Switcher (admins only) */}
        {isAdmin && (
        <div className="mt-6 flex gap-2 border-b border-border pb-px text-xs font-medium">
          <button
            type="button"
            onClick={() => setTab('company')}
            className={`flex items-center gap-2 border-b-2 px-4 py-2 transition ${
              tab === 'company'
                ? 'border-foreground font-semibold text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Building2 className="size-3.5" /> Company Profile
          </button>
          <button
            type="button"
            onClick={() => setTab('plan')}
            className={`flex items-center gap-2 border-b-2 px-4 py-2 transition ${
              tab === 'plan'
                ? 'border-foreground font-semibold text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <CreditCard className="size-3.5" /> Plan &amp; Quotas
          </button>
          <button
            type="button"
            onClick={() => setTab('ai')}
            className={`flex items-center gap-2 border-b-2 px-4 py-2 transition ${
              tab === 'ai'
                ? 'border-foreground font-semibold text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Cpu className="size-3.5" /> AI Engine
          </button>
        </div>
        )}
      </header>

      {/* Tab 1: Company Profile */}
      {isAdmin && tab === 'company' && (
        <section className="mt-6">
          {compLoading ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading company profile…
            </p>
          ) : !profile ? (
            <p className="text-xs text-muted-foreground">No company attached to current session.</p>
          ) : (
            <form onSubmit={onSaveCompany} className="max-w-xl space-y-4">
              <div className="rounded-2xl border border-border bg-surface-2 p-4 text-xs">
                <p className="font-semibold text-foreground">Company Access Code</p>
                <div className="mt-1 flex items-center justify-between">
                  <span className="font-mono text-sm font-semibold tracking-wider text-foreground">
                    {profile.access_code || '—'}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    Share with partners for granular cross-tenant sharing
                  </span>
                </div>
              </div>

              <div>
                <label className={label}>Company Name</label>
                <input
                  required
                  value={compName}
                  onChange={(e) => setCompName(e.target.value)}
                  className={inputClass}
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className={label}>Website</label>
                  <input
                    value={compWebsite}
                    onChange={(e) => setCompWebsite(e.target.value)}
                    placeholder="https://acme.org"
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={label}>Contact Email</label>
                  <input
                    type="email"
                    value={compEmail}
                    onChange={(e) => setCompEmail(e.target.value)}
                    placeholder="info@acme.org"
                    className={inputClass}
                  />
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className={label}>Phone</label>
                  <input
                    value={compPhone}
                    onChange={(e) => setCompPhone(e.target.value)}
                    placeholder="+92 300 1234567"
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={label}>Seat Cap (Maximum Employees)</label>
                  <input
                    type="number"
                    min={1}
                    value={compMaxSeats}
                    onChange={(e) => setCompMaxSeats(e.target.value)}
                    placeholder="Leave blank for plan default"
                    className={inputClass}
                  />
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className={label}>HR Email (for generated emails)</label>
                  <input
                    type="email"
                    value={compHrEmail}
                    onChange={(e) => setCompHrEmail(e.target.value)}
                    placeholder="hr@acme.org"
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={label}>Default Tone</label>
                  <input
                    value={compTone}
                    onChange={(e) => setCompTone(e.target.value)}
                    placeholder="formal / friendly"
                    className={inputClass}
                  />
                </div>
              </div>

              <div>
                <label className={label}>Company Signature</label>
                <textarea
                  value={compSignature}
                  onChange={(e) => setCompSignature(e.target.value)}
                  rows={2}
                  placeholder="Regards, HR Team"
                  className={inputClass}
                />
              </div>

              <div className="pt-2">
                <button type="submit" disabled={savingComp} className={primaryBtn}>
                  {savingComp ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                  Save Profile
                </button>
              </div>
            </form>
          )}
        </section>
      )}

      {/* My profile — used to fill template fields */}
      {tab === 'company' && user && (
        <section className="mt-8 border-t border-border pt-6">
          <h2 className="text-sm font-semibold text-foreground">My Profile</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Only filled fields are used when generating forms and emails. Empty fields stay as
            [Field name] placeholders. Role and department are managed by your admin because
            they control document access.
          </p>
          <form onSubmit={onSaveProfile} className="mt-4 max-w-xl space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className={label}>Full Name</label>
                <input value={myName} onChange={(e) => setMyName(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={label}>Job Title</label>
                <input value={myTitle} onChange={(e) => setMyTitle(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={label}>Manager</label>
                <input value={myManager} onChange={(e) => setMyManager(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={label}>Employee ID</label>
                <input value={myEmployeeId} onChange={(e) => setMyEmployeeId(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={label}>Join Date</label>
                <input type="date" value={myJoinDate} onChange={(e) => setMyJoinDate(e.target.value)} className={inputClass} />
              </div>
            </div>
            <button type="submit" disabled={savingMe} className={primaryBtn}>
              {savingMe ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
              Save My Profile
            </button>
          </form>
        </section>
      )}

      {/* Tab 2: Plan & Usage */}
      {tab === 'plan' && (
        <section className="mt-6 space-y-8">
          {planLoading ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading plans and usage…
            </p>
          ) : (
            <>
              {/* Current Plan Overview & Usage Bars */}
              <div className="rounded-3xl border border-border bg-surface p-6 shadow-sm">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      Current Subscription
                    </span>
                    <h2 className="mt-1 text-2xl font-bold tracking-tight text-foreground">
                      {currentPlan?.name || 'Free'} Plan
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      ${currentPlan?.price_usd?.toLocaleString('en-US') || 0} / {currentPlan?.billing_period || 'month'}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {currentPlan?.allow_versions && (
                      <span className="rounded-full bg-ok-soft px-2.5 py-1 text-[11px] font-medium text-ok">
                        ✓ Versioning
                      </span>
                    )}
                    {currentPlan?.allow_departments && (
                      <span className="rounded-full bg-info-soft px-2.5 py-1 text-[11px] font-medium text-info">
                        ✓ Departments
                      </span>
                    )}
                    {currentPlan?.allow_custom_llm && (
                      <span className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-medium text-accent">
                        ✓ BYO AI Key
                      </span>
                    )}
                  </div>
                </div>

                {/* Usage bars */}
                <div className="mt-6 grid gap-4 border-t border-border pt-5 sm:grid-cols-2">
                  <div className="rounded-2xl border border-border bg-surface-2 p-4">
                    <div className="flex items-center justify-between text-xs font-medium">
                      <span className="flex items-center gap-1.5 text-foreground">
                        <MessageSquare className="size-3.5 text-muted-foreground" /> Monthly Questions
                      </span>
                      <span className="text-muted-foreground">
                        {analytics?.usage?.asks_this_month ?? 0} /{' '}
                        {currentPlan?.monthly_ask_limit ?? 'Unlimited'}
                      </span>
                    </div>
                    {currentPlan?.monthly_ask_limit ? (
                      <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-border">
                        <div
                          className="h-full bg-primary transition-all"
                          style={{
                            width: `${Math.min(
                              100,
                              ((analytics?.usage?.asks_this_month ?? 0) /
                                currentPlan.monthly_ask_limit) *
                                100,
                            )}%`,
                          }}
                        />
                      </div>
                    ) : null}
                  </div>

                  <div className="rounded-2xl border border-border bg-surface-2 p-4">
                    <div className="flex items-center justify-between text-xs font-medium">
                      <span className="flex items-center gap-1.5 text-foreground">
                        <Users className="size-3.5 text-muted-foreground" /> Member Seats
                      </span>
                      <span className="text-muted-foreground">
                        {profile?.max_employees || currentPlan?.max_members || 'Unlimited'} max
                      </span>
                    </div>
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      Admin controls seats in Company Profile.
                    </p>
                  </div>
                </div>
              </div>

              {/* USD Tier Table */}
              <div>
                <h3 className="text-sm font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  Available Tiers (USD)
                </h3>
                <div className="mt-4 grid gap-4 md:grid-cols-4">
                  {plans.map((p) => {
                    const isCurrent = currentPlan?.id === p.id
                    return (
                      <div
                        key={p.id}
                        className={`flex flex-col justify-between rounded-3xl border p-5 transition ${
                          isCurrent
                            ? 'border-foreground bg-surface-elevated ring-2 ring-foreground/10'
                            : 'border-border bg-surface'
                        }`}
                      >
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-foreground">{p.name}</span>
                            {isCurrent && (
                              <span className="rounded-full bg-primary px-2 py-0.5 text-[10px] text-primary-foreground">
                                Current
                              </span>
                            )}
                          </div>
                          <p className="mt-3 text-xl font-bold tracking-tight text-foreground">
                            ${p.price_usd.toLocaleString('en-US')}
                            <span className="text-xs font-normal text-muted-foreground">/mo</span>
                          </p>

                          <ul className="mt-4 space-y-2 text-xs text-muted-foreground">
                            <li className="flex items-center gap-2">
                              <Check className="size-3.5 text-ok" />
                              {p.max_members ? `${p.max_members} members` : 'Unlimited members'}
                            </li>
                            <li className="flex items-center gap-2">
                              <Check className="size-3.5 text-ok" />
                              {p.max_documents ? `${p.max_documents} docs` : 'Unlimited docs'}
                            </li>
                            <li className="flex items-center gap-2">
                              <Check className="size-3.5 text-ok" />
                              {p.storage_mb ? `${p.storage_mb >= 1024 ? `${p.storage_mb / 1024} GB` : `${p.storage_mb} MB`} storage` : 'Unlimited storage'}
                            </li>
                            <li className="flex items-center gap-2">
                              <Check className="size-3.5 text-ok" />
                              {p.monthly_ask_limit
                                ? `${p.monthly_ask_limit.toLocaleString()} asks/mo`
                                : 'Unlimited asks'}
                            </li>
                            {p.allow_versions && (
                              <li className="flex items-center gap-2">
                                <Check className="size-3.5 text-ok" /> File versioning
                              </li>
                            )}
                            {p.allow_departments && (
                              <li className="flex items-center gap-2">
                                <Check className="size-3.5 text-ok" /> Departments
                              </li>
                            )}
                            {p.allow_custom_llm && (
                              <li className="flex items-center gap-2">
                                <Check className="size-3.5 text-ok" /> BYO AI API Key
                              </li>
                            )}
                          </ul>
                        </div>

                        {!isCurrent && (
                          <div className="mt-6 border-t border-border pt-3 space-y-2">
                            {p.price_usd > 0 && (
                              <button
                                type="button"
                                onClick={() => onCheckout(p.id)}
                                disabled={upgradingPlanId === p.id}
                                className="inline-flex w-full items-center justify-center gap-1.5 rounded-full bg-primary py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                              >
                                {upgradingPlanId === p.id ? (
                                  <>
                                    <Loader2 className="size-3 animate-spin" />
                                    Redirecting…
                                  </>
                                ) : (
                                  <>
                                    <CreditCard className="size-3" />
                                    Upgrade to {p.name}
                                  </>
                                )}
                              </button>
                            )}
                            {isPlatformAdmin && (
                              <button
                                type="button"
                                onClick={() => onSelectPlan(p.id)}
                                className="w-full rounded-full border border-border-strong py-1.5 text-xs font-medium text-foreground hover:border-foreground hover:bg-primary hover:text-primary-foreground"
                              >
                                Assign Plan (Admin)
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </>
          )}
        </section>
      )}

      {/* Tab 3: AI Engine */}
      {tab === 'ai' && (
        <section className="mt-6">
          {aiLoading ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading AI engine settings…
            </p>
          ) : (
            <div className="max-w-2xl space-y-6">
              {/* Company Override Banner */}
              <div className="rounded-2xl border border-border bg-surface-2 p-4 text-xs">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-semibold text-foreground">
                      {hasLegacyProviderConfig
                        ? 'Legacy AI provider needs updating'
                        : cfg?.is_company_override
                        ? 'Custom Company Override Active'
                        : cfg?.platform_key_in_use
                        ? 'Platform Bedrock key in use'
                        : isPlatformAdmin
                        ? 'Platform Default Settings'
                        : 'Inheriting Platform Default AI'}
                    </span>
                    <p className="mt-0.5 text-muted-foreground">
                      {hasLegacyProviderConfig
                        ? 'Saving will switch this configuration to Bedrock. Its old provider key will be cleared; enter a Bedrock key or leave it blank to use your configured AWS credentials.'
                        : cfg?.is_company_override
                        ? 'Your organization is overriding the platform LLM with its own model/key.'
                        : cfg?.platform_key_in_use
                        ? 'Platform AWS Bedrock credentials and fast Nova Lite defaults are active for this workspace. You do not need to enter a key.'
                        : 'Currently using the system-wide default LLM provider.'}
                    </p>
                  </div>

                  {cfg?.is_company_override && (
                    <button
                      type="button"
                      onClick={onResetAi}
                      disabled={resettingAi}
                      className="inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-elevated px-3 py-1.5 text-xs text-danger hover:bg-danger-soft"
                    >
                      <RotateCcw className="size-3" />
                      {resettingAi ? 'Resetting…' : 'Reset to platform'}
                    </button>
                  )}
                </div>
              </div>

              <form onSubmit={onSaveAi} className="space-y-4">
                <div>
                  <label htmlFor="provider" className={label}>Provider</label>
                  <SmoothSelect<ActiveLlmProvider>
                    id="provider"
                    value={provider}
                    onChange={(val) => {
                      setProvider(val)
                      setTestResult(null)
                    }}
                    ariaLabel="AI Provider"
                    options={PROVIDERS.map((p) => ({
                      value: p.value,
                      label: p.label,
                      description: p.modelHint,
                      badge: p.badge,
                    }))}
                  />
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {activeProvider.blurb}
                    {activeProvider.badge && (
                      <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-ok-soft px-2 py-0.5 text-[10px] font-semibold text-ok">
                        <Check className="size-3" aria-hidden />
                        {activeProvider.badge}
                      </span>
                    )}
                  </p>
                </div>

                <div>
                  <label htmlFor="chat-model" className={label}>Model Name</label>
                  <input
                    id="chat-model"
                    value={chatModel}
                    onChange={(e) => setChatModel(e.target.value)}
                    placeholder={activeProvider.modelHint}
                    className={inputClass}
                  />
                </div>

                {activeProvider.usesBaseUrl && (
                  <div>
                    <label htmlFor="base-url" className={label}>
                      {provider === 'ollama'
                        ? 'Ollama URL'
                        : provider === 'bedrock'
                        ? 'AWS Region (optional)'
                        : 'Base URL (optional)'}
                    </label>
                    <input
                      id="base-url"
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                      placeholder={
                        provider === 'ollama'
                          ? 'http://localhost:11434'
                          : provider === 'bedrock'
                          ? BEDROCK_DEFAULT_REGION
                          : 'https://api.openai.com/v1'
                      }
                      className={inputClass}
                    />
                  </div>
                )}

                {activeProvider.keyLabel && (
                  <div>
                    <label htmlFor="api-key" className={label}>
                      {provider === 'bedrock' && cfg?.platform_key_in_use && !cfg?.is_company_override
                        ? 'Bedrock API key (optional)'
                        : activeProvider.keyLabel}
                    </label>
                    <div className="relative">
                      <KeyRound className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                      <input
                        id="api-key"
                        type="password"
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        placeholder={
                          cfg?.platform_key_in_use && !cfg?.is_company_override
                            ? 'Platform credentials active — leave blank to keep using them'
                            : cfg?.has_api_key && cfg.provider === provider
                              ? '•••••••• (stored, type to replace)'
                              : provider === 'bedrock'
                                ? 'Paste Bedrock key (or leave blank to use configured AWS CLI / IAM credentials)'
                                : 'Ollama does not require an API key'
                        }
                        className={`${inputClass} pl-10`}
                      />
                    </div>
                    {cfg?.platform_key_in_use && !cfg?.is_company_override && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        Using platform AWS CLI / IAM credentials automatically. Leave blank unless overriding for this company.
                      </p>
                    )}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="temperature" className={label}>Temperature</label>
                    <input
                      id="temperature"
                      type="number"
                      step="0.05"
                      min="0"
                      max="1"
                      value={temperature}
                      onChange={(e) => setTemperature(e.target.value)}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label htmlFor="max-tokens" className={label}>Max Tokens</label>
                    <input
                      id="max-tokens"
                      type="number"
                      min="64"
                      max="4096"
                      value={maxTokens}
                      onChange={(e) => setMaxTokens(e.target.value)}
                      className={inputClass}
                    />
                  </div>
                </div>

                {testResult && (
                  <div
                    className={`rounded-2xl border p-4 text-xs ${
                      testResult.ok
                        ? 'border-ok/30 bg-ok-soft text-ok'
                        : 'border-danger/30 bg-danger-soft text-danger'
                    }`}
                  >
                    <p className="font-semibold">
                      {testResult.ok ? 'Connection successful!' : 'Connection test failed.'}
                    </p>
                    <p className="mt-1">
                      {testResult.ok
                        ? `Tested model ${testResult.model} on ${testResult.provider}.`
                        : testResult.detail || 'Could not connect.'}
                    </p>
                    {testResult.sample && (
                      <p className="mt-2 rounded-xl bg-surface-elevated/80 p-2 font-mono text-[11px]">
                        {testResult.sample}
                      </p>
                    )}
                  </div>
                )}

                <div className="flex items-center gap-2 pt-2">
                  <button type="submit" disabled={savingAi} className={primaryBtn}>
                    {savingAi ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                    Save Configuration
                  </button>
                  <button
                    type="button"
                    onClick={onTestAi}
                    disabled={testingAi}
                    className={ghostBtn}
                  >
                    {testingAi ? <Loader2 className="size-3.5 animate-spin" /> : <PlugZap className="size-3.5" />}
                    Save & Test Connectivity
                  </button>
                </div>
              </form>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
