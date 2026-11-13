import { describe, expect, it } from 'vitest'

import { makeT, t } from './i18n'

describe('i18n', () => {
  it('returns English strings by default', () => {
    expect(t('documents')).toBe('Documents')
    expect(t('loading')).toBe('Loading…')
  })

  it('returns localized strings for supported global languages', () => {
    expect(t('documents', 'es')).toBe('Documentos')
    expect(t('language', 'fr')).toBe('Langue')
    expect(t('documents', 'ur')).toBe('Documents')
    expect(t('welcomeBack', 'ur')).toBe('Khush amdeed,')
    expect(t('markPresent', 'ur')).toContain('haziri')
  })

  it('makeT binds the language once', () => {
    const ur = makeT('ur')
    expect(ur('language')).toBe('Zuban')
    expect(ur('cancel')).toBe(' Mansookh')
  })

  it('never returns an empty string for a known key across all supported languages', () => {
    const keys = ['askAi', 'shared', 'attendance', 'audit', 'usagePlan', 'sources'] as const
    const langs = ['en', 'es', 'fr', 'de', 'ar', 'pt', 'ur'] as const
    for (const key of keys) {
      for (const lang of langs) {
        expect(t(key, lang).length).toBeGreaterThan(0)
      }
    }
  })
})
