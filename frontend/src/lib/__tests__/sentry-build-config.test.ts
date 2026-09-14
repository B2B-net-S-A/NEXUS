import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import { expect, it } from 'vitest'

function check(env: Record<string, string>) {
  return spawnSync(process.execPath, [resolve('scripts/check-sentry-build-env.mjs')], { env: { NODE_ENV: 'test', ...env }, encoding: 'utf8' })
}

// Brak tokena uploadu albo pełnego SHA NIE blokuje obrazu (standard obserwowalności:
// build przechodzi bez SENTRY_AUTH_TOKEN), ale nie jest cichy — ostrzeżenie nazywa
// każdy brak. Twardy `exit 1` razem z Coolify bez SOURCE_COMMIT w buildzie
// uniemożliwiał zbudowanie frontendu w ogóle (14.09.2026).
it('warns loudly but keeps the build going when upload or release configuration is missing', () => {
  const result = check({ NEXT_PUBLIC_SENTRY_DSN: 'synthetic' })
  expect(result.status).toBe(0)
  expect(result.stderr).toContain('SENTRY_BUILD_CONFIGURATION_INCOMPLETE')
  expect(result.stderr).toContain('SENTRY_AUTH_TOKEN')
  expect(result.stderr).toContain('full release SHA')
  expect(result.stdout).not.toContain('SENTRY_BUILD_CONFIGURATION_OK')
})

it('names only the missing release SHA and never prints the upload credential', () => {
  const result = check({ NEXT_PUBLIC_SENTRY_DSN: 'synthetic', NEXT_PUBLIC_GIT_SHA: 'unknown', SENTRY_AUTH_TOKEN: 'synthetic-private-upload-token' })
  expect(result.status).toBe(0)
  expect(result.stderr).toContain('SENTRY_BUILD_CONFIGURATION_INCOMPLETE')
  expect(result.stderr).toContain('full release SHA (got "unknown")')
  expect(result.stderr).not.toContain('SENTRY_AUTH_TOKEN')
  expect(`${result.stdout}${result.stderr}`).not.toContain('synthetic-private-upload-token')
})

it('accepts a full SHA and upload credential without printing the credential', () => {
  const result = check({ NEXT_PUBLIC_SENTRY_DSN: 'synthetic', NEXT_PUBLIC_GIT_SHA: 'a'.repeat(40), SENTRY_AUTH_TOKEN: 'synthetic-private-upload-token' })
  expect(result.status).toBe(0)
  expect(result.stdout).toContain('SENTRY_BUILD_CONFIGURATION_OK')
  expect(result.stdout).not.toContain('synthetic-private-upload-token')
})

it('supports builds with telemetry explicitly disabled', () => {
  expect(check({}).status).toBe(0)
})
