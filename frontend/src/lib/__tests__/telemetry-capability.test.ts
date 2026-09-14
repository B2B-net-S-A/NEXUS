import { expect, it, vi, afterEach } from 'vitest'
afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })
it('does not send trace headers to an older API', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  const capability = await import('../telemetry-capability')
  await capability.probeTelemetryCapability()
  expect(capability.apiSupportsCorrelation()).toBe(false)
  expect(capability.apiTraceTargets).toHaveLength(0)
})
it('enables only the NEXUS target after a compatible simple response', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200, headers: { 'x-request-id':crypto.randomUUID() } })))
  const capability = await import('../telemetry-capability')
  await capability.probeTelemetryCapability()
  expect(capability.apiSupportsCorrelation()).toBe(true)
  expect(capability.apiTraceTargets[0].test('https://api.nexus.dynaminds.pl/api/jobs')).toBe(true)
  expect(capability.apiTraceTargets[0].test('https://external.example/api')).toBe(false)
})
