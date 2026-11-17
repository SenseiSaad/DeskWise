import { describe, expect, it } from 'vitest'
import {
  applyMentionSelection,
  canDeleteTeamMessage,
  canEditTeamMessage,
  canPinTeamMessage,
  detectMentionQuery,
  editSecondsRemaining,
  filterMentionCandidates,
  upsertTeamMessage,
} from './team-chat-helpers'
import type { TeamChatMember, TeamMessage, User } from './api'

const adminUser: User = {
  id: 1,
  username: 'alice',
  email: 'admin@co.test',
  full_name: 'Alice Admin',
  title: 'CTO',
  role: 'admin',
  company_id: 10,
  company: null,
  department_id: null,
  department_name: null,
}

const empUser: User = {
  id: 2,
  username: 'bob',
  email: 'bob@co.test',
  full_name: 'Bob Dev',
  title: 'Engineer',
  role: 'employee',
  company_id: 10,
  company: null,
  department_id: null,
  department_name: null,
}

const viewerUser: User = {
  id: 3,
  username: 'vera',
  email: 'view@co.test',
  full_name: 'Vera Viewer',
  title: 'Auditor',
  role: 'viewer',
  company_id: 10,
  company: null,
  department_id: null,
  department_name: null,
}

function makeMsg(overrides: Partial<TeamMessage> = {}): TeamMessage {
  return {
    id: 100,
    room_id: 1,
    sender_type: 'user',
    sender_id: 2,
    sender: {
      id: 2,
      full_name: 'Bob Dev',
      email: 'bob@co.test',
      title: 'Engineer',
      role: 'employee',
      department_name: null,
    },
    content: 'Hello team',
    reply_to_id: null,
    reply_to: null,
    referenced_document: null,
    sources: [],
    metadata: {},
    reactions: [],
    is_pinned: false,
    pinned_by_id: null,
    pinned_by_name: null,
    pinned_at: null,
    is_edited: false,
    edited_at: null,
    edit_expires_at: new Date(1_700_000_900_000).toISOString(),
    created_at: new Date(1_700_000_000_000).toISOString(),
    ...overrides,
  }
}

describe('team chat RBAC helpers', () => {
  const insideWindow = 1_700_000_300_000
  const expiredWindow = 1_700_001_000_000

  it('allows author to edit own message only before edit window expires', () => {
    const bobMsg = makeMsg({ sender_id: 2 })
    expect(canEditTeamMessage(empUser, bobMsg, insideWindow)).toBe(true)
    expect(editSecondsRemaining(bobMsg, insideWindow)).toBe(600)
    expect(canEditTeamMessage(empUser, bobMsg, expiredWindow)).toBe(false)
    expect(editSecondsRemaining(bobMsg, expiredWindow)).toBe(0)
  })

  it('forbids admin from editing others messages, allows admin delete any', () => {
    const bobMsg = makeMsg({ sender_id: 2 })
    const botMsg = makeMsg({ id: 101, sender_type: 'deskwise', sender_id: null, sender: null, edit_expires_at: null })

    expect(canEditTeamMessage(adminUser, bobMsg, insideWindow)).toBe(false)
    expect(canEditTeamMessage(adminUser, botMsg, insideWindow)).toBe(false)
    expect(canDeleteTeamMessage(adminUser, bobMsg)).toBe(true)
    expect(canDeleteTeamMessage(adminUser, botMsg)).toBe(true)

    // Employees delete only own human messages
    expect(canDeleteTeamMessage(empUser, bobMsg)).toBe(true)
    expect(canDeleteTeamMessage(empUser, botMsg)).toBe(false)
    expect(canDeleteTeamMessage(empUser, makeMsg({ sender_id: 1 }))).toBe(false)
  })

  it('allows any non-viewer to pin messages, blocks viewers', () => {
    expect(canPinTeamMessage(adminUser)).toBe(true)
    expect(canPinTeamMessage(empUser)).toBe(true)
    expect(canPinTeamMessage(viewerUser)).toBe(false)
    expect(canDeleteTeamMessage(viewerUser, makeMsg({ sender_id: 3 }))).toBe(false)
  })
})

describe('mention autocomplete & message list helpers', () => {
  const members: TeamChatMember[] = [
    { id: 1, full_name: 'Alice Admin', email: 'alice@co.test', title: 'HR', role: 'admin', department_id: null, department_name: null },
    { id: 2, full_name: 'Bob Dev', email: 'bob@co.test', title: 'Eng', role: 'employee', department_id: null, department_name: null },
  ]

  it('detects @mention query and prioritizes @DeskWise', () => {
    const detected = detectMentionQuery('Hey @de', 7)
    expect(detected).toEqual({ query: 'de', startIndex: 4 })
    const matches = filterMentionCandidates(members, 'desk', 2)
    expect(matches[0].handle).toBe('DeskWise')

    const applied = applyMentionSelection('Hey @de please', 4, 7, 'DeskWise')
    expect(applied.nextText).toBe('Hey @DeskWise please')
  })

  it('upserts and sorts messages deterministically by id', () => {
    const m1 = makeMsg({ id: 1, content: 'one' })
    const m2 = makeMsg({ id: 2, content: 'two' })
    const m2Updated = makeMsg({ id: 2, content: 'two edited', is_edited: true })
    const merged = upsertTeamMessage(upsertTeamMessage([m2], m1), m2Updated)
    expect(merged.map((m) => [m.id, m.content])).toEqual([
      [1, 'one'],
      [2, 'two edited'],
    ])
  })
})
