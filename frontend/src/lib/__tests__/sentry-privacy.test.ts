import { expect, it } from 'vitest'
import type { Event } from '@sentry/nextjs'
import { scrubSentryEvent, firstInSession } from '../sentry-privacy'

it('removes private content while retaining source locations', () => {
  const secret = 'CV private@example.com +48600111222 token=secret-value'
  const event: Event = {
    message: secret, request: { url: '/public/cv/secret-value', data: secret },
    user: { email: secret }, extra: { prompt: secret },
    exception: { values: [{ type: 'Error', value: secret, stacktrace: { frames: [{ filename: 'page.tsx', lineno: 42, vars: { cv: secret } }] } }] },
    breadcrumbs: [{ message: secret, data: { body: secret } }],
    contexts: { ai: { prompt: secret } },
  }
  const result = scrubSentryEvent(event)
  expect(JSON.stringify(result)).not.toContain(secret)
  expect(result.exception?.values?.[0].stacktrace?.frames?.[0]).toEqual({ filename: 'page.tsx', lineno: 42 })
})
it('captures first session occurrence and preserves a different signature', () => {
  expect(firstInSession('hydration-test:1')).toBe(true)
  expect(firstInSession('hydration-test:1')).toBe(false)
  expect(firstInSession('hydration-test:2')).toBe(true)
})
