// Server-side Sentry init (Node.js runtime — server components, server actions,
// route handlers). Keep all Next.js runtimes in the project receiving source maps.
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
        // 1%, jak w przeglądarce: wczytanie strony dziedziczy tę decyzję (meta `baggage`),
        // a za nim każde żądanie do API z tej karty. Przy 10% (zmienna wspólna z backendem)
        // limit 5 mln spanów Sentry poszedł w 80% w 10 dni (17.11.2026).
        tracesSampleRate: 0.01,
        profilesSampleRate: parseFloat(process.env.SENTRY_PROFILES_SAMPLE_RATE ?? '0.1'),
        // Drop healthcheck noise.
        beforeSendTransaction(event) {
            if (event.transaction?.includes('/api/health')) {
                return null
            }
            return scrubSentryEvent(event)
        },
    })
}
