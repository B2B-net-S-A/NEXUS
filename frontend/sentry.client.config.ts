// Client-side Sentry init (browser bundle). DSN must be a NEXT_PUBLIC_* env so
// it's embedded at build time. Conditional so the SDK is a no-op when the DSN
// is not set.
//
// Privacy: NEXUS handles candidate ATS data — replays must mask all text and
// block all media so personal data never leaves the user's browser.
import * as Sentry from '@sentry/nextjs'

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN

if (dsn) {
    Sentry.init({
        dsn,
        environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? 'production',
        release: process.env.NEXT_PUBLIC_GIT_SHA,
        tracesSampleRate: 0.1,
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 1.0,
        integrations: [
            Sentry.replayIntegration({
                maskAllText: true,
                blockAllMedia: true,
            }),
        ],
    })
}
