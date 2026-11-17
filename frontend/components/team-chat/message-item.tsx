'use client'

import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'
import {
  Check,
  FileText,
  Pencil,
  Pin,
  PinOff,
  Reply,
  ShieldAlert,
  Smile,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import type { TeamMessage, User } from '@/lib/api'
import {
  canDeleteTeamMessage,
  canEditTeamMessage,
  canParticipateInChat,
  canPinTeamMessage,
  editSecondsRemaining,
  formatEditCountdown,
} from '@/lib/team-chat-helpers'

const QUICK_EMOJIS = ['👍', '✅', '❤️', '👀', '😂', '🎉', '🙏', '🔥']

function initials(name?: string | null): string {
  const parts = (name || '?').trim().split(/\s+/)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return (parts[0]?.slice(0, 2) || '?').toUpperCase()
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function renderHumanText(text: string) {
  const parts = text.split(/(@deskwise\b)/gi)
  return parts.map((part, idx) =>
    /^@deskwise$/i.test(part) ? (
      <span
        key={idx}
        className="rounded-md bg-accent-soft px-1.5 py-0.5 font-semibold text-accent"
      >
        {part}
      </span>
    ) : (
      <span key={idx}>{part}</span>
    ),
  )
}

interface MessageItemProps {
  msg: TeamMessage
  currentUser: User
  nowMs: number
  isOnline: boolean
  highlighted?: boolean
  onReply: (msg: TeamMessage) => void
  onJumpTo: (messageId: number) => void
  onEditSave: (msgId: number, content: string) => Promise<void>
  onDeleteRequest: (msg: TeamMessage) => void
  onTogglePin: (msg: TeamMessage) => void
  onToggleReaction: (msgId: number, emoji: string) => void
  onOpenDocument: (docId: number, filename: string) => void
}

export function MessageItem({
  msg,
  currentUser,
  nowMs,
  isOnline,
  highlighted = false,
  onReply,
  onJumpTo,
  onEditSave,
  onDeleteRequest,
  onTogglePin,
  onToggleReaction,
  onOpenDocument,
}: MessageItemProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(msg.content)
  const [savingEdit, setSavingEdit] = useState(false)
  const [showPicker, setShowPicker] = useState(false)

  useEffect(() => {
    if (!editing) setDraft(msg.content)
  }, [msg.content, editing])

  const isBot = msg.sender_type === 'deskwise'
  const isOwn = msg.sender_type === 'user' && msg.sender_id === currentUser.id
  const canParticipate = canParticipateInChat(currentUser)
  const canEdit = canEditTeamMessage(currentUser, msg, nowMs)
  const canDelete = canDeleteTeamMessage(currentUser, msg)
  const canPin = canPinTeamMessage(currentUser)
  const remainingSec = editSecondsRemaining(msg, nowMs)

  const displayName = isBot
    ? 'DeskWise AI'
    : msg.sender?.full_name || msg.sender?.email || 'Former member'

  async function saveEdit() {
    const clean = draft.trim()
    if (!clean || clean === msg.content) {
      setEditing(false)
      return
    }
    setSavingEdit(true)
    try {
      await onEditSave(msg.id, clean)
      setEditing(false)
    } finally {
      setSavingEdit(false)
    }
  }

  return (
    <div
      id={`team-msg-${msg.id}`}
      data-testid={`team-msg-${msg.id}`}
      className={`group relative rounded-2xl border px-4 py-3 transition-colors ${
        highlighted
          ? 'border-accent bg-accent-soft/40'
          : isBot
          ? 'border-accent/25 bg-accent-soft/20'
          : msg.is_pinned
          ? 'border-warn/35 bg-warn-soft/20'
          : 'border-transparent hover:border-border hover:bg-surface/70'
      }`}
    >
      {/* Floating RBAC action bar */}
      <div className="absolute -top-3 right-3 z-10 flex items-center gap-0.5 rounded-xl border border-border bg-surface-elevated p-0.5 shadow-sm opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100 transition-opacity">
        {canParticipate && (
          <button
            type="button"
            onClick={() => onReply(msg)}
            title="Reply"
            aria-label="Reply"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
          >
            <Reply className="size-3.5" />
          </button>
        )}

        {canParticipate && (
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowPicker((v) => !v)}
              title="Add reaction"
              aria-label="Add reaction"
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
            >
              <Smile className="size-3.5" />
            </button>
            {showPicker && (
              <div className="absolute right-0 top-8 z-20 flex items-center gap-1 rounded-xl border border-border bg-surface-elevated p-1.5 shadow-lg">
                {QUICK_EMOJIS.map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    onClick={() => {
                      onToggleReaction(msg.id, emoji)
                      setShowPicker(false)
                    }}
                    className="rounded-lg px-1.5 py-1 text-sm hover:bg-surface-2"
                  >
                    {emoji}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {canPin && (
          <button
            type="button"
            onClick={() => onTogglePin(msg)}
            title={msg.is_pinned ? 'Unpin message' : 'Pin message'}
            aria-label={msg.is_pinned ? 'Unpin message' : 'Pin message'}
            className={`rounded-lg p-1.5 hover:bg-surface-2 ${
              msg.is_pinned ? 'text-accent' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {msg.is_pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
          </button>
        )}

        {canEdit && !editing && (
          <button
            type="button"
            onClick={() => {
              setDraft(msg.content)
              setEditing(true)
            }}
            title={`Edit message (${formatEditCountdown(remainingSec)})`}
            aria-label="Edit message"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
          >
            <Pencil className="size-3.5" />
          </button>
        )}

        {canDelete && (
          <button
            type="button"
            onClick={() => onDeleteRequest(msg)}
            title="Delete message"
            aria-label="Delete message"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-danger-soft hover:text-danger"
          >
            <Trash2 className="size-3.5" />
          </button>
        )}
      </div>

      {/* Author row */}
      <div className="flex items-start gap-3">
        <div className="relative mt-0.5 shrink-0">
          {isBot ? (
            <div className="grid size-9 place-items-center rounded-xl bg-accent text-accent-foreground shadow-xs">
              <Sparkles className="size-4" />
            </div>
          ) : (
            <div
              className={`grid size-9 place-items-center rounded-xl text-xs font-semibold ${
                isOwn
                  ? 'bg-primary text-primary-foreground'
                  : 'border border-border bg-surface-2 text-foreground'
              }`}
            >
              {initials(displayName)}
            </div>
          )}
          {!isBot && isOnline && (
            <span
              title="Online"
              className="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-background bg-ok"
            />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-foreground">{displayName}</span>

            {isBot && (
              <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-foreground">
                AI
              </span>
            )}
            {!isBot && msg.sender?.role === 'admin' && (
              <span className="rounded-full border border-border bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-foreground">
                Admin
              </span>
            )}
            {!isBot && msg.sender?.department_name && (
              <span className="text-[11px] text-muted-foreground">
                {msg.sender.department_name}
              </span>
            )}

            <span className="text-[11px] text-muted-foreground">{formatTime(msg.created_at)}</span>

            {msg.is_edited && (
              <span
                title={msg.edited_at ? `Edited at ${new Date(msg.edited_at).toLocaleString()}` : 'Edited'}
                className="text-[11px] italic text-muted-foreground"
              >
                (edited)
              </span>
            )}

            {msg.is_pinned && (
              <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[10px] font-medium text-warn">
                <Pin className="size-2.5" />
                Pinned{msg.pinned_by_name ? ` by ${msg.pinned_by_name}` : ''}
              </span>
            )}
          </div>

          {/* Reply preview */}
          {msg.reply_to && (
            <button
              type="button"
              onClick={() => onJumpTo(msg.reply_to!.id)}
              className="mt-1.5 flex w-full max-w-xl items-center gap-2 rounded-lg border-l-2 border-accent bg-surface px-2.5 py-1 text-left text-xs text-muted-foreground hover:bg-surface-2"
            >
              <Reply className="size-3 shrink-0 text-accent" />
              <span className="font-semibold text-foreground shrink-0">{msg.reply_to.sender_name}:</span>
              <span className="truncate">{msg.reply_to.content}</span>
            </button>
          )}

          {/* Moderation flag */}
          {msg.flag && (
            <div className="mt-2 flex items-center gap-2 rounded-xl border border-warn/40 bg-warn-soft px-3 py-1.5 text-xs text-warn">
              <ShieldAlert className="size-3.5 shrink-0" />
              <span>{msg.flag.message}</span>
            </div>
          )}

          {/* Message body or inline edit box */}
          {editing ? (
            <div className="mt-2 space-y-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    saveEdit()
                  } else if (e.key === 'Escape') {
                    setEditing(false)
                  }
                }}
                rows={3}
                autoFocus
                className="w-full rounded-xl border border-accent bg-background px-3 py-2 text-sm text-foreground outline-none"
              />
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-muted-foreground">
                  {remainingSec > 0 ? formatEditCountdown(remainingSec) : 'Edit window expired'}
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setEditing(false)}
                    disabled={savingEdit}
                    className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs font-medium hover:bg-surface-2"
                  >
                    <X className="size-3" /> Cancel
                  </button>
                  <button
                    type="button"
                    onClick={saveEdit}
                    disabled={savingEdit || !draft.trim() || remainingSec <= 0}
                    className="inline-flex items-center gap-1 rounded-lg bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground disabled:opacity-50"
                  >
                    <Check className="size-3" /> Save
                  </button>
                </div>
              </div>
            </div>
          ) : isBot ? (
            <div className="ov-md mt-1.5 text-sm leading-relaxed text-foreground">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
                {msg.content}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground">
              {renderHumanText(msg.content)}
            </p>
          )}

          {/* Linked workspace document */}
          {msg.referenced_document && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() =>
                  onOpenDocument(msg.referenced_document!.id, msg.referenced_document!.filename)
                }
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-1.5 text-xs font-medium text-foreground hover:border-border-strong hover:bg-surface-2"
              >
                <FileText className="size-3.5 text-accent" />
                <span>{msg.referenced_document.filename}</span>
                <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {msg.referenced_document.category}
                </span>
              </button>
            </div>
          )}

          {/* @DeskWise citations */}
          {msg.sources?.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] font-medium text-muted-foreground">Sources:</span>
              {msg.sources.map((src, i) => (
                <button
                  key={`${src.filename}-${i}`}
                  type="button"
                  disabled={!src.document_id}
                  onClick={() => src.document_id && onOpenDocument(src.document_id, src.filename)}
                  className={`inline-flex items-center gap-1 rounded-lg border border-border bg-surface px-2 py-0.5 text-[11px] ${
                    src.document_id
                      ? 'text-foreground hover:border-accent hover:text-accent cursor-pointer'
                      : 'text-muted-foreground cursor-default'
                  }`}
                >
                  <FileText className="size-3" />
                  {src.filename}
                </button>
              ))}
            </div>
          )}

          {/* Emoji reactions */}
          {msg.reactions?.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {msg.reactions.map((rx) => {
                const mine = rx.user_ids.includes(currentUser.id)
                return (
                  <button
                    key={rx.emoji}
                    type="button"
                    disabled={!canParticipate}
                    onClick={() => canParticipate && onToggleReaction(msg.id, rx.emoji)}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors ${
                      mine
                        ? 'border-accent bg-accent-soft text-accent font-semibold'
                        : 'border-border bg-surface text-foreground hover:bg-surface-2'
                    } disabled:opacity-70`}
                  >
                    <span>{rx.emoji}</span>
                    <span className="text-[11px]">{rx.count}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
