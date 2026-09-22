import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Event, EventHint } from '@sentry/nextjs'

const { init, addEventProcessor } = vi.hoisted(() => ({
  init: vi.fn(),
  addEventProcessor: vi.fn(),
}))
vi.mock('@sentry/nextjs', () => ({ init, addEventProcessor, replayIntegration: vi.fn() }))
vi.mock('../telemetry-capability', () => ({ apiTraceTargets: [], probeTelemetryCapability: vi.fn() }))

let report: (event: Event, hint?: EventHint) => Event | null

beforeEach(async () => {
  vi.resetModules()
  init.mockClear()
  addEventProcessor.mockClear()
  sessionStorage.clear()
  vi.stubEnv('NEXT_PUBLIC_SENTRY_DSN', 'https://public@example.invalid/frontend')
  await import('../../../sentry.client.config')
  const beforeSend = init.mock.calls[0][0].beforeSend
  const processor = addEventProcessor.mock.calls[0][0]
  // The SDK runs event processors before beforeSend. Replay filtering must
  // leave the original error available for classification at that boundary.
  report = (event, hint = {}) => {
    const processed = processor(event)
    return processed ? beforeSend(processed, hint) : null
  }
})

afterEach(() => vi.unstubAllEnvs())

function reactEvent(code: number): Event {
  return {
    exception: { values: [{
      type: 'Error',
      value: `Minified React error #${code}; visit https://react.dev/errors/${code}?args[]=private@example.com`,
      stacktrace: { frames: [{ filename: 'on-recoverable-error.js', lineno: 30 }] },
      mechanism: { type: 'auto.browser.global_handlers.onerror', handled: false },
    }] },
  }
}

it.each([419, 422, 423, 424])('retains the first React #%s recovery diagnostic without private arguments', code => {
  const result = report(reactEvent(code))
  expect(result?.tags).toMatchObject({
    failure_kind: 'react-recoverable-error',
    react_error_code: String(code),
    sampling_policy: 'first-per-session',
  })
  expect(result?.fingerprint).toEqual(['react-recoverable-error', `react-${code}`])
  expect(result?.exception?.values?.[0].value).toBe(`React error #${code} (private details omitted)`)
  expect(JSON.stringify(result)).not.toContain('private@example.com')
  expect(JSON.stringify(result)).not.toContain('args[]')
  expect(report(reactEvent(code))).toBeNull()
})

it('keeps different React recovery codes at the same callback independently visible', () => {
  expect(report(reactEvent(419))).not.toBeNull()
  expect(report(reactEvent(422))).not.toBeNull()
})

it.each([418, 425])('keeps React #%s hydration mismatches separate from server recovery', code => {
  expect(report(reactEvent(code))?.tags).toMatchObject({
    failure_kind: 'hydration-error', react_error_code: String(code),
  })
})

it('finds the React code beyond the first chained exception', () => {
  const event = reactEvent(419)
  event.exception!.values!.unshift({ type: 'Error', value: 'private inner error' })
  const result = report(event)
  expect(result?.tags?.react_error_code).toBe('419')
  expect(JSON.stringify(result)).not.toContain('private inner error')
})

it('does not suppress unrelated React failures', () => {
  const first = report(reactEvent(310))
  expect(first?.tags?.react_error_code).toBe('310')
  expect(first?.tags?.sampling_policy).toBeUndefined()
  expect(report(reactEvent(310))).not.toBeNull()
})

it('preserves deterministic terminal mutation reporting even with a recoverable React code', () => {
  const event = reactEvent(419)
  event.tags = { failure_kind: 'client', sampling_policy: 'all-terminal-writes', terminal: 'true' }
  event.fingerprint = ['client-mutation-failure', '{{ default }}', 'react-419']
  for (let attempt = 0; attempt < 2; attempt++) {
    const result = report(structuredClone(event))
    expect(result?.tags).toMatchObject({ failure_kind: 'client', sampling_policy: 'all-terminal-writes' })
    expect(result?.fingerprint).toEqual(event.fingerprint)
  }
})

it('does not infer recovery solely from the callback stack', () => {
  const event = reactEvent(419)
  event.exception!.values![0].value = 'private application error'
  const result = report(event)
  expect(result?.tags?.failure_kind).toBeUndefined()
  expect(JSON.stringify(result)).not.toContain('private application error')
})

it('still reports a chunk failure only once per session', () => {
  const event: Event = { exception: { values: [{ type: 'ChunkLoadError', value: 'Loading chunk abc failed' }] } }
  expect(report(structuredClone(event))?.tags?.failure_kind).toBe('chunk-load-error')
  expect(report(structuredClone(event))).toBeNull()
})
