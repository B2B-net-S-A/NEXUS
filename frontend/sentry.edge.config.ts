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
        tracesSampleRate: parseFloat(process.env.SENTRY_TRACES_SAMPLE_RATE ?? '0.1'),
    })
}
