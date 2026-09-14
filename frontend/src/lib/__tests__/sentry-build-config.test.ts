import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import { expect, it } from 'vitest'

function check(env: Record<string, string>) {
  return spawnSync(process.execPath, [resolve('scripts/check-sentry-build-env.mjs')], { env, encoding: 'utf8' })
}

it('fails enabled telemetry builds when upload or release configuration is missing', () => {
  const result = check({ NEXT_PUBLIC_SENTRY_DSN: 'synthetic' })
  expect(result.status).toBe(1)
  expect(result.stderr).toContain('SENTRY_BUILD_CONFIGURATION_FAILED')
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
