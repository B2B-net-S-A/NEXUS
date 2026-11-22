// Edge runtime Sentry init (middleware.ts + any route handler with
// runtime: 'edge'). Lighter SDK surface than the Node runtime — no profiling,
// no replay.
import * as Sentry from '@sentry/nextjs'

import { scrubSentryEvent } from './src/lib/sentry-privacy'

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_DSN

if (dsn) {
    Sentry.init({
        dsn,
        environment: process.env.SENTRY_ENVIRONMENT ?? 'production',
        release: process.env.NEXT_PUBLIC_GIT_SHA || process.env.GIT_SHA,
        sendDefaultPii: false,
        beforeSend: scrubSentryEvent,
        beforeSendTransaction: scrubSentryEvent,
        // 1%, jak w przeglądarce i na serwerze Nexta (sentry.server.config.ts).
        tracesSampleRate: 0.01,
    })
}
