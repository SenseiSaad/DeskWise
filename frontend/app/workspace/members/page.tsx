'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  ArrowLeft,
  Briefcase,
  Building2,
  Check,
  CheckCircle2,
  Eye,
  FileText,
  Loader2,
  Lock,
  Pencil,
  Shield,
  ShieldAlert,
  Trash2,
  UserCheck,
  UserPlus,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  adminApi,
  companyApi2,
  JOB_TITLES,
  type Clearance,
  type Department,
  type EffectiveAccessResult,
  type NewUser,
  type Role,
  type User,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { toast } from '@/components/toaster'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useEscapeKey } from '@/lib/use-escape'
import { useWorkspaceStore } from '@/lib/workspace-store'

type AccessLevelId = 'viewer' | 'employee' | 'dept_manager' | 'admin'

interface AccessLevelSpec {
  id: AccessLevelId
  label: string
  role: Role
  isDeptAdmin: boolean
  defaultClearance: Clearance
  requiresDepartment: boolean
  adminOnly: boolean
  Icon: LucideIcon
  badgeCls: string
  can: string[]
  cannot: string[]
}

const ACCESS_LEVELS: AccessLevelSpec[] = [
  {
    id: 'viewer',
    label: 'Viewer',
    role: 'viewer',
    isDeptAdmin: false,
    defaultClearance: 'standard',
    requiresDepartment: false,
    adminOnly: false,
    Icon: Eye,
    badgeCls: 'border-border bg-surface-2 text-muted-foreground',
    can: [
      'Read & ask AI about Standard company documents',
      'Download approved documents within clearance',
    ],
    cannot: [
      'Upload, edit, or delete any documents',
      'See Internal or Confidential files without an audited override',
    ],
  },
  {
    id: 'employee',
    label: 'Employee',
    role: 'employee',
    isDeptAdmin: false,
    defaultClearance: 'internal',
    requiresDepartment: true,
    adminOnly: false,
    Icon: Briefcase,
    badgeCls: 'border-info/25 bg-info-soft text-info',
    can: [
      'Upload files & search Standard + Internal company/department docs',
      'Tighten visibility on documents they uploaded',
    ],
    cannot: [
      'Read Confidential files or other departments’ files',
      'Widen visibility, self-approve, or manage team members',
    ],
  },
  {
    id: 'dept_manager',
    label: 'Department manager',
    role: 'employee',
    isDeptAdmin: true,
    defaultClearance: 'internal',
    requiresDepartment: true,
    adminOnly: true,
    Icon: UserCheck,
    badgeCls: 'border-warn/25 bg-warn-soft text-warn',
    can: [
      'Manage & approve Standard/Internal docs in their own department',
      'Manage non-admin members & inspect access inside their department',
    ],
    cannot: [
      'Create/promote admins or raise clearance above Internal',
      'Read Confidential files, restricted files, or other departments',
    ],
  },
  {
    id: 'admin',
    label: 'Admin',
    role: 'admin',
    isDeptAdmin: false,
    defaultClearance: 'confidential',
    requiresDepartment: false,
    adminOnly: true,
    Icon: Shield,
    badgeCls: 'border-accent/25 bg-accent-soft text-accent',
    can: [
      'Manage workspace settings, members, audit log & Confidential docs',
      'Explain any member’s access & invoke audited break-glass if needed',
    ],
    cannot: [
      'Auto-read private restricted docs without an audited break-glass reason',
      'Demote or deactivate themselves or the last active admin',
    ],
  },
]

const CLEARANCE_OPTIONS: {
  value: Clearance
  label: string
  plain: string
  rank: number
}[] = [
  {
    value: 'standard',
    label: 'Standard',
    plain: 'Company-wide handbooks & general policies (default for Viewers)',
    rank: 1,
  },
  {
    value: 'internal',
    label: 'Internal',
    plain: 'Day-to-day operational & department documents (default for Employees)',
    rank: 2,
  },
  {
    value: 'confidential',
    label: 'Confidential',
    plain: 'Executive, payroll, legal & high-sensitivity files (Admin confirmation required)',
    rank: 3,
  },
]

const CLEARANCE_RANK: Record<Clearance, number> = {
  standard: 1,
  internal: 2,
  confidential: 3,
}

function userAccessLevel(u: User): AccessLevelId {
  if (u.role === 'admin') return 'admin'
  if (u.role === 'employee' && u.is_dept_admin && u.department_id) return 'dept_manager'
  if (u.role === 'employee') return 'employee'
  return 'viewer'
}

function userClearance(u: User): Clearance {
  if (u.effective_clearance) return u.effective_clearance
  if (u.clearance) return u.clearance
  if (u.role === 'admin') return 'confidential'
  if (u.role === 'viewer') return 'standard'
  return 'internal'
}

const inputClass =
  'h-11 w-full rounded-xl border border-border-strong bg-surface-elevated px-3.5 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-foreground focus:ring-2 focus:ring-foreground/10'
const labelClass = 'mb-1.5 block text-xs font-medium text-foreground'
const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/30 focus-visible:ring-offset-2 focus-visible:ring-offset-background'
const ghostBtn = `inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-elevated px-3 py-1.5 text-xs font-medium text-foreground transition hover:border-foreground disabled:opacity-50 ${focusRing}`
const primaryBtn = `inline-flex h-11 items-center justify-center gap-2 rounded-full bg-primary px-5 text-xs font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50 ${focusRing}`

function AccessLevelBadge({ user }: { user: User }) {
  const id = userAccessLevel(user)
  const spec = ACCESS_LEVELS.find((l) => l.id === id) ?? ACCESS_LEVELS[0]
  const Icon = spec.Icon
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${spec.badgeCls}`}
    >
      <Icon className="size-3" aria-hidden /> {spec.label}
    </span>
  )
}

function ClearanceBadge({ level }: { level: Clearance }) {
  const cls =
    level === 'confidential'
      ? 'bg-danger-soft text-danger'
      : level === 'internal'
      ? 'bg-info-soft text-info'
      : 'bg-surface-2 text-muted-foreground'
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize ${cls}`}>
      {level}
    </span>
  )
}

