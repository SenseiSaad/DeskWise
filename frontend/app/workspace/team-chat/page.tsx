'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'
import {
  ArrowUp,
  ChevronDown,
  Download,
  FileText,
  Hash,
  Loader2,
  Lock,
  MessagesSquare,
  Paperclip,
  Pin,
  Plus,
  Reply,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  Users,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react'
import { useAuth } from '@/lib/auth'
import {
  authApi,
  downloadOwnDocument,
  teamChatApi,
  teamChatWsUrl,
  workApi,
  type EnterpriseDoc,
  type TeamChatMember,
  type TeamMessage,
  type TeamRoom,
  type TeamRoomScope,
} from '@/lib/api'
import {
  applyMentionSelection,
  canParticipateInChat,
  detectMentionQuery,
  filterMentionCandidates,
  isChatAdmin,
  upsertTeamMessage,
} from '@/lib/team-chat-helpers'
import { MessageItem } from '@/components/team-chat/message-item'
import { RoomModal } from '@/components/team-chat/room-modal'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { toast } from '@/components/toaster'

type WsStatus = 'connecting' | 'live' | 'reconnecting' | 'http_sync'

export default function TeamChatPage() {
  const { user } = useAuth()
  const isAdmin = isChatAdmin(user)
  const canParticipate = canParticipateInChat(user)

  // Rooms & directory
  const [rooms, setRooms] = useState<TeamRoom[]>([])
  const [activeRoomId, setActiveRoomId] = useState<number | null>(null)
  const [members, setMembers] = useState<TeamChatMember[]>([])
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([])
  const [onlineUserIds, setOnlineUserIds] = useState<number[]>([])
  const [loadingRooms, setLoadingRooms] = useState(true)

  // Messages for active room
  const [messages, setMessages] = useState<TeamMessage[]>([])
  const [pinned, setPinned] = useState<TeamMessage[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [loadingMsgs, setLoadingMsgs] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [highlightedId, setHighlightedId] = useState<number | null>(null)

  // Search & drawers
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [pinnedOpen, setPinnedOpen] = useState(false)
  const [membersOpen, setMembersOpen] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const [summaryPanel, setSummaryPanel] = useState<Awaited<ReturnType<typeof teamChatApi.summarizeRoom>> | null>(null)

  // Live WebSocket & @DeskWise stream state
  const [wsStatus, setWsStatus] = useState<WsStatus>('connecting')
  const [deskwiseStream, setDeskwiseStream] = useState<{
    streamId: string
    replyToId: number
    text: string
  } | null>(null)
  const [typingUsers, setTypingUsers] = useState<Record<number, { name: string; until: number }>>({})
  const [nowMs, setNowMs] = useState(() => Date.now())

  // Composer state
  const [composer, setComposer] = useState('')
  const [replyTo, setReplyTo] = useState<TeamMessage | null>(null)
  const [attachedDoc, setAttachedDoc] = useState<EnterpriseDoc | null>(null)
  const [docPickerOpen, setDocPickerOpen] = useState(false)
  const [availableDocs, setAvailableDocs] = useState<EnterpriseDoc[]>([])
  const [sending, setSending] = useState(false)

  // @mention autocomplete
  const [mentionState, setMentionState] = useState<{ query: string; startIndex: number; caret: number } | null>(null)
  const [mentionIdx, setMentionIdx] = useState(0)

  // Modals (Room create/edit, delete message/room, doc preview)
  const [roomModal, setRoomModal] = useState<{ open: boolean; mode: 'create' | 'edit' }>({
    open: false,
    mode: 'create',
  })
  const [savingRoom, setSavingRoom] = useState(false)
  const [deleteTargetMsg, setDeleteTargetMsg] = useState<TeamMessage | null>(null)
  const [deletingMsg, setDeletingMsg] = useState(false)
  const [deleteTargetRoom, setDeleteTargetRoom] = useState<TeamRoom | null>(null)
  const [deletingRoom, setDeletingRoom] = useState(false)
  const [previewDoc, setPreviewDoc] = useState<{
    id: number
    filename: string
    text: string
    loading: boolean
  } | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const activeRoomRef = useRef<number | null>(null)
  const feedEndRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const typingLastSentRef = useRef<number>(0)

  activeRoomRef.current = activeRoomId

  const activeRoom = useMemo(
    () => rooms.find((r) => r.id === activeRoomId) ?? rooms[0] ?? null,
    [rooms, activeRoomId],
  )

  const mentionCandidates = useMemo(
    () => (mentionState ? filterMentionCandidates(members, mentionState.query, user?.id) : []),
    [mentionState, members, user?.id],
  )

  // 1-second timer to keep edit-window expiry UI accurate and prune stale typing flags
  useEffect(() => {
    const id = setInterval(() => {
      const now = Date.now()
      setNowMs(now)
      setTypingUsers((prev) => {
        const entries = Object.entries(prev).filter(([, v]) => v.until > now)
        if (entries.length === Object.keys(prev).length) return prev
        return Object.fromEntries(entries)
      })
    }, 1000)
    return () => clearInterval(id)
  }, [])

  const scrollToBottom = useCallback((smooth = false) => {
    feedEndRef.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'end' })
  }, [])

  // Initial rooms load (opens default General room immediately)
  const loadRooms = useCallback(async () => {
    setLoadingRooms(true)
    try {
      const res = await teamChatApi.rooms()
      setRooms(res.rooms)
      setMembers(res.members)
      setDepartments(res.departments)
      setOnlineUserIds(res.online_user_ids || [])
      setActiveRoomId((prev) => {
        if (prev && res.rooms.some((r) => r.id === prev)) return prev
        const def = res.rooms.find((r) => r.is_default) || res.rooms[0]
        return def ? def.id : null
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load team chat')
    } finally {
      setLoadingRooms(false)
    }
  }, [])

  useEffect(() => {
    if (user?.company_id) loadRooms()
  }, [user?.company_id, loadRooms])

  // Load room messages whenever active room or search query changes
  const loadMessages = useCallback(
    async (roomId: number, query = '') => {
      setLoadingMsgs(true)
      try {
        const res = await teamChatApi.messages(roomId, {
          q: query || undefined,
          limit: 50,
          markRead: !query,
        })
        if (activeRoomRef.current !== roomId) return
        setMessages(res.results)
        setPinned(res.pinned)
        setHasMore(res.has_more)
        setRooms((prev) =>
          prev.map((r) => (r.id === roomId ? { ...res.room, unread_count: 0 } : r)),
        )
        setTimeout(() => scrollToBottom(false), 30)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Could not load messages')
      } finally {
        setLoadingMsgs(false)
      }
    },
    [scrollToBottom],
  )

  useEffect(() => {
    if (!activeRoomId) return
    setDeskwiseStream(null)
    setPinnedOpen(false)
    loadMessages(activeRoomId, searchQuery.trim())
  }, [activeRoomId, searchQuery, loadMessages])

  // Real-time WebSocket connection (cookie-authenticated, auto-reconnect + refresh on 4401)
  useEffect(() => {
    if (!user?.company_id) return
    let stopped = false
    let openedOnce = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let pingTimer: ReturnType<typeof setInterval> | null = null
    let attempt = 0

    async function connect() {
      if (stopped) return
      setWsStatus(attempt === 0 ? 'connecting' : 'reconnecting')
      const ws = new WebSocket(teamChatWsUrl())
      wsRef.current = ws

      ws.onopen = () => {
        openedOnce = true
        attempt = 0
        setWsStatus('live')
        if (activeRoomRef.current) {
          ws.send(JSON.stringify({ action: 'room.subscribe', room_id: activeRoomRef.current }))
        }
        pingTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'ping' }))
          }
        }, 25000)
      }

      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data)
          const type = data.type as string

          if (type === 'hello') {
            if (Array.isArray(data.online_user_ids)) {
              setOnlineUserIds(data.online_user_ids)
            }
            return
          }
          if (type === 'presence.update') {
            setOnlineUserIds(data.online_user_ids || [])
            return
          }
          if (type === 'room.created' && data.room) {
            setRooms((prev) =>
              prev.some((r) => r.id === data.room.id) ? prev : [...prev, data.room],
            )
            return
          }
          if (type === 'room.updated' && data.room) {
            setRooms((prev) =>
              prev.map((r) => (r.id === data.room.id ? { ...r, ...data.room } : r)),
            )
            return
          }
          if (type === 'room.deleted' && data.room_id) {
            setRooms((prev) => {
              const filtered = prev.filter((r) => r.id !== data.room_id)
              if (activeRoomRef.current === data.room_id) {
                const fallback = filtered.find((r) => r.is_default) || filtered[0]
                setActiveRoomId(fallback ? fallback.id : null)
              }
              return filtered
            })
            return
          }
          if (type === 'typing' && data.room_id === activeRoomRef.current) {
            if (data.user_id && data.user_id !== user?.id) {
              setTypingUsers((prev) => {
                if (!data.is_typing) {
                  const next = { ...prev }
                  delete next[data.user_id]
                  return next
                }
                return {
                  ...prev,
                  [data.user_id]: { name: data.user_name || 'Teammate', until: Date.now() + 3500 },
                }
              })
            }
            return
          }
          if (type === 'deskwise.status' && data.room_id === activeRoomRef.current) {
            setDeskwiseStream({
              streamId: data.stream_id,
              replyToId: data.reply_to_id,
              text: '',
            })
            setTimeout(() => scrollToBottom(true), 20)
            return
          }
          if (type === 'deskwise.delta' && data.room_id === activeRoomRef.current) {
            setDeskwiseStream((prev) => {
              if (!prev || prev.streamId !== data.stream_id) {
                return {
                  streamId: data.stream_id,
                  replyToId: data.reply_to_id,
                  text: data.token || '',
                }
              }
              return { ...prev, text: prev.text + (data.token || '') }
            })
            setTimeout(() => scrollToBottom(false), 10)
            return
          }
          if (type === 'message.created' && data.message) {
            const m: TeamMessage = data.message
            if (m.sender_id) {
              setTypingUsers((prev) => {
                if (!prev[m.sender_id!]) return prev
                const next = { ...prev }
                delete next[m.sender_id!]
                return next
              })
            }
            if (m.room_id === activeRoomRef.current) {
              setMessages((prev) => upsertTeamMessage(prev, m))
              if (m.replaces_stream_id) {
                setDeskwiseStream((cur) => (cur?.streamId === m.replaces_stream_id ? null : cur))
              }
              if (m.sender_id && m.sender_id !== user?.id) {
                ws.send(JSON.stringify({ action: 'room.read', room_id: m.room_id, last_message_id: m.id }))
              }
              setTimeout(() => scrollToBottom(true), 25)
            } else if (m.sender_id !== user?.id) {
              setRooms((prev) =>
                prev.map((r) =>
                  r.id === m.room_id ? { ...r, unread_count: (r.unread_count || 0) + 1 } : r,
                ),
              )
            }
            return
          }
          if (type === 'message.updated' && data.message) {
            const m: TeamMessage = data.message
            if (m.room_id === activeRoomRef.current) {
              setMessages((prev) => prev.map((x) => (x.id === m.id ? m : x)))
              setPinned((prev) => prev.map((x) => (x.id === m.id ? m : x)))
            }
            return
          }
          if (type === 'message.pinned' && data.message) {
            const m: TeamMessage = data.message
            if (m.room_id === activeRoomRef.current) {
              setMessages((prev) => prev.map((x) => (x.id === m.id ? m : x)))
              setPinned((prev) => {
                const without = prev.filter((x) => x.id !== m.id)
                return m.is_pinned ? [m, ...without] : without
              })
            }
            return
          }
          if (type === 'reaction.updated' && data.message) {
            const m: TeamMessage = data.message
            if (m.room_id === activeRoomRef.current) {
              setMessages((prev) => prev.map((x) => (x.id === m.id ? m : x)))
            }
            return
          }
          if (type === 'message.deleted' && data.message_id) {
            if (data.room_id === activeRoomRef.current) {
              setMessages((prev) =>
                prev
                  .filter((x) => x.id !== data.message_id)
                  .map((x) => (x.reply_to_id === data.message_id ? { ...x, reply_to_id: null, reply_to: null } : x)),
              )
              setPinned((prev) => prev.filter((x) => x.id !== data.message_id))
            }
            return
          }
          if (type === 'error' && data.message) {
            toast.error(data.message)
          }
        } catch {
          /* ignore malformed frames */
        }
      }

      ws.onclose = async (evt) => {
        if (pingTimer) clearInterval(pingTimer)
        if (wsRef.current === ws) wsRef.current = null
        if (stopped) return
        if (evt.code === 4401) {
          // Renew HttpOnly access cookie silently before reconnecting
          await authApi.me().catch(() => null)
        }
        attempt += 1
        // Serverless backends (e.g. Vercel) do not support persistent WebSockets;
        // fall back cleanly to HTTP polling after two initial handshake failures.
        if (!openedOnce && attempt >= 2) {
          setWsStatus('http_sync')
          return
        }
        setWsStatus('reconnecting')
        const delay = Math.min(8000, 800 * Math.pow(1.6, Math.min(attempt, 5)))
        reconnectTimer = setTimeout(connect, delay)
      }
    }

    connect()
    return () => {
      stopped = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (pingTimer) clearInterval(pingTimer)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [user?.company_id, user?.id, scrollToBottom])

  // HTTP sync polling fallback when running against a serverless backend without WebSockets
  useEffect(() => {
    if (wsStatus !== 'http_sync' || !activeRoomId || searchQuery.trim()) return
    const timer = setInterval(async () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return
      try {
        const res = await teamChatApi.messages(activeRoomId, { limit: 50, markRead: false })
        setMessages((prev) => {
          let next = prev
          for (const m of res.results) next = upsertTeamMessage(next, m)
          return next
        })
        setPinned(res.pinned)
      } catch {
        /* ignore transient poll error */
      }
    }, 4000)
    return () => clearInterval(timer)
  }, [wsStatus, activeRoomId, searchQuery])

  // Load workspace documents on demand for attaching inside chat
  useEffect(() => {
    if (!docPickerOpen || availableDocs.length > 0) return
    workApi
      .documents(1, 30)
      .then((res) => setAvailableDocs(res.results || []))
      .catch(() => setAvailableDocs([]))
  }, [docPickerOpen, availableDocs.length])

  async function loadOlderMessages() {
    if (!activeRoom || loadingOlder || !messages.length) return
    setLoadingOlder(true)
    try {
      const res = await teamChatApi.messages(activeRoom.id, {
        beforeId: messages[0].id,
        q: searchQuery.trim() || undefined,
        limit: 50,
        markRead: false,
      })
      setMessages((prev) => {
        const existingIds = new Set(prev.map((m) => m.id))
        const older = res.results.filter((m) => !existingIds.has(m.id))
        return [...older, ...prev]
      })
      setHasMore(res.has_more)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load older messages')
    } finally {
      setLoadingOlder(false)
    }
  }

  function sendTypingSignal() {
    if (!activeRoom || !canParticipate) return
    const now = Date.now()
    if (now - typingLastSentRef.current < 1800) return
    typingLastSentRef.current = now
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'typing', room_id: activeRoom.id, is_typing: true }))
    }
  }

  async function handleSend() {
    if (!activeRoom || !canParticipate || sending) return
    const clean = composer.trim()
    if (!clean) return

    setSending(true)
    const replyId = replyTo?.id ?? null
    const docId = attachedDoc?.id ?? null
    setComposer('')
    setReplyTo(null)
    setAttachedDoc(null)
    setMentionState(null)

    try {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            action: 'message.send',
            room_id: activeRoom.id,
            content: clean,
            reply_to_id: replyId,
            referenced_document_id: docId,
          }),
        )
      } else {
        const res = await teamChatApi.sendMessage(activeRoom.id, {
          content: clean,
          reply_to_id: replyId,
          referenced_document_id: docId,
        })
        setMessages((prev) => {
          let next = upsertTeamMessage(prev, res.message)
          if (res.deskwise_message) next = upsertTeamMessage(next, res.deskwise_message)
          return next
        })
        setTimeout(() => scrollToBottom(true), 20)
      }
    } catch (err) {
      setComposer(clean)
      toast.error(err instanceof Error ? err.message : 'Failed to send message')
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  async function handleEditSave(msgId: number, content: string) {
    try {
      const res = await teamChatApi.editMessage(msgId, content)
      setMessages((prev) => prev.map((m) => (m.id === msgId ? res.message : m)))
      setPinned((prev) => prev.map((m) => (m.id === msgId ? res.message : m)))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not edit message')
      throw err
    }
  }

  async function confirmDeleteMessage() {
    if (!deleteTargetMsg) return
    setDeletingMsg(true)
    try {
      const targetId = deleteTargetMsg.id
      await teamChatApi.deleteMessage(targetId)
      setMessages((prev) =>
        prev
          .filter((m) => m.id !== targetId)
          .map((m) => (m.reply_to_id === targetId ? { ...m, reply_to_id: null, reply_to: null } : m)),
      )
      setPinned((prev) => prev.filter((m) => m.id !== targetId))
      setDeleteTargetMsg(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not delete message')
    } finally {
      setDeletingMsg(false)
    }
  }

  async function handleTogglePin(msg: TeamMessage) {
    try {
      const res = await teamChatApi.pinMessage(msg.id, !msg.is_pinned)
      setMessages((prev) => prev.map((m) => (m.id === msg.id ? res.message : m)))
      setPinned((prev) => {
        const without = prev.filter((m) => m.id !== msg.id)
        return res.message.is_pinned ? [res.message, ...without] : without
      })
      toast.success(res.message.is_pinned ? 'Message pinned' : 'Message unpinned')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not update pin')
    }
  }

  async function handleToggleReaction(msgId: number, emoji: string) {
    try {
      const res = await teamChatApi.reactMessage(msgId, emoji)
      setMessages((prev) => prev.map((m) => (m.id === msgId ? res.message : m)))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not react')
    }
  }

  function jumpToMessage(msgId: number) {
    const el = document.getElementById(`team-msg-${msgId}`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setHighlightedId(msgId)
    setTimeout(() => setHighlightedId((cur) => (cur === msgId ? null : cur)), 1800)
  }

  async function handleRoomSubmit(payload: {
    name: string
    description: string
    scope: TeamRoomScope
    department_id: number | null
    member_ids: number[]
  }) {
    setSavingRoom(true)
    try {
      if (roomModal.mode === 'create') {
        const created = await teamChatApi.createRoom(payload)
        setRooms((prev) => (prev.some((r) => r.id === created.id) ? prev : [...prev, created]))
        setActiveRoomId(created.id)
        toast.success(`Created room "${created.name}"`)
      } else if (activeRoom) {
        const updated = await teamChatApi.updateRoom(activeRoom.id, payload)
        setRooms((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
        toast.success('Room updated')
      }
      setRoomModal({ open: false, mode: 'create' })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not save room')
    } finally {
      setSavingRoom(false)
    }
  }

  async function confirmDeleteRoom() {
    if (!deleteTargetRoom) return
    setDeletingRoom(true)
    try {
      const rid = deleteTargetRoom.id
      await teamChatApi.deleteRoom(rid)
      setRooms((prev) => {
        const remaining = prev.filter((r) => r.id !== rid)
        const def = remaining.find((r) => r.is_default) || remaining[0]
        setActiveRoomId(def ? def.id : null)
        return remaining
      })
      setDeleteTargetRoom(null)
      toast.success('Room deleted')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not delete room')
    } finally {
      setDeletingRoom(false)
    }
  }

  async function handleOpenDocument(docId: number, filename: string) {
    setPreviewDoc({ id: docId, filename, text: '', loading: true })
    try {
      const res = await workApi.preview(docId)
      setPreviewDoc({ id: docId, filename: res.filename, text: res.text, loading: false })
    } catch (err) {
      setPreviewDoc(null)
      toast.error(err instanceof Error ? err.message : 'Document preview unavailable')
    }
  }

  function insertDeskWiseTag() {
    if (!composer.toLowerCase().includes('@deskwise')) {
      setComposer((prev) => (prev ? `@DeskWise ${prev}` : '@DeskWise '))
    }
    inputRef.current?.focus()
  }

  function handleComposerChange(val: string, caret: number) {
    setComposer(val)
    sendTypingSignal()
    const match = detectMentionQuery(val, caret)
    setMentionState(match ? { ...match, caret } : null)
    setMentionIdx(0)
  }

  function pickMention(handle: string) {
    if (!mentionState) return
    const { nextText, nextCaret } = applyMentionSelection(
      composer,
      mentionState.startIndex,
      mentionState.caret,
      handle,
    )
    setComposer(nextText)
    setMentionState(null)
    requestAnimationFrame(() => {
      inputRef.current?.focus()
      inputRef.current?.setSelectionRange(nextCaret, nextCaret)
    })
  }

  if (!user?.company_id) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-8 text-center text-sm text-muted-foreground">
        Select a company workspace from the sidebar to open Team Chat.
      </div>
    )
  }

  const typingNames = Object.values(typingUsers).map((v) => v.name)
  const hasMultipleRooms = rooms.length > 1

  return (
    <div className="flex h-[calc(100dvh-7.5rem)] lg:h-[calc(100dvh-5rem)] flex-col overflow-hidden rounded-2xl border border-border bg-surface-elevated shadow-xs">
      {/* Header: Single default room first; lightweight pills appear only if extra rooms exist */}
      <header className="border-b border-border bg-surface px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
              <MessagesSquare className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="truncate text-base font-semibold text-foreground">
                  {activeRoom?.name ?? 'Team Chat'}
                </h1>
                {activeRoom && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {activeRoom.scope === 'private' ? (
                      <>
                        <Lock className="size-2.5" /> Private
                      </>
                    ) : activeRoom.scope === 'department' ? (
                      <>
                        <Hash className="size-2.5" /> {activeRoom.department_name || 'Department'}
                      </>
                    ) : (
                      <>
                        <Users className="size-2.5" /> All employees
                      </>
                    )}
                  </span>
                )}
                <span
                  title={wsStatus === 'http_sync' ? 'HTTP auto-sync (4s)' : `WebSocket: ${wsStatus}`}
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    wsStatus === 'live'
                      ? 'bg-ok-soft text-ok'
                      : wsStatus === 'http_sync'
                        ? 'bg-info-soft text-info'
                        : 'bg-warn-soft text-warn'
                  }`}
                >
                  {wsStatus === 'live' || wsStatus === 'http_sync' ? (
                    <Wifi className="size-2.5" />
                  ) : (
                    <WifiOff className="size-2.5" />
                  )}
                  {wsStatus === 'live' ? 'Live' : wsStatus === 'http_sync' ? 'Synced' : 'Reconnecting'}
                </span>
              </div>
              <p className="truncate text-xs text-muted-foreground">
                {activeRoom?.description || 'Company employee chatroom. Mention @DeskWise anytime for work.'}
              </p>
            </div>
          </div>

          {/* Controls */}
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setSearchOpen((v) => !v)}
              title="Search messages"
              className={`inline-flex items-center gap-1 rounded-xl border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                searchOpen || searchQuery
                  ? 'border-accent bg-accent-soft text-accent'
                  : 'border-border bg-background text-foreground hover:bg-surface-2'
              }`}
            >
              <Search className="size-3.5" />
              <span className="hidden sm:inline">Search</span>
            </button>

            <button
              type="button"
              onClick={() => setPinnedOpen((v) => !v)}
              className={`inline-flex items-center gap-1 rounded-xl border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                pinnedOpen
                  ? 'border-accent bg-accent-soft text-accent'
                  : 'border-border bg-background text-foreground hover:bg-surface-2'
              }`}
            >
              <Pin className="size-3.5" />
              <span>Pinned ({pinned.length})</span>
            </button>

            <button
              type="button"
              onClick={() => setMembersOpen((v) => !v)}
              className={`inline-flex items-center gap-1 rounded-xl border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                membersOpen
                  ? 'border-accent bg-accent-soft text-accent'
                  : 'border-border bg-background text-foreground hover:bg-surface-2'
              }`}
            >
              <span className="size-2 rounded-full bg-ok" />
              <span>{onlineUserIds.length || 1} online</span>
            </button>

            {activeRoom && (
              <button
                type="button"
                disabled={summarizing}
                onClick={async () => {
                  setSummarizing(true)
                  try {
                    const res = await teamChatApi.summarizeRoom(activeRoom.id)
                    setSummaryPanel(res)
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : 'Could not summarize room.')
                  } finally {
                    setSummarizing(false)
                  }
                }}
                title="AI Catch-Up Summary"
                className="inline-flex items-center gap-1 rounded-xl border border-border bg-background px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-surface-2 disabled:opacity-50"
              >
                {summarizing ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
                <span>Summarize</span>
              </button>
            )}

            {isAdmin && (
              <>
                <button
                  type="button"
                  onClick={() => setRoomModal({ open: true, mode: 'create' })}
                  className="inline-flex items-center gap-1 rounded-xl bg-primary px-2.5 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90"
                >
                  <Plus className="size-3.5" />
                  <span>New room</span>
                </button>
                {activeRoom && !activeRoom.is_default && (
                  <>
                    <button
                      type="button"
                      onClick={() => setRoomModal({ open: true, mode: 'edit' })}
                      title="Edit room"
                      className="rounded-xl border border-border bg-background p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
                    >
                      <Settings2 className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setDeleteTargetRoom(activeRoom)}
                      title="Delete room"
                      className="rounded-xl border border-border bg-background p-1.5 text-muted-foreground hover:bg-danger-soft hover:text-danger"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </>
                )}
              </>
            )}
          </div>
        </div>

        {/* Optional lightweight room pills when company created extra rooms */}
        {hasMultipleRooms && (
          <div className="mt-2.5 flex items-center gap-1.5 overflow-x-auto pb-0.5">
            {rooms.map((room) => {
              const isSelected = room.id === activeRoom?.id
              return (
                <button
                  key={room.id}
                  type="button"
                  onClick={() => setActiveRoomId(room.id)}
                  className={`inline-flex shrink-0 items-center gap-1.5 rounded-xl border px-3 py-1 text-xs font-medium transition-colors ${
                    isSelected
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border bg-background text-muted-foreground hover:bg-surface-2 hover:text-foreground'
                  }`}
                >
                  {room.scope === 'private' ? <Lock className="size-3" /> : <Hash className="size-3" />}
                  <span>{room.name}</span>
                  {room.unread_count > 0 && !isSelected && (
                    <span className="rounded-full bg-accent px-1.5 py-0.2 text-[10px] font-bold text-accent-foreground">
                      {room.unread_count}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        )}

        {summaryPanel && summaryPanel.room_id === activeRoom?.id && (
          <div className="mt-2.5 rounded-2xl border border-info/30 bg-info-soft p-3.5 text-xs">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-1.5 font-semibold text-foreground">
                <Sparkles className="size-3.5 text-info" />
                <span>Room Catch-Up Summary ({summaryPanel.message_count} messages · {summaryPanel.mode})</span>
              </div>
              <button
                type="button"
                onClick={() => setSummaryPanel(null)}
                className="rounded p-0.5 text-muted-foreground hover:bg-surface hover:text-foreground"
                aria-label="Close summary"
              >
                <X className="size-3.5" />
              </button>
            </div>
            <p className="mt-1.5 whitespace-pre-wrap leading-relaxed text-foreground/90">{summaryPanel.summary}</p>
            {(summaryPanel.action_items.length > 0 || summaryPanel.open_questions.length > 0) && (
              <div className="mt-2.5 grid gap-2 border-t border-info/20 pt-2 sm:grid-cols-2">
                {summaryPanel.action_items.length > 0 && (
                  <div>
                    <p className="font-semibold text-foreground">Action items</p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted-foreground">
                      {summaryPanel.action_items.map((item, i) => (
                        <li key={i}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {summaryPanel.open_questions.length > 0 && (
                  <div>
                    <p className="font-semibold text-foreground">Open questions</p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted-foreground">
                      {summaryPanel.open_questions.map((q, i) => (
                        <li key={i}>{q}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Search bar */}
        {searchOpen && (
          <div className="mt-2.5 flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search messages in this room..."
                className="w-full rounded-xl border border-border bg-background py-1.5 pl-9 pr-8 text-xs text-foreground outline-none focus:border-accent"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>
          </div>
        )}
      </header>

      {/* Pinned banner */}
      {pinned.length > 0 && !pinnedOpen && (
        <button
          type="button"
          onClick={() => setPinnedOpen(true)}
          className="flex items-center justify-between gap-2 border-b border-border bg-warn-soft/35 px-4 py-1.5 text-left text-xs hover:bg-warn-soft/55"
        >
          <div className="flex min-w-0 items-center gap-2">
            <Pin className="size-3.5 shrink-0 text-warn" />
            <span className="font-semibold text-foreground shrink-0">
              {pinned[0].sender_type === 'deskwise'
                ? 'DeskWise AI'
                : pinned[0].sender?.full_name || 'Message'}
              :
            </span>
            <span className="truncate text-muted-foreground">{pinned[0].content}</span>
          </div>
          <span className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-warn">
            {pinned.length} pinned <ChevronDown className="size-3" />
          </span>
        </button>
      )}

      {/* Body + optional side drawers (Pinned / Online Members) */}
      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* Messages feed */}
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4 sm:px-5 space-y-2">
            {loadingRooms || loadingMsgs ? (
              <div className="grid h-full place-items-center text-xs text-muted-foreground">
                <span className="flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin" /> Loading team chat...
                </span>
              </div>
            ) : messages.length === 0 ? (
              <div className="grid h-full place-items-center p-6 text-center">
                <div className="max-w-md space-y-3">
                  <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent">
                    <Sparkles className="size-6" />
                  </div>
                  <h2 className="text-base font-semibold text-foreground">
                    {searchQuery ? 'No matching messages' : `Welcome to ${activeRoom?.name ?? 'Team Chat'}`}
                  </h2>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {searchQuery
                      ? 'Try a different keyword or clear the search filter.'
                      : 'Chat with your team in real time, pin important decisions, or mention @DeskWise to pull answers directly from company documents.'}
                  </p>
                </div>
              </div>
            ) : (
              <>
                {hasMore && (
                  <div className="flex justify-center pb-2">
                    <button
                      type="button"
                      onClick={loadOlderMessages}
                      disabled={loadingOlder}
                      className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                    >
                      {loadingOlder && <Loader2 className="size-3 animate-spin" />}
                      Load older messages
                    </button>
                  </div>
                )}

                {messages.map((msg) => (
                  <MessageItem
                    key={msg.id}
                    msg={msg}
                    currentUser={user}
                    nowMs={nowMs}
                    isOnline={Boolean(msg.sender_id && onlineUserIds.includes(msg.sender_id))}
                    highlighted={highlightedId === msg.id}
                    onReply={(m) => {
                      setReplyTo(m)
                      inputRef.current?.focus()
                    }}
                    onJumpTo={jumpToMessage}
                    onEditSave={handleEditSave}
                    onDeleteRequest={setDeleteTargetMsg}
                    onTogglePin={handleTogglePin}
                    onToggleReaction={handleToggleReaction}
                    onOpenDocument={handleOpenDocument}
                  />
                ))}

                {/* Live @DeskWise AI streaming bubble */}
                {deskwiseStream && (
                  <div className="rounded-2xl border border-accent/30 bg-accent-soft/25 px-4 py-3">
                    <div className="flex items-start gap-3">
                      <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent text-accent-foreground">
                        <Sparkles className="size-4 animate-pulse" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-foreground">DeskWise AI</span>
                          <span className="text-xs text-accent">
                            {deskwiseStream.text ? 'writing…' : 'checking company documents…'}
                          </span>
                        </div>
                        {deskwiseStream.text && (
                          <div className="ov-md mt-1.5 text-sm leading-relaxed text-foreground">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
                              {deskwiseStream.text}
                            </ReactMarkdown>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
            <div ref={feedEndRef} />
          </div>

          {/* Typing status */}
          {typingNames.length > 0 && (
            <div className="px-5 pb-1 text-[11px] italic text-muted-foreground">
              {typingNames.join(', ')} {typingNames.length === 1 ? 'is' : 'are'} typing…
            </div>
          )}

          {/* Composer */}
          <div className="border-t border-border bg-surface p-3 sm:px-5 sm:py-3.5">
            {!canParticipate ? (
              <div className="rounded-xl border border-border bg-background px-4 py-2.5 text-center text-xs text-muted-foreground">
                Read-only viewer role: you can read and search messages, but cannot post, edit, pin, or delete.
              </div>
            ) : (
              <div className="relative space-y-2">
                {/* @mention autocomplete dropdown */}
                {mentionState && mentionCandidates.length > 0 && (
                  <div className="absolute bottom-full left-0 z-30 mb-2 w-full max-w-sm overflow-hidden rounded-2xl border border-border bg-surface-elevated shadow-xl">
                    {mentionCandidates.map((c, idx) => (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => pickMention(c.handle)}
                        className={`flex w-full items-center justify-between gap-2 px-3.5 py-2 text-left text-xs ${
                          idx === mentionIdx ? 'bg-accent-soft text-foreground' : 'hover:bg-surface'
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          {c.isBot ? (
                            <Sparkles className="size-3.5 shrink-0 text-accent" />
                          ) : (
                            <span className="size-2 shrink-0 rounded-full bg-border-strong" />
                          )}
                          <span className="font-semibold truncate">@{c.handle}</span>
                        </div>
                        <span className="truncate text-[11px] text-muted-foreground">{c.subtitle}</span>
                      </button>
                    ))}
                  </div>
                )}

                {/* Document picker dropdown */}
                {docPickerOpen && (
                  <div className="absolute bottom-full right-0 z-30 mb-2 w-full max-w-sm overflow-hidden rounded-2xl border border-border bg-surface-elevated shadow-xl">
                    <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs font-semibold">
                      <span>Attach workspace document</span>
                      <button type="button" onClick={() => setDocPickerOpen(false)}>
                        <X className="size-3.5" />
                      </button>
                    </div>
                    <div className="max-h-48 overflow-y-auto p-1.5 space-y-0.5">
                      {availableDocs.length === 0 ? (
                        <p className="p-2 text-xs text-muted-foreground">No accessible documents found.</p>
                      ) : (
                        availableDocs.map((doc) => (
                          <button
                            key={doc.id}
                            type="button"
                            onClick={() => {
                              setAttachedDoc(doc)
                              setDocPickerOpen(false)
                            }}
                            className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs hover:bg-surface"
                          >
                            <span className="flex items-center gap-1.5 truncate">
                              <FileText className="size-3.5 shrink-0 text-accent" />
                              <span className="truncate font-medium">{doc.filename}</span>
                            </span>
                            <span className="shrink-0 text-[10px] text-muted-foreground">{doc.category}</span>
                          </button>
                        ))
                      )}
                    </div>
                  </div>
                )}

                {/* Reply / attached doc pills */}
                {(replyTo || attachedDoc) && (
                  <div className="flex flex-wrap items-center gap-2">
                    {replyTo && (
                      <div className="flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-1 text-xs">
                        <Reply className="size-3 text-accent" />
                        <span className="font-medium">
                          Replying to{' '}
                          {replyTo.sender_type === 'deskwise'
                            ? 'DeskWise AI'
                            : replyTo.sender?.full_name || 'teammate'}
                        </span>
                        <span className="max-w-48 truncate text-muted-foreground">
                          {replyTo.content}
                        </span>
                        <button
                          type="button"
                          onClick={() => setReplyTo(null)}
                          aria-label="Cancel reply"
                          className="text-muted-foreground hover:text-foreground"
                        >
                          <X className="size-3" />
                        </button>
                      </div>
                    )}
                    {attachedDoc && (
                      <div className="flex items-center gap-1.5 rounded-xl border border-accent/40 bg-accent-soft px-3 py-1 text-xs text-accent">
                        <FileText className="size-3" />
                        <span className="max-w-48 truncate font-medium">{attachedDoc.filename}</span>
                        <button type="button" onClick={() => setAttachedDoc(null)} aria-label="Remove document">
                          <X className="size-3" />
                        </button>
                      </div>
                    )}
                  </div>
                )}

                <div className="flex items-end gap-2 rounded-2xl border border-border bg-background p-2 focus-within:border-border-strong">
                  <button
                    type="button"
                    onClick={insertDeskWiseTag}
                    title="Mention @DeskWise AI"
                    className="inline-flex shrink-0 items-center gap-1 rounded-xl bg-accent-soft px-2.5 py-1.5 text-xs font-semibold text-accent hover:opacity-85"
                  >
                    <Sparkles className="size-3.5" />
                    <span className="hidden sm:inline">@DeskWise</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setDocPickerOpen((v) => !v)}
                    title="Attach workspace document"
                    aria-label="Attach workspace document"
                    className="shrink-0 rounded-xl p-1.5 text-muted-foreground hover:bg-surface hover:text-foreground"
                  >
                    <Paperclip className="size-4" />
                  </button>

                  <textarea
                    ref={inputRef}
                    rows={1}
                    value={composer}
                    onChange={(e) =>
                      handleComposerChange(e.target.value, e.target.selectionStart ?? e.target.value.length)
                    }
                    onKeyDown={(e) => {
                      if (mentionState && mentionCandidates.length > 0) {
                        if (e.key === 'ArrowDown') {
                          e.preventDefault()
                          setMentionIdx((i) => (i + 1) % mentionCandidates.length)
                          return
                        }
                        if (e.key === 'ArrowUp') {
                          e.preventDefault()
                          setMentionIdx((i) => (i - 1 + mentionCandidates.length) % mentionCandidates.length)
                          return
                        }
                        if (e.key === 'Enter' || e.key === 'Tab') {
                          e.preventDefault()
                          pickMention(mentionCandidates[mentionIdx].handle)
                          return
                        }
                        if (e.key === 'Escape') {
                          setMentionState(null)
                          return
                        }
                      }
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        handleSend()
                      }
                    }}
                    placeholder={`Message ${activeRoom?.name ?? 'General'}… (type @DeskWise for AI help)`}
                    className="max-h-36 min-h-8 flex-1 resize-none bg-transparent py-1 text-sm text-foreground outline-none placeholder:text-muted-foreground"
                  />

                  <button
                    type="button"
                    onClick={handleSend}
                    disabled={sending || !composer.trim() || !activeRoom}
                    aria-label="Send message"
                    className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
                  >
                    {sending ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Pinned drawer */}
        {pinnedOpen && (
          <aside className="w-72 shrink-0 border-l border-border bg-surface p-3 overflow-y-auto">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Pinned Messages ({pinned.length})
              </h3>
              <button type="button" onClick={() => setPinnedOpen(false)} className="text-muted-foreground hover:text-foreground">
                <X className="size-4" />
              </button>
            </div>
            {pinned.length === 0 ? (
              <p className="text-xs text-muted-foreground">No pinned messages in this room yet.</p>
            ) : (
              <div className="space-y-2">
                {pinned.map((pm) => (
                  <div key={pm.id} className="rounded-xl border border-border bg-background p-2.5 text-xs space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-foreground truncate">
                        {pm.sender_type === 'deskwise' ? 'DeskWise AI' : pm.sender?.full_name || 'Member'}
                      </span>
                      {canParticipate && (
                        <button
                          type="button"
                          onClick={() => handleTogglePin(pm)}
                          className="text-[11px] text-accent hover:underline"
                        >
                          Unpin
                        </button>
                      )}
                    </div>
                    <p className="line-clamp-3 text-muted-foreground">{pm.content}</p>
                    <button
                      type="button"
                      onClick={() => jumpToMessage(pm.id)}
                      className="text-[11px] font-medium text-primary hover:underline"
                    >
                      Jump to message →
                    </button>
                  </div>
                ))}
              </div>
            )}
          </aside>
        )}

        {/* Members / presence drawer */}
        {membersOpen && (
          <aside className="w-64 shrink-0 border-l border-border bg-surface p-3 overflow-y-auto">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                People ({members.length})
              </h3>
              <button type="button" onClick={() => setMembersOpen(false)} className="text-muted-foreground hover:text-foreground">
                <X className="size-4" />
              </button>
            </div>
            <div className="space-y-1.5">
              {members.map((m) => {
                const isOn = onlineUserIds.includes(m.id)
                return (
                  <div
                    key={m.id}
                    className="flex items-center justify-between gap-2 rounded-xl border border-border/60 bg-background px-2.5 py-2 text-xs"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span className={`size-2 shrink-0 rounded-full ${isOn ? 'bg-ok' : 'bg-border-strong'}`} />
                      <div className="min-w-0">
                        <p className="truncate font-medium text-foreground">{m.full_name}</p>
                        <p className="truncate text-[10px] text-muted-foreground">
                          {m.title || m.department_name || m.role}
                        </p>
                      </div>
                    </div>
                    <span className="shrink-0 text-[10px] capitalize text-muted-foreground">{m.role}</span>
                  </div>
                )
              })}
            </div>
          </aside>
        )}
      </div>

      {/* Create / Edit Room modal */}
      <RoomModal
        open={roomModal.open}
        mode={roomModal.mode}
        initialRoom={roomModal.mode === 'edit' ? activeRoom : null}
        departments={departments}
        members={members}
        currentUserId={user.id}
        saving={savingRoom}
        onClose={() => setRoomModal((s) => ({ ...s, open: false }))}
        onSubmit={handleRoomSubmit}
      />

      {/* Delete message confirmation */}
      <ConfirmDialog
        open={Boolean(deleteTargetMsg)}
        title="Delete message permanently?"
        message="This will permanently remove the message from the chatroom for everyone. This cannot be undone."
        confirmText="Delete message"
        loading={deletingMsg}
        onConfirm={confirmDeleteMessage}
        onCancel={() => !deletingMsg && setDeleteTargetMsg(null)}
      />

      {/* Delete room confirmation */}
      <ConfirmDialog
        open={Boolean(deleteTargetRoom)}
        title={`Delete "${deleteTargetRoom?.name ?? ''}"?`}
        message="All messages in this room will be permanently deleted. The default General room stays intact."
        confirmText="Delete room"
        loading={deletingRoom}
        onConfirm={confirmDeleteRoom}
        onCancel={() => !deletingRoom && setDeleteTargetRoom(null)}
      />

      {/* Document preview modal */}
      {previewDoc && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4 backdrop-blur-xs"
          role="dialog"
          aria-modal="true"
        >
          <div className="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border bg-surface-elevated shadow-2xl">
            <div className="flex items-center justify-between border-b border-border bg-surface px-5 py-3">
              <div className="flex items-center gap-2 min-w-0">
                <FileText className="size-4 shrink-0 text-accent" />
                <span className="truncate text-sm font-semibold text-foreground">{previewDoc.filename}</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => downloadOwnDocument(previewDoc.id, previewDoc.filename)}
                  className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 py-1 text-xs font-medium hover:bg-surface-2"
                >
                  <Download className="size-3.5" /> Download
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewDoc(null)}
                  className="rounded-lg p-1 text-muted-foreground hover:bg-surface-2"
                >
                  <X className="size-4" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              {previewDoc.loading ? (
                <div className="flex items-center justify-center gap-2 py-12 text-xs text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> Loading preview...
                </div>
              ) : (
                <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-foreground">
                  {previewDoc.text || 'Empty document.'}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
