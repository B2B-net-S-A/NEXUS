// Client-side Sentry init (browser bundle). DSN must be a NEXT_PUBLIC_* env so
// it's embedded at build time. Conditional so the SDK is a no-op when the DSN
// is not set.
//
// Privacy: NEXUS handles candidate ATS data — replays must mask all text and
// block all media so personal data never leaves the user's browser.
//
import * as Sentry from '@sentry/nextjs'
import { apiTraceTargets, probeTelemetryCapability } from './src/lib/telemetry-capability'

import { scrubSentryEvent, firstInSession } from './src/lib/sentry-privacy'

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN

/** Ułamek bezcielesnych błędów sieci raportowanych do Sentry (patrz beforeSend). */
const NETWORK_ERROR_SAMPLE_RATE = 0.1
/** Ułamek błędów ładowania chunków JS raportowanych do Sentry (patrz beforeSend). */
const HYDRATION_ERROR_RE = /hydration|Hydration|Minified React error #(418|423|425)/
const CHUNK_ERROR_RE = /ChunkLoadError|Loading chunk [\w-]+ failed/

if (dsn) {
    void probeTelemetryCapability()
    Sentry.init({
        dsn,
        environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? 'production',
        release: process.env.NEXT_PUBLIC_GIT_SHA,
        // 1% performance traces (was 10%) — cap quota while keeping enough
        // sampling to spot N+1 patterns and slow routes.
        tracesSampleRate: 0.01,
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 0.1,
        sendDefaultPii: false,
        tracePropagationTargets: apiTraceTargets,
        beforeSendTransaction: scrubSentryEvent,
        integrations: [
            Sentry.replayIntegration({
                maskAllText: true,
                blockAllMedia: true,
            }),
        ],
        // Drop known noise before it counts against quota.
        ignoreErrors: [
            // Browser quirks — not app bugs
            'ResizeObserver loop limit exceeded',
            'ResizeObserver loop completed with undelivered notifications',
            'Non-Error promise rejection captured',
            // ChunkLoadError CELOWO nie jest tu ignorowany — patrz `beforeSend`
            // (próbkowany: to bezpośredni ślad deployu widziany przez starą kartę).
            // Axios cancel — user navigated away before request returned
            'CanceledError',
            'AbortError',
            // 'Network Error' CELOWO nie jest tu ignorowany — patrz
            // `beforeSend`: próbkujemy go, zamiast wyrzucać w całości.
        ],
        beforeSend(event, hint) {
            const exc = hint?.originalException as
                | { message?: string; code?: string; name?: string }
                | undefined

            // Drop axios 401/403/404 from the report — those are expected
            // auth/permission states handled by the app, not crashes.
            const status = (
                exc as { response?: { status?: number } } | undefined
            )?.response?.status
            if (status === 401 || status === 403 || status === 404) {
                return null
            }

            // Surowy timeout axios odrzucamy — zapytania i mutacje react-query
            // zgłaszają go osobno jako syntetyczne `API timeout: …`
            // (`lib/query-error-telemetry.ts`), już z trasą i próbkowaniem.
            if (exc?.code === 'ECONNABORTED' || exc?.name === 'TimeoutError') {
                return null
            }

            // Błąd ładowania chunku = stara karta po deployu sięga po plik JS,
            // którego już nie ma. Przy ~8 przebudowach dziennie to bezpośredni
            // pomiar wpływu deployów na użytkowników (reaudyt 14.09.2026, R07),
            // więc próbkujemy zamiast wyrzucać; jeden fingerprint = jeden issue.
            const chunkText = `${exc?.name ?? ''} ${exc?.message ?? ''} ${
                event.exception?.values?.[0]?.type ?? ''
            } ${event.exception?.values?.[0]?.value ?? ''}`
            if (CHUNK_ERROR_RE.test(chunkText) || HYDRATION_ERROR_RE.test(chunkText)) {
                const kind = CHUNK_ERROR_RE.test(chunkText) ? "chunk-load-error" : "hydration-error"
                const frame = event.exception?.values?.[0]?.stacktrace?.frames?.at(-1)
                if (!firstInSession(`${kind}:${frame?.filename ?? ""}:${frame?.lineno ?? ""}`)) {
                    return null
                }
                event.fingerprint = [kind]
                event.tags = { ...event.tags, sampling_policy: 'first-per-session', failure_kind: kind }
                return scrubSentryEvent(event)
            }

            // Bezcielesny błąd sieci (axios `ERR_NETWORK`) — PRÓBKOWANY, nie
            // wyrzucany. Do 09.2026 leciał na `ignoreErrors`, a to jest
            // dokładnie kształt, jaki w przeglądarce ma 503 „no available
            // server" z Traefika i backendowe 500 bez nagłówków CORS —
            // obie klasy incydentów były w Sentry niewidoczne. 10% wystarcza,
            // żeby fala była widoczna na wykresie, a nie zjadła darmowego
            // limitu 5k zdarzeń; jeden fingerprint zbiera je w jeden issue.
            if (exc?.code === 'ERR_NETWORK') {
                if (Math.random() >= NETWORK_ERROR_SAMPLE_RATE) {
                    return null
                }
                event.fingerprint = ['network-error']
                event.tags = { ...event.tags, network_error: 'sampled' }
                return scrubSentryEvent(event)
            }

            return scrubSentryEvent(event)
        },
    })
}
