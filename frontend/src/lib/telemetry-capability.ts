const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'https://api.nexus.dynaminds.pl').replace(/\/$/, '')

function originTarget(base: string): RegExp[] {
  // Konfiguracja Sentry ładuje ten moduł przed resztą aplikacji: zły adres nie może jej wywrócić.
  try {
    const origin = new URL(base).origin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return [new RegExp(`^${origin}(?:/|$)`)]
  } catch { return [] }
}

/**
 * `tracePropagationTargets` od pierwszego żądania strony, bez czekania na sondę. Cel
 * dopisywany po sondzie gubił 26 z 37 pierwszych żądań wczytania `/dashboard`, a sonda
 * nieudana w zastoju backendu zostawiała kartę bez propagacji na minuty (24.11.2026);
 * żądanie bez `sentry-trace` backend próbkuje sam (10%). CORS API przepuszcza
 * `sentry-trace` i `baggage` od 14.09.2026 (strażnik: backend/tests/test_sentry_traces_sampler.py).
 * Cel z adresu, który bundel naprawdę woła: na sztywno wpisana stara domena po przeprowadzce
 * API na b2bnetwork.pl (05.11.2026) wyłączyła przekazywanie decyzji o próbkowaniu (17.11).
 */
export const apiTraceTargets: RegExp[] = originTarget(API_BASE)
// Rolling deployments may serve the new frontend before the new API: `X-Operation-Id` waits for the probe.
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
  probing = (async () => {
    try {
      // Bez własnych nagłówków. Pierwsza sonda wychodzi przed `Sentry.init`, kolejne
      // niosą `sentry-trace` z celu wyżej, a CORS API go przepuszcza.
      const response = await fetch(`${API_BASE}/api/health/live`, {
        credentials: 'omit', signal: AbortSignal.timeout(5000),
      })
      compatible = response.ok && /^[a-f0-9-]{36}$/i.test(response.headers.get('x-request-id') ?? '')
      rememberUsageCounter(compatible && (await response.json()).usageCounter === true)
    } catch { /* Errors and traces still report; `X-Operation-Id` waits for a compatible API. */ }
    finally {
      if (!compatible) nextProbeAt = Date.now() + RETRY_AFTER_FAILURE_MS
      probing = undefined
    }
  })()
  return probing
}
