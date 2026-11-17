'use client'

import { useEffect, useState } from 'react'
import { Loader2, Lock, Users, Building2, X } from 'lucide-react'
import type { TeamChatMember, TeamRoom, TeamRoomScope } from '@/lib/api'

interface RoomModalProps {
  open: boolean
  mode: 'create' | 'edit'
  initialRoom?: TeamRoom | null
  departments: { id: number; name: string }[]
  members: TeamChatMember[]
  currentUserId: number
  saving: boolean
  onClose: () => void
  onSubmit: (payload: {
    name: string
    description: string
    scope: TeamRoomScope
    department_id: number | null
    member_ids: number[]
  }) => void
}

export function RoomModal({
  open,
  mode,
  initialRoom,
  departments,
  members,
  currentUserId,
  saving,
  onClose,
  onSubmit,
}: RoomModalProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [scope, setScope] = useState<TeamRoomScope>('company')
  const [departmentId, setDepartmentId] = useState<number | ''>('')
  const [selectedMembers, setSelectedMembers] = useState<number[]>([])

  useEffect(() => {
    if (!open) return
    if (mode === 'edit' && initialRoom) {
      setName(initialRoom.name)
      setDescription(initialRoom.description || '')
      setScope(initialRoom.scope)
      setDepartmentId(initialRoom.department_id ?? '')
      setSelectedMembers(
        initialRoom.member_ids?.length ? initialRoom.member_ids : [currentUserId],
      )
    } else {
      setName('')
      setDescription('')
      setScope('company')
      setDepartmentId(departments[0]?.id ?? '')
      setSelectedMembers([currentUserId])
    }
  }, [open, mode, initialRoom, departments, currentUserId])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const isDefault = Boolean(mode === 'edit' && initialRoom?.is_default)

  function toggleMember(uid: number) {
    if (uid === currentUserId) return
    setSelectedMembers((prev) =>
      prev.includes(uid) ? prev.filter((id) => id !== uid) : [...prev, uid],
    )
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    onSubmit({
      name: name.trim(),
      description: description.trim(),
      scope: isDefault ? 'company' : scope,
      department_id: !isDefault && scope === 'department' && departmentId ? Number(departmentId) : null,
      member_ids: !isDefault && scope === 'private' ? selectedMembers : [],
    })
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
      aria-label={mode === 'create' ? 'Create chatroom' : 'Edit chatroom'}
    >
      <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-surface-elevated shadow-2xl">
        <div className="flex items-center justify-between border-b border-border bg-surface px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-foreground">
              {mode === 'create' ? 'Create separate room' : `Edit ${initialRoom?.name ?? 'room'}`}
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Keep everyone in General by default, or add focused rooms when needed.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close modal"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-foreground">Room name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. HR Support, Q4 Launch, Engineering"
              maxLength={80}
              required
              autoFocus
              className="w-full rounded-xl border border-border bg-background px-3.5 py-2 text-sm text-foreground outline-none focus:border-accent"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-foreground">
              Description <span className="font-normal text-muted-foreground">(optional)</span>
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this room for?"
              maxLength={240}
              className="w-full rounded-xl border border-border bg-background px-3.5 py-2 text-sm text-foreground outline-none focus:border-accent"
            />
          </div>

          {!isDefault && (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-foreground">Who can access</label>
              <div className="grid grid-cols-3 gap-2">
                {(
                  [
                    { id: 'company', label: 'All company', icon: Users },
                    { id: 'department', label: 'Department', icon: Building2 },
                    { id: 'private', label: 'Selected people', icon: Lock },
                  ] as const
                ).map((opt) => {
                  const Icon = opt.icon
                  const active = scope === opt.id
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => setScope(opt.id)}
                      className={`flex items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-medium transition-colors ${
                        active
                          ? 'border-accent bg-accent-soft text-accent'
                          : 'border-border bg-surface text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <Icon className="size-3.5" />
                      {opt.label}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {!isDefault && scope === 'department' && (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-foreground">Department</label>
              {departments.length === 0 ? (
                <p className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-muted-foreground">
                  No departments created yet. Create departments under Members or use All company / Selected people.
                </p>
              ) : (
                <select
                  value={departmentId}
                  onChange={(e) => setDepartmentId(Number(e.target.value))}
                  required
                  className="w-full rounded-xl border border-border bg-background px-3.5 py-2 text-sm text-foreground outline-none focus:border-accent"
                >
                  <option value="">Choose department...</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {!isDefault && scope === 'private' && (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-foreground">
                Members ({selectedMembers.length} selected)
              </label>
              <div className="max-h-44 space-y-1 overflow-y-auto rounded-xl border border-border bg-background p-2">
                {members.map((m) => {
                  const checked = selectedMembers.includes(m.id)
                  const locked = m.id === currentUserId
                  return (
                    <label
                      key={m.id}
                      className={`flex cursor-pointer items-center justify-between rounded-lg px-2.5 py-1.5 text-xs ${
                        checked ? 'bg-accent-soft/60 text-foreground' : 'hover:bg-surface'
                      }`}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={locked}
                          onChange={() => toggleMember(m.id)}
                          className="accent-accent"
                        />
                        <span className="truncate font-medium">{m.full_name || m.email}</span>
                      </div>
                      <span className="ml-2 shrink-0 text-[10px] capitalize text-muted-foreground">
                        {m.role}
                        {locked ? ' (you)' : ''}
                      </span>
                    </label>
                  )
                })}
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="rounded-xl border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface-2 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !name.trim() || (!isDefault && scope === 'department' && !departmentId)}
              className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              {saving && <Loader2 className="size-3.5 animate-spin" />}
              {mode === 'create' ? 'Create room' : 'Save changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
