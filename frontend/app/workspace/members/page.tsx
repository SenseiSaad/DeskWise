'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  ArrowLeft,
  Briefcase,
  Building2,
  CheckCircle2,
  Eye,
  Loader2,
  Lock,
  Pencil,
  Shield,
  Trash2,
  UserPlus,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  adminApi,
  companyApi2,
  JOB_TITLES,
  type Department,
  type NewUser,
  type Role,
  type User,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { toast } from '@/components/toaster'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useEscapeKey } from '@/lib/use-escape'
import { useWorkspaceStore } from '@/lib/workspace-store'

type CreatableRole = Exclude<Role, 'public'>

const ROLE_BADGE: Record<Role, { label: string; cls: string; Icon: LucideIcon }> = {
  admin: { label: 'Admin', cls: 'border-accent/25 bg-accent-soft text-accent', Icon: Shield },
  employee: { label: 'Employee', cls: 'border-info/25 bg-info-soft text-info', Icon: Briefcase },
  viewer: { label: 'Viewer', cls: 'border-border bg-surface-2 text-muted-foreground', Icon: Eye },
}

const ROLE_OPTIONS: { value: CreatableRole; label: string; desc: string; Icon: LucideIcon }[] = [
  { value: 'admin', label: 'Admin', desc: 'Full control, plus member management.', Icon: Shield },
  { value: 'employee', label: 'Employee', desc: 'Upload and manage documents.', Icon: Briefcase },
  { value: 'viewer', label: 'Viewer', desc: 'Read-only access to the library.', Icon: Eye },
]

const inputClass =
  'h-11 w-full rounded-xl border border-border-strong bg-surface-elevated px-3.5 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-foreground focus:ring-2 focus:ring-foreground/10'
const labelClass = 'mb-1.5 block text-xs font-medium text-foreground'
const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/30 focus-visible:ring-offset-2 focus-visible:ring-offset-background'
const ghostBtn = `inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-elevated px-3 py-1.5 text-xs font-medium text-foreground transition hover:border-foreground disabled:opacity-50 ${focusRing}`
const primaryBtn = `inline-flex h-11 items-center justify-center gap-2 rounded-full bg-primary px-5 text-xs font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50 ${focusRing}`