export default function MembersPage() {
  const { user } = useAuth()

  if (!user) return null
  const isCompanyAdmin = user.role === 'admin' || Boolean(user.is_platform_admin)
  const isDeptAdmin = user.role === 'employee' && Boolean(user.is_dept_admin) && Boolean(user.department_id)

  if (!isCompanyAdmin && !isDeptAdmin) {
    return (
      <div className="mx-auto max-w-lg py-10">
        <div className="rounded-2xl border border-border bg-surface p-8 text-center sm:p-10">
          <span className="mx-auto grid size-12 place-items-center rounded-full bg-surface-2 text-muted-foreground">
            <Lock className="size-5" aria-hidden />
          </span>
          <h1 className="mt-5 text-2xl font-semibold tracking-[-0.03em]">Admins &amp; managers only</h1>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
            Managing team access is limited to workspace administrators and department managers.
          </p>
          <Link
            href="/workspace"
            className={`mt-6 inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-xs font-medium text-primary-foreground transition-colors hover:opacity-90 ${focusRing}`}
          >
            <ArrowLeft className="size-4" aria-hidden /> Back to workspace
          </Link>
        </div>
      </div>
    )
  }

  return (
    <MembersAdmin
      currentUser={user}
      isCompanyAdmin={isCompanyAdmin}
    />
  )
}

