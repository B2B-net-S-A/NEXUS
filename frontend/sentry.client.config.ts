// Client-side Sentry init (browser bundle). DSN must be a NEXT_PUBLIC_* env so
// it's embedded at build time. Conditional so the SDK is a no-op when the DSN
// is not set.
//
// Privacy: NEXUS handles candidate ATS data — replays must mask all text and
// block all media so personal data never leaves the user's browser.
//
// QA 2026-05-27: Sentry envelope POST 503 — przekroczona b2bnet-sa free
// plan quota (5k events/mc). Tuning żeby zmieścić się:
//   - tracesSampleRate 0.1 → 0.01 (10x mniej performance traces; errory
//     wciąż zawsze łapane, traces są nice-to-have).
//   - beforeSend filter: drop axios cancel + network errors (np. user
//     close tab w trakcie request) — to znormalna noise.
//   - ignoreErrors: common browser noise (ResizeObserver, ChunkLoadError
//     z service workera) — nie błędy aplikacji, generują dużo events.
import * as Sentry from '@sentry/nextjs'

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN

if (dsn) {
    Sentry.init({
        dsn,
        environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? 'production',
        release: process.env.NEXT_PUBLIC_GIT_SHA,
        // 1% performance traces (was 10%) — cap quota while keeping enough
        // sampling to spot N+1 patterns and slow routes.
        tracesSampleRate: 0.01,
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 1.0,
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
            // Next.js chunk load failures (cache mismatch after deploy) —
            // user just reloads, no actionable bug
            /ChunkLoadError/,
            /Loading chunk \d+ failed/,
            // Axios cancel — user navigated away before request returned
            'CanceledError',
            'AbortError',
            // Network unreachable — usually offline/wifi blip, not app issue
            'Network Error',
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

            // Drop expected axios timeout (ECONNABORTED) — user can retry.
            if (exc?.code === 'ECONNABORTED' || exc?.name === 'TimeoutError') {
                return null
            }

            return event
        },
    })
}