function RoleBadge({ role }: { role: Role }) {
  const meta = ROLE_BADGE[role] ?? ROLE_BADGE.viewer
  const Icon = meta.Icon
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${meta.cls}`}
    >
      <Icon className="size-3" aria-hidden /> {meta.label}
    </span>
  )
}

export default function MembersPage() {
  const { user } = useAuth()

  if (!user) return null

  if (user.role !== 'admin') {
    return (
      <div className="mx-auto max-w-lg py-10">
        <div className="rounded-2xl border border-border bg-surface p-8 text-center sm:p-10">
          <span className="mx-auto grid size-12 place-items-center rounded-full bg-surface-2 text-muted-foreground">
            <Lock className="size-5" aria-hidden />
          </span>
          <h1 className="mt-5 text-2xl font-semibold tracking-[-0.03em]">Admins only</h1>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
            Managing team membership is limited to administrators.
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

  return <MembersAdmin currentUserId={user.id} />
}

function MembersAdmin({ currentUserId }: { currentUserId: number }) {
  const [users, setUsers] = useState<User[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  // New member form
  const { membersDraft, setMembersDraft } = useWorkspaceStore()
  const { fullName, title, departmentId, email, password, role } = membersDraft
  const setFullName = (v: string) => setMembersDraft((s) => ({ ...s, fullName: v }))
  const setTitle = (v: string) => setMembersDraft((s) => ({ ...s, title: v }))
  const setDepartmentId = (v: number | '') => setMembersDraft((s) => ({ ...s, departmentId: v }))
  const setEmail = (v: string) => setMembersDraft((s) => ({ ...s, email: v }))
  const setPassword = (v: string) => setMembersDraft((s) => ({ ...s, password: v }))
  const setRole = (v: CreatableRole) => setMembersDraft((s) => ({ ...s, role: v }))
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')
  const [formSuccess, setFormSuccess] = useState('')

  // Edit / Delete dialogs
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [confirmUser, setConfirmUser] = useState<User | null>(null)
  const [removingId, setRemovingId] = useState<number | null>(null)

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
    const c = { total: users.length, admin: 0, employee: 0, viewer: 0 }
    for (const u of users) {
      if (u.role === 'admin') c.admin += 1
      else if (u.role === 'employee') c.employee += 1
      else if (u.role === 'viewer') c.viewer += 1
    }
    return c
  }, [users])

  async function onCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setFormError('')
    setFormSuccess('')
    setSubmitting(true)
    const payload: NewUser = {
      email: email.trim(),
      password,
      role,
      ...(fullName.trim() ? { full_name: fullName.trim() } : {}),
      ...(title ? { title } : {}),
      ...(departmentId ? { department_id: Number(departmentId) } : {}),
    }
    try {
      const created = await adminApi.createUser(payload)
      setUsers((prev) => [created, ...prev])
      setFullName('')
      setTitle('')
      setDepartmentId('')
      setEmail('')
      setPassword('')
      setRole('viewer')
      setFormSuccess(`${created.full_name || created.email} was added as ${created.role}.`)
      toast.success('Member invited.')
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Could not add this member.')
    } finally {
      setSubmitting(false)
    }
  }

  async function onRemove(u: User) {
    if (u.id === currentUserId) return
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

  const stats = [
    { label: 'Total members', value: counts.total, Icon: Users, dot: '' },
    { label: 'Admins', value: counts.admin, Icon: Shield, dot: 'bg-accent' },
    { label: 'Employees', value: counts.employee, Icon: Briefcase, dot: 'bg-info' },
    { label: 'Viewers', value: counts.viewer, Icon: Eye, dot: 'bg-muted-foreground' },
  ]

  return (
    <div className="space-y-8 pb-8">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Member management
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">
          Manage your team&rsquo;s <span className="font-serif font-normal italic">access.</span>
        </h1>
        <p className="mt-2 max-w-xl text-xs leading-relaxed text-muted-foreground sm:text-sm">
          Invite teammates, assign departments and roles, and adjust permissions at any time.
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

          {/* Invite panel */}
          <section className="rounded-2xl border border-border bg-surface p-5 sm:p-7">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-2 text-foreground">
                <UserPlus className="size-4" aria-hidden />
              </span>
              <div>
                <h2 className="text-base font-semibold tracking-[-0.02em]">Invite a member</h2>
                <p className="text-xs text-muted-foreground">
                  Create an account for a teammate. They sign in with their work email.
                </p>
              </div>
            </div>

            <form onSubmit={onCreate} className="mt-5 space-y-4">
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
                    Email
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
                    Job title <span className="font-normal text-muted-foreground">(optional)</span>
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
                  <label htmlFor="m-dept" className={labelClass}>
                    Department <span className="font-normal text-muted-foreground">(optional)</span>
                  </label>
                  <select
                    id="m-dept"
                    value={departmentId}
                    onChange={(e) => setDepartmentId(e.target.value ? Number(e.target.value) : '')}
                    className={inputClass}
                    disabled={submitting}
                  >
                    <option value="">No department</option>
                    {departments.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label htmlFor="m-password" className={labelClass}>
                  Temporary password
                </label>
                <input
                  id="m-password"
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 8 characters"
                  className={inputClass}
                  disabled={submitting}
                />
              </div>

              <fieldset disabled={submitting}>
                <legend className={labelClass}>Role</legend>
                <div className="grid gap-3 sm:grid-cols-3">
                  {ROLE_OPTIONS.map((opt) => {
                    const Icon = opt.Icon
                    const active = role === opt.value
                    return (
                      <label
                        key={opt.value}
                        className={`flex cursor-pointer flex-col gap-1 rounded-xl border p-3.5 transition ${
                          active
                            ? 'border-foreground bg-surface-elevated ring-2 ring-foreground/10'
                            : 'border-border-strong bg-surface hover:border-foreground/50'
                        }`}
                      >
                        <span className="flex items-center gap-2">
                          <input
                            type="radio"
                            name="role"
                            value={opt.value}
                            checked={active}
                            onChange={() => setRole(opt.value)}
                            className="sr-only"
                          />
                          <Icon className="size-3.5 text-foreground" aria-hidden />
                          <span className="text-xs font-medium text-foreground">{opt.label}</span>
                          {active ? (
                            <CheckCircle2 className="ml-auto size-3.5 text-foreground" aria-hidden />
                          ) : null}
                        </span>
                        <span className="text-[11px] leading-relaxed text-muted-foreground">{opt.desc}</span>
                      </label>
                    )
                  })}
                </div>
              </fieldset>

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
                <button
                  type="submit"
                  disabled={submitting}
                  className={primaryBtn}
                >
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
                <div className="hidden overflow-hidden rounded-2xl border border-border bg-surface md:block">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border text-left uppercase tracking-[0.08em] text-muted-foreground">
                        <th scope="col" className="px-5 py-3 font-semibold">Name</th>
                        <th scope="col" className="px-5 py-3 font-semibold">Email</th>
                        <th scope="col" className="px-5 py-3 font-semibold">Department</th>
                        <th scope="col" className="px-5 py-3 font-semibold">Role</th>
                        <th scope="col" className="px-5 py-3 font-semibold">Status</th>
                        <th scope="col" className="px-5 py-3 text-right font-semibold">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => {
                        const isSelf = u.id === currentUserId
                        return (
                          <tr key={u.id} className="border-b border-border last:border-0 hover:bg-surface-2">
                            <td className="px-5 py-3.5">
                              <span className="flex items-center gap-1.5 font-medium text-foreground">
                                {u.full_name || u.email}
                                {isSelf ? (
                                  <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                                    You
                                  </span>
                                ) : null}
                              </span>
                              {u.title ? (
                                <span className="block text-[11px] text-muted-foreground">{u.title}</span>
                              ) : null}
                            </td>
                            <td className="px-5 py-3.5 text-muted-foreground">{u.email}</td>
                            <td className="px-5 py-3.5 text-muted-foreground">
                              {u.department_name ? (
                                <span className="inline-flex items-center gap-1 rounded bg-surface-2 px-2 py-0.5 text-[11px] text-muted-foreground">
                                  <Building2 className="size-2.5" />
                                  {u.department_name}
                                </span>
                              ) : (
                                '—'
                              )}
                            </td>
                            <td className="px-5 py-3.5">
                              <RoleBadge role={u.role} />
                            </td>
                            <td className="px-5 py-3.5">
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
                            <td className="px-5 py-3.5 text-right">
                              {isSelf ? (
                                <span className="text-xs text-muted-foreground">—</span>
                              ) : (
                                <div className="inline-flex items-center gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() => setEditingUser(u)}
                                    className={ghostBtn}
                                    title="Edit member"
                                  >
                                    <Pencil className="size-3" /> Edit
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setConfirmUser(u)}
                                    disabled={removingId === u.id}
                                    className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1.5 text-xs text-danger transition hover:bg-danger-soft disabled:opacity-50"
                                    title="Remove member"
                                  >
                                    {removingId === u.id ? (
                                      <Loader2 className="size-3 animate-spin" />
                                    ) : (
                                      <Trash2 className="size-3" />
                                    )}
                                  </button>
                                </div>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Mobile list */}
                <ul className="space-y-3 md:hidden">
                  {users.map((u) => {
                    const isSelf = u.id === currentUserId
                    return (
                      <li key={u.id} className="rounded-2xl border border-border bg-surface p-4 text-xs">
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <p className="font-semibold text-foreground">
                              {u.full_name || u.email}
                              {isSelf && (
                                <span className="ml-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-[10px] text-muted-foreground">
                                  You
                                </span>
                              )}
                            </p>
                            {u.title && <p className="text-[11px] text-muted-foreground">{u.title}</p>}
                            <p className="mt-1 text-muted-foreground">{u.email}</p>
                            {u.department_name && (
                              <p className="mt-1 text-[11px] text-muted-foreground">
                                Department: {u.department_name}
                              </p>
                            )}
                          </div>
                          <RoleBadge role={u.role} />
                        </div>

                        {!isSelf && (
                          <div className="mt-3 flex items-center justify-end gap-2 border-t border-border pt-2">
                            <button
                              type="button"
                              onClick={() => setEditingUser(u)}
                              className={ghostBtn}
                            >
                              <Pencil className="size-3" /> Edit
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmUser(u)}
                              disabled={removingId === u.id}
                              className="rounded-full border border-border px-3 py-1 text-xs text-danger hover:bg-danger-soft"
                            >
                              Remove
                            </button>
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </section>
        </>
      )}

      {/* Edit Member Modal */}
      {editingUser && (
        <EditMemberModal
          user={editingUser}
          departments={departments}
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
    </div>
  )
}

function EditMemberModal({
  user,
  departments,
  onClose,
  onSaved,
}: {
  user: User
  departments: Department[]
  onClose: () => void
  onSaved: (updated: User) => void
}) {
  useEscapeKey(onClose)
  const [fullName, setFullName] = useState(user.full_name || '')
  const [title, setTitle] = useState(user.title || '')
  const [departmentId, setDepartmentId] = useState<number | ''>(user.department_id ?? '')
  const [role, setRole] = useState<CreatableRole>(
    user.role === 'admin' ? 'admin' : user.role === 'employee' ? 'employee' : 'viewer',
  )
  const [isActive, setIsActive] = useState<boolean>(user.is_active !== false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const updated = await adminApi.updateUser(user.id, {
        full_name: fullName.trim(),
        title: title || '',
        department_id: departmentId ? Number(departmentId) : null,
        role,
        is_active: isActive,
      })
      toast.success('Member updated.')
      onSaved(updated)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update member.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-3xl border border-border bg-surface p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border pb-3">
          <h2 className="text-sm font-semibold text-foreground">
            Edit member: {user.full_name || user.email}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-muted-foreground hover:bg-surface-2"
          >
            <X className="size-4" />
          </button>
        </div>

        <form onSubmit={submit} className="mt-4 space-y-3.5">
          <div>
            <label className={labelClass}>Full name</label>
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className={inputClass}
            />
          </div>

          <div>
            <label className={labelClass}>Job title</label>
            <select
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

          <div>
            <label className={labelClass}>Department</label>
            <select
              value={departmentId}
              onChange={(e) => setDepartmentId(e.target.value ? Number(e.target.value) : '')}
              className={inputClass}
            >
              <option value="">No department</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className={labelClass}>Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as CreatableRole)}
              className={inputClass}
            >
              <option value="viewer">Viewer (Read-only)</option>
              <option value="employee">Employee (Upload & manage)</option>
              <option value="admin">Admin (Full access)</option>
            </select>
          </div>

          <label className="flex items-center gap-2 pt-1 text-xs text-foreground">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="size-4 rounded"
            />
            <span>Account is active (uncheck to deactivate access)</span>
          </label>

          {error && <p className="text-xs text-danger">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className={ghostBtn}>
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className={primaryBtn}
            >
              {submitting ? <Loader2 className="size-3.5 animate-spin" /> : 'Save changes'}
            </button>
          </div>
        </form>
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
