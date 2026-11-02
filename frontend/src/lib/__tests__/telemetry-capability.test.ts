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
it('asks for the usage screen only when the API says the counter is on, and remembers it', async () => {
  localStorage.clear()
  const health = (body: object) => new Response(JSON.stringify(body), { status: 200, headers: { 'x-request-id':crypto.randomUUID() } })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(health({ usageCounter: true })))
  const on = await import('../telemetry-capability')
  expect(on.apiWantsUsageScreen()).toBe(false)
  await on.probeTelemetryCapability()
  expect(on.apiWantsUsageScreen()).toBe(true)

  // Nowa karta: zanim sonda odpowie, wystarcza pamięć z poprzedniej.
  vi.resetModules()
  const nextTab = await import('../telemetry-capability')
  expect(nextTab.apiWantsUsageScreen()).toBe(true)

  // Wyłączenie albo powrót do starszego API kasuje pamięć.
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(health({ usageCounter: false })))
  await nextTab.probeTelemetryCapability()
  expect(nextTab.apiWantsUsageScreen()).toBe(false)
  expect(localStorage.getItem('nexus_usage_counter')).toBeNull()
})
it('keeps the counter off against an older API without the field', async () => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  const capability = await import('../telemetry-capability')
  await capability.probeTelemetryCapability()
  expect(capability.apiWantsUsageScreen()).toBe(false)
})
