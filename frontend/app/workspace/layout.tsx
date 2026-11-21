'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import {
  ChevronDown,
  FileText,
  Gauge,
  Languages,
  LayoutDashboard,
  Loader2,
  LogOut,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  QrCode,
  ScrollText,
  Settings,
  Share2,
  Shield,
  Sparkles,
  Users,
} from 'lucide-react'
import { useAuth } from '@/lib/auth'
import { isUiLanguage, type UiLanguage } from '@/lib/api'
import { Logo } from '@/components/logo'
import { ThemeToggle } from '@/components/theme-toggle'
import { SmoothSelect, type SmoothSelectOption } from '@/components/ui/smooth-select'
import { adminApi, type AdminCompany } from '@/lib/api'
import { makeT } from '@/lib/i18n'
import { WorkspaceStoreProvider } from '@/lib/workspace-store'
import { WorkspaceBackgroundStatusPill } from '@/components/workspace-bg-status'

const LANGUAGE_OPTIONS: SmoothSelectOption<string>[] = [
  { value: 'en', label: 'English', description: 'Default workspace UI & answers', badge: 'EN' },
  { value: 'es', label: 'Spanish', description: 'Español', badge: 'ES' },
  { value: 'fr', label: 'French', description: 'Français', badge: 'FR' },
  { value: 'de', label: 'German', description: 'Deutsch', badge: 'DE' },
  { value: 'ar', label: 'Arabic', description: 'العربية', badge: 'AR' },
  { value: 'pt', label: 'Portuguese', description: 'Português', badge: 'PT' },
  { value: 'ur', label: 'Roman Urdu', description: 'Urdu (Latin script)', badge: 'UR' },
  { value: '__more', label: 'More languages', description: 'Additional locales coming soon', badge: 'Soon', disabled: true },
]

