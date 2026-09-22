// Client-side Sentry init (browser bundle). DSN must be a NEXT_PUBLIC_* env so
// it's embedded at build time. Conditional so the SDK is a no-op when the DSN
// is not set.
//
// Privacy: NEXUS handles candidate ATS data — replays must mask all text and
// block all media so personal data never leaves the user's browser.
//
import * as Sentry from '@sentry/nextjs'
import { apiTraceTargets, probeTelemetryCapability } from './src/lib/telemetry-capability'

import { scrubSentryEvent, scrubReplayEvent, firstInSession, reactErrorCode } from './src/lib/sentry-privacy'

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN

/** Ułamek bezcielesnych błędów sieci raportowanych do Sentry (patrz beforeSend). */
const NETWORK_ERROR_SAMPLE_RATE = 0.1
const HYDRATION_ERROR_RE = /hydration|Minified React error #(418|425)\b/i
// #419 is server-aborted Suspense; #422/#423 recover from hydration errors;
// #424 is an early root update. They do not all mean mismatched HTML.
const REACT_RECOVERY_CODES = new Set(['419', '422', '423', '424'])
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
                maskAllInputs: true,
                blockAllMedia: true,
                maskAttributes: ['title', 'aria-label', 'alt', 'href', 'src', 'value'],
                networkCaptureBodies: false,
                // Custom network/console/navigation payloads are free-form. DOM
                // recording remains fully masked; errors retain their own trace.
                beforeAddRecordingEvent: () => null,
            }),
        ],
        // Drop known noise before it counts against quota.
        ignoreErrors: [
            // Browser quirks — not app bugs
            'ResizeObserver loop limit exceeded',
            'ResizeObserver loop completed with undelivered notifications',
            'Non-Error promise rejection captured',
            // ChunkLoadError CELOWO nie jest tu ignorowany — patrz `beforeSend`
            // (pierwsze wystąpienie danej sygnatury w sesji).
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
            // więc raportujemy pierwszą sygnaturę w sesji.
            const failureText = [exc?.name, exc?.message, event.message,
                ...(event.exception?.values ?? []).flatMap(value => [value.type, value.value]),
            ].filter(value => typeof value === 'string').join(' ')
            const reactCode = reactErrorCode(failureText)
            const kind = CHUNK_ERROR_RE.test(failureText) ? 'chunk-load-error'
                : reactCode && REACT_RECOVERY_CODES.has(reactCode) ? 'react-recoverable-error'
                : HYDRATION_ERROR_RE.test(failureText) ? 'hydration-error' : undefined
            // A terminal write already has deterministic operation reporting.
            // Its React diagnostic must not turn that into session sampling.
            if (kind && event.tags?.sampling_policy !== 'all-terminal-writes') {
                const frame = event.exception?.values?.[0]?.stacktrace?.frames?.at(-1)
                if (!firstInSession(`${kind}:${reactCode ?? ''}:${frame?.filename ?? ""}:${frame?.lineno ?? ""}`)) {
                    return null
                }
                event.fingerprint = reactCode ? [kind, `react-${reactCode}`] : [kind]
                event.tags = { ...event.tags, sampling_policy: 'first-per-session', failure_kind: kind,
                    ...(reactCode ? { react_error_code: reactCode } : {}),
                }
                return scrubSentryEvent(event)
            }

            // Bezcielesny błąd sieci (axios `ERR_NETWORK`) — PRÓBKOWANY, nie
            // wyrzucany. Do 09.2026 leciał na `ignoreErrors`, a to jest
            // dokładnie kształt, jaki w przeglądarce ma 503 „no available
            // server" z Traefika i backendowe 500 bez nagłówków CORS —
            // obie klasy incydentów były w Sentry niewidoczne. 10% wystarcza,
            // żeby fala była widoczna bez nadmiernego zużycia limitu Team.
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
    Sentry.addEventProcessor(event => scrubReplayEvent(event, window.location.href))
}
