import { afterEach, expect, it, vi } from 'vitest'

const { init } = vi.hoisted(() => ({ init: vi.fn() }))
vi.mock('@sentry/nextjs', () => ({ init }))

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
  init.mockClear()
})

it.each(['node', 'edge'])('routes %s errors to the frontend source-map project and build release', async runtime => {
  vi.stubEnv('NEXT_PUBLIC_SENTRY_DSN', 'https://public@example.invalid/frontend')
  vi.stubEnv('SENTRY_DSN', 'https://public@example.invalid/backend')
  vi.stubEnv('NEXT_PUBLIC_GIT_SHA', 'a'.repeat(40))
  vi.stubEnv('GIT_SHA', 'b'.repeat(40))
  if (runtime === 'node') await import('../../../sentry.server.config')
  else await import('../../../sentry.edge.config')
  expect(init).toHaveBeenCalledWith(expect.objectContaining({
    dsn: 'https://public@example.invalid/frontend',
    release: 'a'.repeat(40),
    sendDefaultPii: false,
  }))
})