// Authenticated, tenant-scoped shell for the enterprise workspace. Gates on a
// signed-in session client-side and redirects guests to the enterprise sign-in.
export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, sessionExpired, isEnterprise, logout, refreshUser, isPlatformAdmin, language, setLanguage } = useAuth()
  const router = useRouter()
  const pathname = usePathname()
  const t = makeT(language)

  const [companies, setCompanies] = useState<AdminCompany[]>([])
  const [switching, setSwitching] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  useEffect(() => {
    try {
      if (window.localStorage.getItem('deskwise:sidebar-collapsed') === '1') {
        setSidebarCollapsed(true)
      }
    } catch {
      // ignore storage errors
    }
  }, [])

  function toggleSidebar() {
    setSidebarCollapsed((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem('deskwise:sidebar-collapsed', next ? '1' : '0')
      } catch {
        // ignore storage errors
      }
      return next
    })
  }

  useEffect(() => {
    if (isPlatformAdmin) {
      adminApi.companies().then(setCompanies).catch(() => setCompanies([]))
    }
  }, [isPlatformAdmin])

  useEffect(() => {
    if (!loading && !isEnterprise) {
      const nextParam = encodeURIComponent(pathname || '/workspace')
      router.replace(`/enterprise?next=${nextParam}${sessionExpired ? '&expired=1' : ''}`)
    }
  }, [loading, isEnterprise, sessionExpired, router, pathname])

  useEffect(() => {
    const titles: Record<string, string> = {
      '/workspace': 'Overview',
      '/workspace/chat': 'Ask AI',
      '/workspace/team-chat': 'Team Chat',
      '/workspace/documents': 'Documents',
      '/workspace/shared': 'Shared with me',
      '/workspace/attendance': 'Attendance',
      '/workspace/members': 'Members',
      '/workspace/audit': 'Audit log',
      '/workspace/usage': 'Usage & plan',
      '/workspace/settings': 'Settings',
    }
    const key = Object.keys(titles)
      .filter((href) => href !== '/workspace' && pathname.startsWith(href))
      .sort((a, b) => b.length - a.length)[0]
    const section = titles[pathname] ?? (key ? titles[key] : 'Workspace')
    const desired = `${section} · Deskwise`

    // The authenticated shell owns its browser title. Next's metadata manager can
    // overwrite document.title during client navigation, so keep this tab's title
    // stable for as long as the workspace layout is mounted.
    document.title = desired
    let queued = false
    const enforce = () => {
      if (queued) return
      queued = true
      queueMicrotask(() => {
        queued = false
        if (document.title !== desired) document.title = desired
      })
    }
    const observer = new MutationObserver(enforce)
    observer.observe(document.head, { subtree: true, childList: true, characterData: true })
    return () => observer.disconnect()
  }, [pathname])

  if (loading || !isEnterprise || !user) {
    return (
      <main className="grid min-h-dvh place-items-center bg-background text-muted-foreground">
        <span className="flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" /> {t('loading')}</span>
      </main>
    )
  }

  const isAdmin = user.role === 'admin' || isPlatformAdmin
  const isDeptAdmin = user.role === 'employee' && Boolean(user.is_dept_admin) && Boolean(user.department_id)
  const comp = user.company
  const NAV = [
    { href: '/workspace', label: t('overview'), icon: LayoutDashboard, adminOnly: false, deptAdminOk: false, exact: true, enabled: true },
    { href: '/workspace/chat', label: t('askAi'), icon: Sparkles, adminOnly: false, deptAdminOk: false, exact: false, enabled: comp?.enable_ai_chat !== false },
    { href: '/workspace/team-chat', label: t('teamChat'), icon: MessagesSquare, adminOnly: false, deptAdminOk: false, exact: false, enabled: comp?.enable_team_chat === true },
    { href: '/workspace/documents', label: t('documents'), icon: FileText, adminOnly: false, deptAdminOk: false, exact: false, enabled: true },
    { href: '/workspace/shared', label: t('shared'), icon: Share2, adminOnly: false, deptAdminOk: false, exact: false, enabled: true },
    { href: '/workspace/attendance', label: t('attendance'), icon: QrCode, adminOnly: false, deptAdminOk: false, exact: false, enabled: comp?.enable_attendance === true },
    { href: '/workspace/members', label: t('members'), icon: Users, adminOnly: true, deptAdminOk: true, exact: false, enabled: true },
    { href: '/workspace/audit', label: t('audit'), icon: ScrollText, adminOnly: true, deptAdminOk: false, exact: false, enabled: true },
    { href: '/workspace/usage', label: t('usagePlan'), icon: Gauge, adminOnly: true, deptAdminOk: false, exact: false, enabled: true },
    { href: '/workspace/settings', label: t('settings'), icon: Settings, adminOnly: true, deptAdminOk: false, exact: false, enabled: true },
  ]
  const items = NAV.filter((n) => n.enabled && (!n.adminOnly || isAdmin || (n.deptAdminOk && isDeptAdmin)))
  const active = (n: (typeof NAV)[number]) => (n.exact ? pathname === n.href : pathname === n.href || pathname.startsWith(n.href + '/'))

  async function handleSwitchCompany(newCompanyId: number) {
    setSwitching(true)
    try {
      if (newCompanyId === 0) {
        await adminApi.detachCompany()
      } else {
        await adminApi.switchCompany(newCompanyId)
      }
      await refreshUser()
      router.refresh()
    } catch (err) {
      console.error(err)
    } finally {
      setSwitching(false)
    }
  }

  return (
    <WorkspaceStoreProvider>
      <div className="min-h-dvh bg-background text-foreground">
        <div className="mx-auto flex max-w-7xl flex-col lg:flex-row">
        {/* Sidebar (desktop) / top bar (mobile) */}
        <aside
          className={`border-b border-border transition-[width] duration-200 lg:sticky lg:top-0 lg:flex lg:h-dvh lg:shrink-0 lg:flex-col lg:border-b-0 lg:border-r lg:overflow-hidden ${
            sidebarCollapsed ? 'lg:w-[4.5rem]' : 'lg:w-64'
          }`}
        >
          <div
            className={`flex items-center gap-2 py-3.5 lg:py-4 ${
              sidebarCollapsed ? 'justify-between px-5 lg:justify-center lg:px-2' : 'justify-between px-5'
            }`}
          >
            <div className={sidebarCollapsed ? 'lg:hidden' : ''}>
              <Logo href="/workspace" />
            </div>
            <span className="rounded-full border border-border px-2 py-1 font-mono text-[8px] uppercase tracking-[0.12em] text-muted-foreground lg:hidden">
              Workspace
            </span>
            <button
              type="button"
              onClick={toggleSidebar}
              aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-expanded={!sidebarCollapsed}
              title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              className="hidden size-8 shrink-0 place-items-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground lg:grid"
            >
              {sidebarCollapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            </button>
          </div>

          {isPlatformAdmin && !sidebarCollapsed && (
            <div className="mx-3 mb-2 rounded-xl border border-accent/25 bg-accent-soft p-2.5 text-xs text-accent">
              <div className="flex items-center gap-1.5 font-semibold">
                <Shield className="size-3.5" />
                <span>Platform Admin</span>
              </div>
              <div className="mt-1.5">
                <label className="mb-0.5 block text-[9px] uppercase tracking-wider text-muted-foreground">
                  Active Company:
                </label>
                <div className="relative">
                  <select
                    value={user.company_id || 0}
                    onChange={(e) => handleSwitchCompany(Number(e.target.value))}
                    disabled={switching}
                    className="w-full appearance-none rounded-lg border border-border bg-surface py-1 pl-2 pr-7 text-xs font-medium text-foreground outline-none focus:border-border-strong"
                  >
                    <option value={0}>All tenants (detached)</option>
                    {companies.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} ({c.doc_count} docs)
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-2 top-2 size-3.5 text-muted-foreground" />
                </div>
              </div>
            </div>
          )}

          <nav
            aria-label="Workspace"
            className={`flex gap-1 overflow-x-auto pb-2 no-scrollbar lg:mt-1 lg:min-h-0 lg:flex-1 lg:flex-col lg:overflow-y-auto ${
              sidebarCollapsed ? 'px-3 lg:px-2' : 'px-3'
            }`}
          >
            {items.map((n) => {
              const Icon = n.icon
              const on = active(n)
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={on ? 'page' : undefined}
                  title={sidebarCollapsed ? n.label : undefined}
                  className={`flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition-colors lg:text-[13px] ${
                    sidebarCollapsed ? 'lg:justify-center lg:px-0 lg:py-2' : ''
                  } ${
                    on
                      ? 'bg-primary text-primary-foreground font-semibold'
                      : 'text-muted-foreground hover:bg-surface-2 hover:text-foreground'
                  }`}
                >
                  <Icon className="size-4 shrink-0" />
                  <span className={sidebarCollapsed ? 'lg:sr-only' : ''}>{n.label}</span>
                </Link>
              )
            })}
          </nav>

          {/* Mobile account and appearance controls */}
          <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3 lg:hidden">
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">{user.full_name || user.email}</p>
              <p className="mt-0.5 truncate text-[10px] capitalize text-muted-foreground">
                {user.department_name ? `${user.role} · ${user.department_name}` : user.role}
              </p>
            </div>
            <div className="w-36 shrink-0">
              <SmoothSelect
                value={language}
                onChange={(val) => {
                  if (isUiLanguage(val)) setLanguage(val)
                }}
                options={LANGUAGE_OPTIONS}
                size="pill"
                align="right"
                leadingIcon={<Languages className="size-3.5" aria-hidden />}
                ariaLabel="Reply language"
              />
            </div>
            <ThemeToggle variant="segmented" compact />
            <button
              onClick={logout}
              aria-label={t('logout')}
              className="grid size-8 shrink-0 place-items-center rounded-full border border-border text-danger transition-colors hover:bg-danger-soft"
            >
              <LogOut className="size-3.5" />
            </button>
          </div>

          <div className={`hidden pb-3 lg:block lg:shrink-0 ${sidebarCollapsed ? 'px-2' : 'px-3'}`}>
            <div className="mx-2 mb-2.5 h-px bg-border" />
            {sidebarCollapsed ? (
              <div className="flex flex-col items-center gap-2">
                <ThemeToggle variant="segmented" compact />
                <button
                  type="button"
                  onClick={logout}
                  aria-label={t('logout')}
                  title={t('logout')}
                  className="grid size-8 place-items-center rounded-lg border border-border text-danger transition-colors hover:bg-danger-soft"
                >
                  <LogOut className="size-3.5" />
                </button>
              </div>
            ) : (
            <div className="rounded-xl border border-border bg-surface p-2.5 text-xs">
              <p className="truncate text-xs font-semibold text-foreground">{user.full_name || user.email}</p>
              <p className="mt-0.5 truncate text-[11px] capitalize text-muted-foreground">
                {user.department_name ? `${user.role} · ${user.department_name}` : user.role}
              </p>

              {/* Preferences: Language + Appearance in one compact row */}
              <div className="mt-2.5 flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <SmoothSelect
                    value={language}
                    onChange={(val) => {
                      if (isUiLanguage(val)) setLanguage(val)
                    }}
                    options={LANGUAGE_OPTIONS}
                    size="pill"
                    leadingIcon={<Languages className="size-3.5" aria-hidden />}
                    ariaLabel="Reply language"
                  />
                </div>
                <ThemeToggle variant="segmented" compact />
              </div>

              {/* Actions row */}
              <div className="mt-2.5 flex items-center justify-between border-t border-border pt-2 text-[11px]">
                <Link href="/" className="text-muted-foreground transition-colors hover:text-foreground">
                  {t('backToLanding')}
                </Link>
                <button
                  onClick={logout}
                  className="flex items-center gap-1 font-medium text-danger transition-opacity hover:opacity-80"
                >
                  <LogOut className="size-3" /> {t('logout')}
                </button>
              </div>
            </div>
            )}
          </div>
        </aside>

        {/* Content */}
        <div className="min-w-0 flex-1 px-4 py-5 sm:px-6 lg:px-10 lg:py-10">{children}</div>
      </div>
      <WorkspaceBackgroundStatusPill />
    </div>
    </WorkspaceStoreProvider>
  )
}
