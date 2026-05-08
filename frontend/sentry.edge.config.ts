// Edge runtime Sentry init (middleware.ts + any route handler with
// runtime: 'edge'). Lighter SDK surface than the Node runtime — no profiling,
// no replay.
import * as Sentry from '@sentry/nextjs'

const dsn = process.env.SENTRY_DSN

if (dsn) {
    Sentry.init({
        dsn,
        environment: process.env.SENTRY_ENVIRONMENT ?? 'production',
        release: process.env.GIT_SHA,
        tracesSampleRate: parseFloat(process.env.SENTRY_TRACES_SAMPLE_RATE ?? '0.1'),
    })
}
