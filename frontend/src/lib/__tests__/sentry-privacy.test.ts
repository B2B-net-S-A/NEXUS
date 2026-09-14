import { expect, it } from 'vitest'
import type { Event } from '@sentry/nextjs'
import { scrubSentryEvent, scrubReplayEvent, firstInSession } from '../sentry-privacy'

it('removes private content while retaining source locations', () => {
  const secret = 'CV private@example.com +48600111222 token=secret-value'
  const event: Event = {
    message: secret, request: { url: '/public/cv/secret-value', data: secret },
    user: { email: secret }, extra: { prompt: secret },
    exception: { values: [{ type: 'Error', value: secret, stacktrace: { frames: [{ filename: 'page.tsx', lineno: 42, vars: { cv: secret } }] } }] },
    threads: { values: [{ stacktrace: { frames: [{ filename: 'logger.ts', lineno: 5, vars: { cv: secret }, context_line: secret }] } }] },
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

it('redacts capabilities and query data from stack URLs while retaining file and line', () => {
  const result = scrubSentryEvent({ exception: { values: [{ stacktrace: { frames: [
    { filename: 'https://nexus.dynaminds.pl/cv/synthetic-private-token?email=private@example.com', lineno: 8 },
    { filename: 'https://nexus.dynaminds.pl/_next/static/chunks/app.js?token=private', lineno: 42 },
  ] } }] } })
  const frames = result.exception.values[0].stacktrace.frames
  expect(frames[0]).toEqual({ filename: 'https://nexus.dynaminds.pl/cv/[redacted]', lineno: 8 })
  expect(frames[1]).toEqual({ filename: 'https://nexus.dynaminds.pl/_next/static/chunks/app.js', lineno: 42 })
})

it('rejects private replay metadata and subsequent segments of that recording', () => {
  const replay = { type: 'replay_event', replay_id: 'private-replay', urls: ['https://nexus.dynaminds.pl/cv/synthetic-token'] } as Event
  expect(scrubReplayEvent(replay, 'https://nexus.dynaminds.pl/')).toBeNull()
  expect(scrubReplayEvent({ ...replay, urls: [] } as Event, 'https://nexus.dynaminds.pl/')).toBeNull()
  expect(scrubReplayEvent({ type: 'replay_event', replay_id: 'query-replay', urls: [] } as Event, 'https://nexus.dynaminds.pl/?email=private@example.com')).toBeNull()
})

it('retains a safe replay with private identity/context removed', () => {
  const replay = { type: 'replay_event', replay_id: 'safe-replay', urls: ['https://nexus.dynaminds.pl/'], user: { email: 'private@example.com' }, contexts: { private: { data: 'private-value' } } } as Event
  const result = scrubReplayEvent(replay, 'https://nexus.dynaminds.pl/')
  expect(result).not.toBeNull()
  expect(JSON.stringify(result)).not.toContain('private')
})
