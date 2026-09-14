import { expect, it, vi, afterEach } from 'vitest'
afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })
it('does not send trace headers to an older API', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  const module = await import('../telemetry-capability')
  await module.probeTelemetryCapability()
  expect(module.apiSupportsCorrelation()).toBe(false)
  expect(module.apiTraceTargets).toHaveLength(0)
})
it('enables only the NEXUS target after a compatible simple response', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200, headers: { 'x-request-id':'12345678-1234-1234-1234-123456789abc' } })))
  const module = await import('../telemetry-capability')
  await module.probeTelemetryCapability()
  expect(module.apiSupportsCorrelation()).toBe(true)
  expect(module.apiTraceTargets[0].test('https://api.nexus.dynaminds.pl/api/jobs')).toBe(true)
  expect(module.apiTraceTargets[0].test('https://external.example/api')).toBe(false)
})
