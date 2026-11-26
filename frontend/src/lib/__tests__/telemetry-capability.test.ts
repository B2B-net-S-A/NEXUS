import { expect, it, vi, afterEach } from 'vitest'
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules() })
const API = 'https://api.nexus.b2bnetwork.pl'
const tracesTo = (targets: RegExp[], url: string) => targets.some(target => target.test(url))
const pendingProbe = () => vi.fn(() => new Promise<Response>(() => {}))
it('traces the first request of the page, before the probe answers', async () => {
  // 24.11.2026: z celem dopisywanym po sondzie 26 z 37 pierwszych żądań wczytania
  // `/dashboard` szło bez `sentry-trace`, więc backend próbkował je sam (10%).
  vi.stubEnv('NEXT_PUBLIC_API_URL', API)
  vi.stubGlobal('fetch', pendingProbe())
  const capability = await import('../telemetry-capability')
  void capability.probeTelemetryCapability()
  expect(tracesTo(capability.apiTraceTargets, `${API}/api/users/me/preferences`)).toBe(true)
})
it('hands Sentry the API target at init, while the probe is still in flight', async () => {
  const init = vi.fn()
  vi.doMock('@sentry/nextjs', () => ({ init, addEventProcessor: vi.fn(), replayIntegration: vi.fn() }))
  try {
    vi.stubEnv('NEXT_PUBLIC_SENTRY_DSN', 'https://public@example.invalid/frontend')
    vi.stubEnv('NEXT_PUBLIC_API_URL', API)
    const fetchMock = pendingProbe()
    vi.stubGlobal('fetch', fetchMock)
    await import('../../../sentry.client.config')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(tracesTo(init.mock.calls[0][0].tracePropagationTargets, `${API}/api/kpis/me/today`)).toBe(true)
  } finally {
    vi.doUnmock('@sentry/nextjs')
  }
})
it('keeps trace propagation after a failed probe', async () => {
  // 24.11.2026 sonda padła w 52-sekundowym zastoju backendu. Ponawia ją dopiero żądanie
  // axios po minucie, a pulpit odpytuje co 5 min, więc karta była bez propagacji ponad 3 min.
  vi.stubEnv('NEXT_PUBLIC_API_URL', API)
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
  const capability = await import('../telemetry-capability')
  await capability.probeTelemetryCapability()
  expect(capability.apiSupportsCorrelation()).toBe(false)
  expect(tracesTo(capability.apiTraceTargets, `${API}/api/jobs`)).toBe(true)
})
it('sends no X-Operation-Id to an API without X-Request-Id, but keeps trace propagation', async () => {
  // `sentry-trace` i `baggage` CORS API przepuszcza od 14.09.2026 (#1515); strażnik:
  // backend/tests/test_sentry_traces_sampler.py.
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  const capability = await import('../telemetry-capability')
  await capability.probeTelemetryCapability()
  expect(capability.apiSupportsCorrelation()).toBe(false)
  expect(capability.apiTraceTargets).toHaveLength(1)
})
it('enables correlation after a compatible simple response and traces only the NEXUS API', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200, headers: { 'x-request-id':crypto.randomUUID() } })))
  const capability = await import('../telemetry-capability')
  await capability.probeTelemetryCapability()
  expect(capability.apiSupportsCorrelation()).toBe(true)
  expect(capability.apiTraceTargets[0].test('https://api.nexus.b2bnetwork.pl/api/jobs')).toBe(true)
  expect(capability.apiTraceTargets[0].test('https://external.example/api')).toBe(false)
})
it('sends trace headers to the API the bundle actually calls, not a hard-coded host', async () => {
  // Od 05.11.2026 API stoi pod api.nexus.b2bnetwork.pl. Cel na sztywno ustawiony na starą
  // domenę wyłączył przekazywanie decyzji o próbkowaniu i backend sam próbkował 10% żądań.
  vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.nexus.b2bnetwork.pl/')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200, headers: { 'x-request-id': crypto.randomUUID() } })))
  const capability = await import('../telemetry-capability')
  await capability.probeTelemetryCapability()
  expect(capability.apiTraceTargets).toHaveLength(1)
  expect(capability.apiTraceTargets[0].test('https://api.nexus.b2bnetwork.pl/api/jobs')).toBe(true)
  expect(capability.apiTraceTargets[0].test('https://api.nexus.b2bnetwork.pl.evil.example/api')).toBe(false)
  expect(capability.apiTraceTargets[0].test('https://api.nexus.dynaminds.pl/api/jobs')).toBe(false)
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
it('probes the cheap liveness route, never the full health check', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  const capability = await import('../telemetry-capability')
  await capability.probeTelemetryCapability()
  expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/health\/live$/)
})
it('waits a minute after a failed probe instead of probing on every request', async () => {
  vi.useFakeTimers()
  try {
    const fetchMock = vi.fn().mockRejectedValue(new Error('timeout'))
    vi.stubGlobal('fetch', fetchMock)
    const capability = await import('../telemetry-capability')
    await capability.probeTelemetryCapability()
    await capability.probeTelemetryCapability()
    await capability.probeTelemetryCapability()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(60_000)
    fetchMock.mockResolvedValue(new Response('{}', { status: 200, headers: { 'x-request-id': crypto.randomUUID() } }))
    await capability.probeTelemetryCapability()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(capability.apiSupportsCorrelation()).toBe(true)
  } finally {
    vi.useRealTimers()
  }
})
it('keeps the counter off against an older API without the field', async () => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  const capability = await import('../telemetry-capability')
  await capability.probeTelemetryCapability()
  expect(capability.apiWantsUsageScreen()).toBe(false)
})