function MembersAdmin({ currentUser, isCompanyAdmin }: { currentUser: User; isCompanyAdmin: boolean }) {
  const actorClearance = userClearance(currentUser)
  const actorMaxRank = isCompanyAdmin ? CLEARANCE_RANK[actorClearance] : CLEARANCE_RANK.internal

  const [users, setUsers] = useState<User[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  // New member form
  const { membersDraft, setMembersDraft } = useWorkspaceStore()
  const { fullName, title, departmentId, email, password, role, isDeptAdmin = false } = membersDraft
  const setFullName = (v: string) => setMembersDraft((s) => ({ ...s, fullName: v }))
  const setTitle = (v: string) => setMembersDraft((s) => ({ ...s, title: v }))
  const setDepartmentId = (v: number | '') => setMembersDraft((s) => ({ ...s, departmentId: v }))
  const setEmail = (v: string) => setMembersDraft((s) => ({ ...s, email: v }))
  const setPassword = (v: string) => setMembersDraft((s) => ({ ...s, password: v }))

  const selectedLevel: AccessLevelId =
    role === 'admin' ? 'admin' : role === 'employee' && isDeptAdmin ? 'dept_manager' : role === 'employee' ? 'employee' : 'viewer'
  const [clearance, setClearance] = useState<Clearance>('standard')
  const [inviteReason, setInviteReason] = useState('')
  const [pendingHighPrivSubmit, setPendingHighPrivSubmit] = useState(false)

  const selectAccessLevel = (lvl: AccessLevelId) => {
    const spec = ACCESS_LEVELS.find((x) => x.id === lvl) ?? ACCESS_LEVELS[0]
    setMembersDraft((s) => ({
      ...s,
      role: spec.role,
      isDeptAdmin: spec.isDeptAdmin,
      departmentId: !isCompanyAdmin && currentUser.department_id ? currentUser.department_id : s.departmentId,
    }))
    const capped = CLEARANCE_RANK[spec.defaultClearance] > actorMaxRank ? 'internal' : spec.defaultClearance
    setClearance(capped)
  }

  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')
  const [formSuccess, setFormSuccess] = useState('')

  // Edit / View-as / Delete dialogs
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [previewingUser, setPreviewingUser] = useState<User | null>(null)
  const [confirmUser, setConfirmUser] = useState<User | null>(null)
  const [removingId, setRemovingId] = useState<number | null>(null)

  // Department management (Company Admin)
  const [newDeptName, setNewDeptName] = useState('')
  const [deptSaving, setDeptSaving] = useState(false)
  const [deptError, setDeptError] = useState('')
  const [confirmDept, setConfirmDept] = useState<Department | null>(null)
  const [removingDeptId, setRemovingDeptId] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError('')
    Promise.all([
      adminApi.users(),
      companyApi2.departments().catch(() => []),
    ])
      .then(([usersRes, deptsRes]) => {
        setUsers(usersRes)
        setDepartments(deptsRes)
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : 'Could not load members.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const counts = useMemo(() => {
    const c = { total: users.length, admin: 0, activeAdmins: 0, deptManager: 0, employee: 0, viewer: 0 }
    for (const u of users) {
      if (u.role === 'admin') {
        c.admin += 1
        if (u.is_active !== false) c.activeAdmins += 1
      } else if (u.role === 'employee' && u.is_dept_admin) c.deptManager += 1
      else if (u.role === 'employee') c.employee += 1
      else if (u.role === 'viewer') c.viewer += 1
    }
    return c
  }, [users])

  const currentSpec = ACCESS_LEVELS.find((l) => l.id === selectedLevel) ?? ACCESS_LEVELS[0]
  const effectiveDeptId = !isCompanyAdmin ? (currentUser.department_id ?? '') : departmentId
  const isSensitiveInvite = selectedLevel === 'admin' || clearance === 'confidential'
  const deptRequiredNow = selectedLevel === 'dept_manager' || (currentSpec.requiresDepartment && departments.length > 0)

  async function onCreateDepartment(e: React.FormEvent) {
    e.preventDefault()
    const clean = newDeptName.trim()
    if (!clean) return
    setDeptError('')
    setDeptSaving(true)
    try {
      const created = await companyApi2.addDepartment(clean)
      setDepartments((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
      setNewDeptName('')
      if (!departmentId) setDepartmentId(created.id)
      toast.success(`Department "${created.name}" created.`)
    } catch (err) {
      setDeptError(err instanceof Error ? err.message : 'Could not create department.')
    } finally {
      setDeptSaving(false)
    }
  }

  async function onDeleteDepartment(dept: Department) {
    setRemovingDeptId(dept.id)
    setDeptError('')
    try {
      await companyApi2.removeDepartment(dept.id)
      setDepartments((prev) => prev.filter((d) => d.id !== dept.id))
      if (departmentId === dept.id) setDepartmentId('')
      setConfirmDept(null)
      toast.success(`Department "${dept.name}" removed. Its files were moved to Restricted.`)
      load()
    } catch (err) {
      setDeptError(err instanceof Error ? err.message : 'Could not delete department.')
    } finally {
      setRemovingDeptId(null)
    }
  }

  function validateCreate(): string | null {
    if (deptRequiredNow && !effectiveDeptId) {
      return `Please select a department — ${currentSpec.label} accounts must belong to a department.`
    }
    if (isSensitiveInvite && inviteReason.trim().length < 5) {
      return 'Please provide a brief audit reason (at least 5 characters) when granting Admin or Confidential clearance.'
    }
    return null
  }

  async function executeCreate() {
    setFormError('')
    setFormSuccess('')
    setSubmitting(true)
    const payload: NewUser = {
      email: email.trim(),
      password,
      role: currentSpec.role,
      clearance,
      ...(fullName.trim() ? { full_name: fullName.trim() } : {}),
      ...(title ? { title } : {}),
      ...(effectiveDeptId ? { department_id: Number(effectiveDeptId) } : {}),
      ...(isCompanyAdmin && currentSpec.isDeptAdmin && effectiveDeptId ? { is_dept_admin: true } : {}),
      ...(inviteReason.trim() ? { reason: inviteReason.trim() } : {}),
    }
    try {
      const created = await adminApi.createUser(payload)
      setUsers((prev) => [created, ...prev])
      setFullName('')
      setTitle('')
      setDepartmentId('')
      setEmail('')
      setPassword('')
      setInviteReason('')
      selectAccessLevel('viewer')
      setFormSuccess(`${created.full_name || created.email} was added as ${currentSpec.label} (${clearance} clearance).`)
      toast.success('Member invited & logged in audit trail.')
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Could not add this member.')
    } finally {
      setSubmitting(false)
      setPendingHighPrivSubmit(false)
    }
  }

  function onCreateSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const err = validateCreate()
    if (err) {
      setFormError(err)
      return
    }
    if (isSensitiveInvite) {
      setPendingHighPrivSubmit(true)
      return
    }
    void executeCreate()
  }

  async function onRemove(u: User) {
    if (u.id === currentUser.id) return
    const name = u.full_name || u.email
    setRemovingId(u.id)
    try {
      await adminApi.removeUser(u.id)
      setUsers((prev) => prev.filter((x) => x.id !== u.id))
      toast.success('Member removed.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Could not remove ${name}.`)
    } finally {
      setRemovingId(null)
      setConfirmUser(null)
    }
  }

  const availableLevels = ACCESS_LEVELS.filter((l) => isCompanyAdmin || !l.adminOnly)
  const selectedDeptName = departments.find((d) => d.id === Number(effectiveDeptId))?.name

  const stats = [
    { label: 'Total members', value: counts.total, Icon: Users, dot: '' },
    { label: 'Admins', value: counts.admin, Icon: Shield, dot: 'bg-accent' },
    { label: 'Managers & Staff', value: counts.deptManager + counts.employee, Icon: Briefcase, dot: 'bg-info' },
    { label: 'Viewers', value: counts.viewer, Icon: Eye, dot: 'bg-muted-foreground' },
  ]

  return (
    <div className="space-y-8 pb-8">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Member access &amp; clearance
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">
          Manage your team&rsquo;s <span className="font-serif font-normal italic">access.</span>
        </h1>
        <p className="mt-2 max-w-2xl text-xs leading-relaxed text-muted-foreground sm:text-sm">
          Choose an access level, assign a department, and set document clearance. Every permission change is
          enforced server-side across documents and AI answers, revokes active sessions immediately, and is recorded
          in the audit log.
        </p>
      </header>

      {loading ? (
        <LoadingState />
      ) : loadError ? (
        <ErrorState message={loadError} onRetry={load} />
      ) : (
        <>
          {/* Summary */}
          <section aria-label="Membership summary" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {stats.map((s) => {
              const Icon = s.Icon
              return (
                <div key={s.label} className="rounded-2xl border border-border bg-surface p-4">
                  <div className="flex items-center justify-between text-muted-foreground">
                    <span className="flex items-center gap-1.5 text-xs font-medium">
                      {s.dot ? <span className={`size-1.5 rounded-full ${s.dot}`} aria-hidden /> : null}
                      {s.label}
                    </span>
                    <Icon className="size-4 text-muted-foreground" aria-hidden />
                  </div>
                  <p className="mt-2 text-2xl font-semibold tracking-[-0.02em] text-foreground">
                    {s.value}
                  </p>
                </div>
              )
            })}
          </section>

          {/* Departments management (Company Admin) */}
          {isCompanyAdmin && (
            <section className="rounded-2xl border border-border bg-surface p-5 sm:p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-start gap-3">
                  <span className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-2 text-foreground">
                    <Building2 className="size-4" aria-hidden />
                  </span>
                  <div>
                    <h2 className="text-base font-semibold tracking-[-0.02em]">Departments</h2>
                    <p className="text-xs text-muted-foreground">
                      Organize members and scope documents to specific teams (e.g. Finance, HR, Engineering).
                    </p>
                  </div>
                </div>
                <form onSubmit={onCreateDepartment} className="flex w-full gap-2 sm:w-auto sm:min-w-[18rem]">
                  <input
                    type="text"
                    value={newDeptName}
                    onChange={(e) => setNewDeptName(e.target.value)}
                    placeholder="New department name…"
                    aria-label="New department name"
                    maxLength={120}
                    disabled={deptSaving}
                    className={inputClass}
                  />
                  <button
                    type="submit"
                    disabled={deptSaving || !newDeptName.trim()}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
                  >
                    {deptSaving ? <Loader2 className="size-3.5 animate-spin" /> : null}
                    Add
                  </button>
                </form>
              </div>

              {deptError && (
                <p role="alert" className="mt-3 flex items-center gap-1.5 rounded-xl border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
                  <AlertCircle className="size-3.5 shrink-0" aria-hidden /> {deptError}
                </p>
              )}

              <div className="mt-4 flex flex-wrap gap-2">
                {departments.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No departments yet. Create your first department above before adding Department Managers or department-scoped files.
                  </p>
                ) : (
                  departments.map((d) => (
                    <span
                      key={d.id}
                      className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs text-foreground"
                    >
                      <span className="font-medium">{d.name}</span>
                      <span className="text-[11px] text-muted-foreground">
                        {d.member_count} {d.member_count === 1 ? 'member' : 'members'}
                      </span>
                      <button
                        type="button"
                        onClick={() => setConfirmDept(d)}
                        disabled={removingDeptId === d.id}
                        aria-label={`Delete ${d.name} department`}
                        title={`Delete ${d.name}`}
                        className="rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-danger-soft hover:text-danger disabled:opacity-50"
                      >
                        {removingDeptId === d.id ? (
                          <Loader2 className="size-3 animate-spin" />
                        ) : (
                          <X className="size-3" />
                        )}
                      </button>
                    </span>
                  ))
                )}
              </div>
            </section>
          )}

          {/* Invite panel */}
          <section className="rounded-2xl border border-border bg-surface p-5 sm:p-7">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-2 text-foreground">
                <UserPlus className="size-4" aria-hidden />
              </span>
              <div>
                <h2 className="text-base font-semibold tracking-[-0.02em]">Invite a member</h2>
                <p className="text-xs text-muted-foreground">
                  Pick their access level and document clearance below. You can preview their exact document access anytime.
                </p>
              </div>
            </div>

            <form onSubmit={onCreateSubmit} className="mt-5 space-y-5">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="m-name" className={labelClass}>
                    Full name <span className="font-normal text-muted-foreground">(optional)</span>
                  </label>
                  <input
                    id="m-name"
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Ada Lovelace"
                    className={inputClass}
                    disabled={submitting}
                  />
                </div>
                <div>
                  <label htmlFor="m-email" className={labelClass}>
                    Work email
                  </label>
                  <input
                    id="m-email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="teammate@company.com"
                    className={inputClass}
                    disabled={submitting}
                  />
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="m-title" className={labelClass}>
                    Job title <span className="font-normal text-muted-foreground">(display only)</span>
                  </label>
                  <select
                    id="m-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className={inputClass}
                    disabled={submitting}
                  >
                    <option value="">No title</option>
                    {JOB_TITLES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="m-password" className={labelClass}>
                    Temporary password <span className="font-normal text-muted-foreground">(optional — leave blank to email invite link)</span>
                  </label>
                  <input
                    id="m-password"
                    type="password"
                    minLength={10}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Leave blank for 7-day invite link, or 10+ chars"
                    className={inputClass}
                    disabled={submitting}
                  />
                </div>
              </div>

              {/* Access level cards */}
              <fieldset disabled={submitting}>
                <legend className={labelClass}>Access level</legend>
                <div
                  role="radiogroup"
                  aria-label="Access level"
                  className="grid gap-3 sm:grid-cols-2"
                >
                  {availableLevels.map((lvl) => {
                    const Icon = lvl.Icon
                    const active = selectedLevel === lvl.id
                    return (
                      <label
                        key={lvl.id}
                        className={`flex cursor-pointer flex-col gap-2 rounded-2xl border p-4 transition ${
                          active
                            ? 'border-foreground bg-surface-elevated ring-2 ring-foreground/15'
                            : 'border-border-strong bg-surface hover:border-foreground/50'
                        }`}
                      >
                        <span className="flex items-center gap-2">
                          <input
                            type="radio"
                            name="access_level"
                            value={lvl.id}
                            checked={active}
                            onChange={() => selectAccessLevel(lvl.id)}
                            className="sr-only"
                          />
                          <Icon className="size-4 shrink-0 text-foreground" aria-hidden />
                          <span className="text-xs font-semibold text-foreground">{lvl.label}</span>
                          {active && <CheckCircle2 className="ml-auto size-4 text-foreground" aria-hidden />}
                        </span>
                        <ul className="space-y-1 text-[11px] leading-relaxed">
                          {lvl.can.map((line) => (
                            <li key={line} className="flex items-start gap-1.5 text-foreground/90">
                              <Check className="mt-0.5 size-3 shrink-0 text-ok" aria-hidden />
                              <span>{line}</span>
                            </li>
                          ))}
                          {lvl.cannot.map((line) => (
                            <li key={line} className="flex items-start gap-1.5 text-muted-foreground">
                              <X className="mt-0.5 size-3 shrink-0 text-danger" aria-hidden />
                              <span>{line}</span>
                            </li>
                          ))}
                        </ul>
                      </label>
                    )
                  })}
                </div>
              </fieldset>

              {/* Department + Clearance */}
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="m-dept" className={labelClass}>
                    Department{' '}
                    {deptRequiredNow ? (
                      <span className="font-semibold text-danger">* required</span>
                    ) : (
                      <span className="font-normal text-muted-foreground">(optional)</span>
                    )}
                  </label>
                  <select
                    id="m-dept"
                    value={effectiveDeptId}
                    onChange={(e) => setDepartmentId(e.target.value ? Number(e.target.value) : '')}
                    className={inputClass}
                    disabled={submitting || !isCompanyAdmin}
                    required={deptRequiredNow}
                  >
                    <option value="">
                      {deptRequiredNow ? 'Select a department…' : 'No department'}
                    </option>
                    {departments.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name} ({d.member_count} members)
                      </option>
                    ))}
                  </select>
                  {currentSpec.requiresDepartment && departments.length === 0 && (
                    <p className="mt-1 text-[11px] text-warn">
                      No departments exist yet. Create one in the Departments section above.
                    </p>
                  )}
                </div>

                <div>
                  <label htmlFor="m-clearance" className={labelClass}>
                    Document clearance
                  </label>
                  <select
                    id="m-clearance"
                    value={clearance}
                    onChange={(e) => setClearance(e.target.value as Clearance)}
                    className={inputClass}
                    disabled={submitting}
                  >
                    {CLEARANCE_OPTIONS.filter((opt) => opt.rank <= actorMaxRank).map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label} — {opt.plain}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Live Effective Access summary */}
              <div
                aria-live="polite"
                className="rounded-2xl border border-border bg-surface-2 p-4 text-xs"
              >
                <p className="font-semibold text-foreground">Live effective access summary</p>
                <p className="mt-1 leading-relaxed text-muted-foreground">
                  As <strong className="text-foreground">{currentSpec.label}</strong> with{' '}
                  <strong className="capitalize text-foreground">{clearance}</strong> clearance
                  {selectedDeptName ? (
                    <>
                      {' '}in <strong className="text-foreground">{selectedDeptName}</strong>
                    </>
                  ) : null}
                  , this person will be able to search and ask AI about{' '}
                  <strong className="text-foreground">
                    {clearance === 'standard'
                      ? 'Standard'
                      : clearance === 'internal'
                      ? 'Standard & Internal'
                      : 'Standard, Internal & Confidential'}
                  </strong>{' '}
                  approved{' '}
                  {selectedLevel === 'admin'
                    ? 'company-wide and department documents (never restricted private files without audited break-glass).'
                    : selectedDeptName
                    ? `company-wide and ${selectedDeptName} department documents.`
                    : 'company-wide documents only.'}
                </p>
              </div>

              {isSensitiveInvite && (
                <div>
                  <label htmlFor="m-reason" className={labelClass}>
                    Audit reason <span className="font-semibold text-danger">* required for Admin / Confidential</span>
                  </label>
                  <input
                    id="m-reason"
                    type="text"
                    required
                    minLength={5}
                    value={inviteReason}
                    onChange={(e) => setInviteReason(e.target.value)}
                    placeholder="e.g. Onboarding new Finance Director with audit clearance"
                    className={inputClass}
                    disabled={submitting}
                  />
                </div>
              )}

              {formError ? (
                <p
                  role="alert"
                  className="flex items-start gap-2 rounded-xl bg-danger-soft px-3.5 py-2.5 text-xs text-danger"
                >
                  <AlertCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {formError}
                </p>
              ) : null}
              {formSuccess ? (
                <p
                  role="status"
                  className="flex items-start gap-2 rounded-xl bg-ok-soft px-3.5 py-2.5 text-xs text-ok"
                >
                  <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {formSuccess}
                </p>
              ) : null}

              <div className="flex flex-wrap items-center gap-3 pt-1">
                <button type="submit" disabled={submitting} className={primaryBtn}>
                  {submitting ? (
                    <Loader2 className="size-3.5 animate-spin" aria-hidden />
                  ) : (
                    <UserPlus className="size-3.5" aria-hidden />
                  )}
                  {submitting ? 'Adding…' : 'Add member'}
                </button>
              </div>
            </form>
          </section>

          {/* Members list */}
          <section className="space-y-4">
            <h2 className="text-base font-semibold tracking-[-0.02em]">
              Members <span className="text-xs font-normal text-muted-foreground">({counts.total})</span>
            </h2>

            {counts.total === 0 ? (
              <div className="rounded-2xl border border-border bg-surface p-10 text-center">
                <p className="font-serif text-lg italic text-foreground">No members yet.</p>
              </div>
            ) : (
              <>
                {/* Desktop table */}
                <div className="hidden overflow-x-auto rounded-2xl border border-border bg-surface md:block">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border text-left uppercase tracking-[0.08em] text-muted-foreground">
                        <th scope="col" className="px-4 py-3 font-semibold">Member</th>
                        <th scope="col" className="px-4 py-3 font-semibold">Department</th>
                        <th scope="col" className="px-4 py-3 font-semibold">Access level</th>
                        <th scope="col" className="px-4 py-3 font-semibold">Clearance</th>
                        <th scope="col" className="px-4 py-3 font-semibold">Status</th>
                        <th scope="col" className="px-4 py-3 text-right font-semibold">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => {
                        const isSelf = u.id === currentUser.id
                        const isLastAdmin = u.role === 'admin' && u.is_active !== false && counts.activeAdmins <= 1
                        return (
                          <tr key={u.id} className="border-b border-border last:border-0 hover:bg-surface-2">
                            <td className="px-4 py-3.5">
                              <span className="flex items-center gap-1.5 font-medium text-foreground">
                                {u.full_name || u.email}
                                {isSelf && (
                                  <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                                    You
                                  </span>
                                )}
                              </span>
                              <span className="block text-[11px] text-muted-foreground">
                                {u.email}{u.title ? ` · ${u.title}` : ''}
                              </span>
                            </td>
                            <td className="px-4 py-3.5 text-muted-foreground">
                              {u.department_name ? (
                                <span className="inline-flex items-center gap-1 rounded bg-surface-2 px-2 py-0.5 text-[11px] text-muted-foreground">
                                  <Building2 className="size-2.5" aria-hidden />
                                  {u.department_name}
                                </span>
                              ) : (
                                '—'
                              )}
                            </td>
                            <td className="px-4 py-3.5">
                              <AccessLevelBadge user={u} />
                            </td>
                            <td className="px-4 py-3.5">
                              <ClearanceBadge level={userClearance(u)} />
                            </td>
                            <td className="px-4 py-3.5">
                              {u.is_active === false ? (
                                <span className="rounded-full bg-danger-soft px-2 py-0.5 text-[10px] font-medium text-danger">
                                  Deactivated
                                </span>
                              ) : (
                                <span className="rounded-full bg-ok-soft px-2 py-0.5 text-[10px] font-medium text-ok">
                                  Active
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-3.5 text-right">
                              <div className="inline-flex flex-wrap items-center justify-end gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => setPreviewingUser(u)}
                                  className={ghostBtn}
                                  title="Read-only preview of what this user can search & download"
                                >
                                  <Eye className="size-3" aria-hidden /> View as
                                </button>
                                {!isSelf && (
                                  <>
                                    <button
                                      type="button"
                                      onClick={() => setEditingUser(u)}
                                      className={ghostBtn}
                                      title="Edit member access"
                                    >
                                      <Pencil className="size-3" aria-hidden /> Edit
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setConfirmUser(u)}
                                      disabled={removingId === u.id || isLastAdmin}
                                      className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1.5 text-xs text-danger transition hover:bg-danger-soft disabled:cursor-not-allowed disabled:opacity-40"
                                      title={isLastAdmin ? 'Cannot remove the last active admin' : 'Remove member'}
                                      aria-label={`Remove ${u.full_name || u.email}`}
                                    >
                                      {removingId === u.id ? (
                                        <Loader2 className="size-3 animate-spin" aria-hidden />
                                      ) : (
                                        <Trash2 className="size-3" aria-hidden />
                                      )}
                                    </button>
                                  </>
                                )}
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Mobile cards (390px friendly) */}
                <ul className="space-y-3 md:hidden">
                  {users.map((u) => {
                    const isSelf = u.id === currentUser.id
                    const isLastAdmin = u.role === 'admin' && u.is_active !== false && counts.activeAdmins <= 1
                    return (
                      <li key={u.id} className="rounded-2xl border border-border bg-surface p-4 text-xs">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate font-semibold text-foreground">
                              {u.full_name || u.email}
                              {isSelf && (
                                <span className="ml-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-[10px] text-muted-foreground">
                                  You
                                </span>
                              )}
                            </p>
                            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{u.email}</p>
                            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                              <AccessLevelBadge user={u} />
                              <ClearanceBadge level={userClearance(u)} />
                              {u.department_name && (
                                <span className="rounded bg-surface-2 px-2 py-0.5 text-[10px] text-muted-foreground">
                                  {u.department_name}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-2.5">
                          <button
                            type="button"
                            onClick={() => setPreviewingUser(u)}
                            className={ghostBtn}
                          >
                            <Eye className="size-3" aria-hidden /> View as
                          </button>
                          {!isSelf && (
                            <>
                              <button
                                type="button"
                                onClick={() => setEditingUser(u)}
                                className={ghostBtn}
                              >
                                <Pencil className="size-3" aria-hidden /> Edit
                              </button>
                              <button
                                type="button"
                                onClick={() => setConfirmUser(u)}
                                disabled={removingId === u.id || isLastAdmin}
                                className="rounded-full border border-border px-3 py-1.5 text-xs text-danger hover:bg-danger-soft disabled:opacity-40"
                              >
                                Remove
                              </button>
                            </>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </section>
        </>
      )}

      {/* Confirm Admin / Confidential Invite */}
      <ConfirmDialog
        open={pendingHighPrivSubmit}
        title="Confirm elevated access"
        message={`You are inviting ${email || 'this member'} with ${currentSpec.label} access and ${clearance} clearance. Reason: "${inviteReason}". This grant is permanently logged in the audit trail.`}
        confirmText="Confirm & invite"
        danger={false}
        loading={submitting}
        onConfirm={() => void executeCreate()}
        onCancel={() => setPendingHighPrivSubmit(false)}
      />

      {/* Read-only "View as this user" Effective Access Modal */}
      {previewingUser && (
        <ViewAsUserModal
          user={previewingUser}
          onClose={() => setPreviewingUser(null)}
        />
      )}

      {/* Edit Member Modal */}
      {editingUser && (
        <EditMemberModal
          user={editingUser}
          departments={departments}
          isCompanyAdmin={isCompanyAdmin}
          actorMaxRank={actorMaxRank}
          isLastActiveAdmin={editingUser.role === 'admin' && editingUser.is_active !== false && counts.activeAdmins <= 1}
          onClose={() => setEditingUser(null)}
          onSaved={(updated) => {
            setUsers((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
          }}
        />
      )}

      {/* Confirm Delete Dialog */}
      <ConfirmDialog
        open={!!confirmUser}
        title="Remove member"
        message={
          confirmUser
            ? `Remove ${confirmUser.full_name || confirmUser.email}? They will immediately lose access to this workspace.`
            : ''
        }
        confirmText="Remove"
        danger={true}
        loading={confirmUser ? removingId === confirmUser.id : false}
        onConfirm={() => confirmUser && onRemove(confirmUser)}
        onCancel={() => setConfirmUser(null)}
      />

      <ConfirmDialog
        open={!!confirmDept}
        title={confirmDept ? `Delete ${confirmDept.name} department?` : ''}
        message="Department documents will be moved to Restricted (never company-wide), and any Department Managers in this department will be downgraded to standard members with active sessions signed out."
        confirmText="Delete department"
        danger={true}
        loading={confirmDept ? removingDeptId === confirmDept.id : false}
        onConfirm={() => confirmDept && onDeleteDepartment(confirmDept)}
        onCancel={() => setConfirmDept(null)}
      />
    </div>
  )
}

function ViewAsUserModal({ user, onClose }: { user: User; onClose: () => void }) {
  useEscapeKey(onClose)
  const [data, setData] = useState<EffectiveAccessResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    adminApi
      .effectiveAccess(user.id)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not compute effective access.'))
      .finally(() => setLoading(false))
  }, [user.id])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`View as ${user.full_name || user.email}`}
      className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-3xl border border-border bg-surface p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
          <div className="min-w-0">
            <p className="inline-flex items-center gap-1.5 rounded-full bg-info-soft px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-info">
              <Eye className="size-3" aria-hidden /> Read-only preview · Audited
            </p>
            <h2 className="mt-2 truncate text-base font-semibold text-foreground">
              Viewing as {user.full_name || user.email}
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {user.email} · {user.department_name || 'No department'} · Clearance:{' '}
              <span className="font-semibold capitalize text-foreground">{userClearance(user)}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close preview"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface-2"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="mt-4 min-h-0 flex-1 overflow-y-auto pr-1">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-xs text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Computing effective access…
            </div>
          ) : error ? (
            <p role="alert" className="rounded-xl bg-danger-soft p-3 text-xs text-danger">
              {error}
            </p>
          ) : data ? (
            <div className="space-y-4">
              <div className="rounded-2xl border border-border bg-surface-2 p-4">
                <p className="text-sm font-semibold text-foreground">
                  Can search {data.summary.searchable_count} of {data.summary.total_approved} approved documents · can
                  download {data.summary.downloadable_count}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Workspace library shows {data.summary.workspace_visible_count} of {data.summary.total_documents} total
                  company documents (including drafts/in-review they own or manage).
                </p>
              </div>

              {data.documents.length === 0 ? (
                <p className="rounded-xl border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
                  This user currently has no accessible documents.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.documents.map((doc) => (
                    <li
                      key={doc.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surface-elevated px-3.5 py-2.5 text-xs"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        <span className="truncate font-medium text-foreground">{doc.filename}</span>
                        <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] capitalize text-muted-foreground">
                          {doc.access_scope === 'department' ? doc.department_name || 'Department' : doc.access_scope}
                        </span>
                        <ClearanceBadge level={doc.sensitivity} />
                      </div>
                      <div className="flex items-center gap-1.5 text-[10px] font-medium">
                        {doc.can_search && (
                          <span className="rounded-full bg-ok-soft px-2 py-0.5 text-ok">AI searchable</span>
                        )}
                        {doc.can_download ? (
                          <span className="rounded-full bg-info-soft px-2 py-0.5 text-info">Download</span>
                        ) : (
                          <span className="rounded-full bg-surface-2 px-2 py-0.5 text-muted-foreground">View only</span>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function EditMemberModal({
  user,
  departments,
  isCompanyAdmin,
  actorMaxRank,
  isLastActiveAdmin,
  onClose,
  onSaved,
}: {
  user: User
  departments: Department[]
  isCompanyAdmin: boolean
  actorMaxRank: number
  isLastActiveAdmin: boolean
  onClose: () => void
  onSaved: (updated: User) => void
}) {
  useEscapeKey(onClose)
  const initialLevel = userAccessLevel(user)
  const initialClearance = userClearance(user)

  const [fullName, setFullName] = useState(user.full_name || '')
  const [title, setTitle] = useState(user.title || '')
  const [departmentId, setDepartmentId] = useState<number | ''>(user.department_id ?? '')
  const [level, setLevel] = useState<AccessLevelId>(initialLevel)
  const [clearance, setClearance] = useState<Clearance>(initialClearance)
  const [isActive, setIsActive] = useState<boolean>(user.is_active !== false)
  const [reason, setReason] = useState('')
  const [confirmElevate, setConfirmElevate] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const spec = ACCESS_LEVELS.find((l) => l.id === level) ?? ACCESS_LEVELS[0]
  const accessChanged =
    level !== initialLevel ||
    clearance !== initialClearance ||
    (departmentId || null) !== (user.department_id ?? null) ||
    isActive !== (user.is_active !== false)
  const elevatingToSensitive =
    (level === 'admin' && initialLevel !== 'admin') ||
    (clearance === 'confidential' && initialClearance !== 'confidential')

  function handleLevelChange(next: AccessLevelId) {
    setLevel(next)
    const nextSpec = ACCESS_LEVELS.find((l) => l.id === next) ?? ACCESS_LEVELS[0]
    const capped = CLEARANCE_RANK[nextSpec.defaultClearance] > actorMaxRank ? 'internal' : nextSpec.defaultClearance
    setClearance(capped)
  }

  async function executeSave() {
    setSubmitting(true)
    setError('')
    try {
      const updated = await adminApi.updateUser(user.id, {
        full_name: fullName.trim(),
        title: title || '',
        ...(isCompanyAdmin ? { department_id: departmentId ? Number(departmentId) : null } : {}),
        role: spec.role,
        ...(isCompanyAdmin ? { is_dept_admin: spec.isDeptAdmin } : {}),
        clearance,
        is_active: isActive,
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      })
      toast.success('Member access updated & logged in audit trail.')
      onSaved(updated)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update member.')
    } finally {
      setSubmitting(false)
      setConfirmElevate(false)
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (isLastActiveAdmin && (level !== 'admin' || !isActive)) {
      setError('Cannot demote or deactivate the last active admin.')
      return
    }
    if (spec.requiresDepartment && !departmentId) {
      setError(`${spec.label} accounts must belong to a department.`)
      return
    }
    if ((accessChanged && reason.trim().length < 5) && (elevatingToSensitive || !isActive)) {
      setError('Please enter a reason (at least 5 characters) for elevated access or deactivation.')
      return
    }
    if (elevatingToSensitive) {
      setConfirmElevate(true)
      return
    }
    void executeSave()
  }

  const editableLevels = ACCESS_LEVELS.filter((l) => isCompanyAdmin || !l.adminOnly)

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Edit ${user.full_name || user.email}`}
      className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-3xl border border-border bg-surface p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border pb-3">
          <h2 className="text-sm font-semibold text-foreground">
            Edit access: {user.full_name || user.email}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-muted-foreground hover:bg-surface-2"
          >
            <X className="size-4" />
          </button>
        </div>

        {isLastActiveAdmin && (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-warn-soft px-3 py-2 text-xs text-warn">
            <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            This is the last active admin — demotion and deactivation are disabled.
          </p>
        )}

        <form onSubmit={onSubmit} className="mt-4 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="e-name" className={labelClass}>Full name</label>
              <input
                id="e-name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="e-title" className={labelClass}>Job title</label>
              <select
                id="e-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className={inputClass}
              >
                <option value="">No title</option>
                {JOB_TITLES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <fieldset>
            <legend className={labelClass}>Access level</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {editableLevels.map((lvl) => {
                const Icon = lvl.Icon
                const active = level === lvl.id
                const blocked = isLastActiveAdmin && lvl.id !== 'admin'
                return (
                  <label
                    key={lvl.id}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-xs transition ${
                      blocked
                        ? 'cursor-not-allowed border-border bg-surface-2 opacity-50'
                        : active
                        ? 'cursor-pointer border-foreground bg-surface-elevated ring-2 ring-foreground/15'
                        : 'cursor-pointer border-border-strong bg-surface hover:border-foreground/50'
                    }`}
                  >
                    <input
                      type="radio"
                      name="edit_access_level"
                      value={lvl.id}
                      checked={active}
                      disabled={blocked}
                      onChange={() => handleLevelChange(lvl.id)}
                      className="sr-only"
                    />
                    <Icon className="size-3.5 shrink-0" aria-hidden />
                    <span className="font-medium text-foreground">{lvl.label}</span>
                    {active && <CheckCircle2 className="ml-auto size-3.5 text-foreground" aria-hidden />}
                  </label>
                )
              })}
            </div>
          </fieldset>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="e-dept" className={labelClass}>
                Department {spec.requiresDepartment && <span className="text-danger">*</span>}
              </label>
              <select
                id="e-dept"
                value={departmentId}
                onChange={(e) => setDepartmentId(e.target.value ? Number(e.target.value) : '')}
                className={inputClass}
                disabled={!isCompanyAdmin}
                required={spec.requiresDepartment}
              >
                <option value="">{spec.requiresDepartment ? 'Select a department…' : 'No department'}</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="e-clr" className={labelClass}>Document clearance</label>
              <select
                id="e-clr"
                value={clearance}
                onChange={(e) => setClearance(e.target.value as Clearance)}
                className={inputClass}
              >
                {CLEARANCE_OPTIONS.filter((opt) => opt.rank <= actorMaxRank).map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <label className="flex items-center gap-2 pt-1 text-xs text-foreground">
            <input
              type="checkbox"
              checked={isActive}
              disabled={isLastActiveAdmin}
              onChange={(e) => setIsActive(e.target.checked)}
              className="size-4 rounded accent-primary"
            />
            <span>Account is active (unchecking revokes all sessions immediately)</span>
          </label>

          {accessChanged && (
            <div>
              <label htmlFor="e-reason" className={labelClass}>
                Reason for change{' '}
                {elevatingToSensitive || !isActive ? (
                  <span className="font-semibold text-danger">* required</span>
                ) : (
                  <span className="font-normal text-muted-foreground">(recorded in audit log)</span>
                )}
              </label>
              <input
                id="e-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Role transfer to Finance team"
                className={inputClass}
              />
            </div>
          )}

          {error && (
            <p role="alert" className="rounded-xl bg-danger-soft px-3 py-2 text-xs text-danger">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className={ghostBtn}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} className={primaryBtn}>
              {submitting ? <Loader2 className="size-3.5 animate-spin" /> : 'Save changes'}
            </button>
          </div>
        </form>

        <ConfirmDialog
          open={confirmElevate}
          title="Confirm elevated privileges"
          message={`Grant ${user.full_name || user.email} ${spec.label} access (${clearance} clearance)? Their existing tokens will be revoked and this change will be logged in the audit trail.`}
          confirmText="Confirm & save"
          danger={false}
          loading={submitting}
          onConfirm={() => void executeSave()}
          onCancel={() => setConfirmElevate(false)}
        />
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="space-y-6" aria-hidden>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-20 animate-pulse rounded-2xl border border-border bg-surface-2" />
        ))}
      </div>
      <div className="h-72 animate-pulse rounded-2xl border border-border bg-surface-2" />
      <div className="h-40 animate-pulse rounded-2xl border border-border bg-surface-2" />
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-10 text-center">
      <span className="mx-auto grid size-11 place-items-center rounded-full bg-danger-soft text-danger">
        <AlertCircle className="size-5" aria-hidden />
      </span>
      <p className="mt-4 text-sm font-medium text-foreground">We couldn&rsquo;t load your members.</p>
      <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className={`mt-5 inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-xs font-medium text-primary-foreground transition-colors hover:opacity-90 ${focusRing}`}
      >
        Try again
      </button>
    </div>
  )
}
