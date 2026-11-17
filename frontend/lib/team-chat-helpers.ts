import type { TeamChatMember, TeamMessage, User } from './api'

export function isChatAdmin(user: Pick<User, 'role' | 'is_platform_admin' | 'is_superuser'> | null | undefined): boolean {
  if (!user) return false
  return user.role === 'admin' || Boolean(user.is_platform_admin) || Boolean(user.is_superuser)
}

export function canParticipateInChat(user: Pick<User, 'role' | 'is_platform_admin' | 'is_superuser'> | null | undefined): boolean {
  if (!user) return false
  return user.role !== 'viewer' || isChatAdmin(user)
}

export function editSecondsRemaining(msg: Pick<TeamMessage, 'sender_type' | 'edit_expires_at'>, nowMs = Date.now()): number {
  if (msg.sender_type !== 'user' || !msg.edit_expires_at) return 0
  const expiresMs = Date.parse(msg.edit_expires_at)
  if (!Number.isFinite(expiresMs)) return 0
  return Math.max(0, Math.floor((expiresMs - nowMs) / 1000))
}

export function canEditTeamMessage(
  user: Pick<User, 'id' | 'role' | 'is_platform_admin' | 'is_superuser'> | null | undefined,
  msg: Pick<TeamMessage, 'sender_type' | 'sender_id' | 'edit_expires_at'>,
  nowMs = Date.now(),
): boolean {
  if (!user || !canParticipateInChat(user)) return false
  if (msg.sender_type !== 'user' || msg.sender_id !== user.id) return false
  return editSecondsRemaining(msg, nowMs) > 0
}

export function canDeleteTeamMessage(
  user: Pick<User, 'id' | 'role' | 'is_platform_admin' | 'is_superuser'> | null | undefined,
  msg: Pick<TeamMessage, 'sender_type' | 'sender_id'>,
): boolean {
  if (!user || !canParticipateInChat(user)) return false
  if (isChatAdmin(user)) return true
  return msg.sender_type === 'user' && msg.sender_id === user.id
}

export function canPinTeamMessage(
  user: Pick<User, 'role' | 'is_platform_admin' | 'is_superuser'> | null | undefined,
): boolean {
  return canParticipateInChat(user)
}

export function formatEditCountdown(seconds: number): string {
  if (seconds <= 0) return 'expired'
  if (seconds < 60) return `${seconds}s left`
  const mins = Math.ceil(seconds / 60)
  return `${mins}m left`
}

export interface MentionCandidate {
  id: string
  handle: string
  label: string
  subtitle: string
  isBot?: boolean
}

export function detectMentionQuery(text: string, caretPos: number): { query: string; startIndex: number } | null {
  const before = text.slice(0, caretPos)
  const match = before.match(/(?:^|\s)@([a-zA-Z0-9._-]*)$/)
  if (!match) return null
  const query = match[1] ?? ''
  const atIndex = before.lastIndexOf('@')
  if (atIndex < 0) return null
  return { query: query.toLowerCase(), startIndex: atIndex }
}

export function filterMentionCandidates(
  members: TeamChatMember[],
  query: string,
  currentUserId?: number,
): MentionCandidate[] {
  const q = query.trim().toLowerCase()
  const candidates: MentionCandidate[] = [
    {
      id: 'deskwise',
      handle: 'DeskWise',
      label: 'DeskWise AI',
      subtitle: 'Ask company documents & generate work drafts',
      isBot: true,
    },
  ]

  for (const m of members) {
    if (currentUserId && m.id === currentUserId) continue
    const displayName = m.full_name || m.email.split('@')[0]
    candidates.push({
      id: `user-${m.id}`,
      handle: displayName,
      label: displayName,
      subtitle: m.title || m.department_name || m.role,
    })
  }

  if (!q) return candidates.slice(0, 7)
  return candidates
    .filter((c) => c.handle.toLowerCase().includes(q) || c.label.toLowerCase().includes(q))
    .slice(0, 7)
}

export function applyMentionSelection(
  text: string,
  startIndex: number,
  caretPos: number,
  handle: string,
): { nextText: string; nextCaret: number } {
  const prefix = text.slice(0, startIndex)
  const suffix = text.slice(caretPos)
  const insertion = `@${handle} `
  const cleanSuffix = suffix.startsWith(' ') ? suffix.slice(1) : suffix
  return {
    nextText: `${prefix}${insertion}${cleanSuffix}`,
    nextCaret: prefix.length + insertion.length,
  }
}

export function upsertTeamMessage(list: TeamMessage[], incoming: TeamMessage): TeamMessage[] {
  const idx = list.findIndex((m) => m.id === incoming.id)
  if (idx >= 0) {
    const next = [...list]
    next[idx] = incoming
    return next
  }
  return [...list, incoming].sort((a, b) => a.id - b.id)
}
