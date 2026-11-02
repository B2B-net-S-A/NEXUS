/** Rolling deployments may serve the new frontend before the new API. */
export const apiTraceTargets: RegExp[] = []
let compatible = false
// Pamiętane między wczytaniami: pierwsza partia żądań karty otwartej z linku idzie,
// zanim sonda odpowie, a bez tej pamięci taka wizyta nie liczyłaby się wcale.
const USAGE_COUNTER_KEY = 'nexus_usage_counter'
let usageCounter: boolean | undefined
let probing: Promise<void> | undefined
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
  const base = process.env.NEXT_PUBLIC_API_URL || 'https://api.nexus.dynaminds.pl'
  probing = (async () => {
    try {
      // A simple request (no custom headers) works against both API versions.
      const response = await fetch(`${base.replace(/\/$/, '')}/api/health`, {
        credentials: 'omit', signal: AbortSignal.timeout(5000),
      })
      compatible = response.ok && /^[a-f0-9-]{36}$/i.test(response.headers.get('x-request-id') ?? '')
      if (compatible && apiTraceTargets.length === 0) {
        apiTraceTargets.push(/^https:\/\/api\.nexus\.dynaminds\.pl(?:\/|$)/)
      }
      rememberUsageCounter(compatible && (await response.json()).usageCounter === true)
    } catch { /* Errors still report; tracing waits for a compatible API. */ }
    finally { probing = undefined }
  })()
  return probing
}
