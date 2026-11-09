/** Rolling deployments may serve the new frontend before the new API. */
export const apiTraceTargets: RegExp[] = []
let compatible = false
// Pamiętane między wczytaniami: pierwsza partia żądań karty otwartej z linku idzie,
// zanim sonda odpowie, a bez tej pamięci taka wizyta nie liczyłaby się wcale.
const USAGE_COUNTER_KEY = 'nexus_usage_counter'
let usageCounter: boolean | undefined
let probing: Promise<void> | undefined
// Bez przerwy każde żądanie po nieudanej sondzie wysyłało następną: 04.11.2026
// przy nasyconym backendzie 151 sond na 10 minut zamiast 7–14.
const RETRY_AFTER_FAILURE_MS = 60_000
let nextProbeAt = 0
export function apiSupportsCorrelation(): boolean { return compatible }
/** Licznik użycia obszarów włączony na API: wtedy (i tylko wtedy) wolno wysłać `X-Nexus-Screen`. */
export function apiWantsUsageScreen(): boolean {
  if (usageCounter !== undefined) return usageCounter
  try { return localStorage.getItem(USAGE_COUNTER_KEY) === '1' } catch { return false }
}

function rememberUsageCounter(value: boolean): void {
  usageCounter = value
  try {
    if (value) localStorage.setItem(USAGE_COUNTER_KEY, '1')
    else localStorage.removeItem(USAGE_COUNTER_KEY)
  } catch { /* Bez pamięci licznik łapie tylko żądania po odpowiedzi sondy. */ }
}

export function probeTelemetryCapability(): Promise<void> {
  if (probing) return probing
  if (Date.now() < nextProbeAt) return Promise.resolve()
  const base = process.env.NEXT_PUBLIC_API_URL || 'https://api.nexus.dynaminds.pl'
  probing = (async () => {
    try {
      // A simple request (no custom headers) works against both API versions.
      const response = await fetch(`${base.replace(/\/$/, '')}/api/health/live`, {
        credentials: 'omit', signal: AbortSignal.timeout(5000),
      })
      compatible = response.ok && /^[a-f0-9-]{36}$/i.test(response.headers.get('x-request-id') ?? '')
      if (compatible && apiTraceTargets.length === 0) {
        apiTraceTargets.push(/^https:\/\/api\.nexus\.dynaminds\.pl(?:\/|$)/)
      }
      rememberUsageCounter(compatible && (await response.json()).usageCounter === true)
    } catch { /* Errors still report; tracing waits for a compatible API. */ }
    finally {
      if (!compatible) nextProbeAt = Date.now() + RETRY_AFTER_FAILURE_MS
      probing = undefined
    }
  })()
  return probing
}
