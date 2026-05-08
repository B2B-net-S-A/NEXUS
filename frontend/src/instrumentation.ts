// Next.js 15 instrumentation hook — runs once per server worker on boot.
// Sentry init is split per runtime so the right SDK is loaded for Node vs Edge.
//
// Sentry init is idempotent and a no-op when SENTRY_DSN is unset, so this file
// is safe to commit before the DSN is provisioned in Coolify env vault.

export async function register(): Promise<void> {
    if (process.env.NEXT_RUNTIME === 'nodejs') {
        await import('../sentry.server.config')
    }
    if (process.env.NEXT_RUNTIME === 'edge') {
        await import('../sentry.edge.config')
    }
}

// Next.js 15 hook for capturing request-level errors in App Router routes.
// @sentry/nextjs ^9 exports captureRequestError as the canonical name.
export { captureRequestError as onRequestError } from '@sentry/nextjs'
