'use client'

// App Router error boundary. Captures unhandled exceptions in any nested
// route segment and reports them to Sentry. Without this, errors bubble to
// global-error.tsx (Next default) which is harder to debug.
import { useEffect } from 'react'
import * as Sentry from '@sentry/nextjs'

interface ErrorPageProps {
    error: Error & { digest?: string }
    reset: () => void
}

export default function ErrorPage({ error, reset }: ErrorPageProps) {
    useEffect(() => {
        Sentry.captureException(error, {
            tags: {
                boundary: 'app-router',
                digest: error.digest ?? 'unknown',
            },
        })
    }, [error])

    return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
            <h2 className="text-2xl font-bold">Coś poszło nie tak</h2>
            <p className="max-w-md text-sm text-muted-foreground">
                Wystąpił nieoczekiwany błąd. Zespół został powiadomiony.
            </p>
            {process.env.NODE_ENV === 'development' && (
                <pre className="max-w-2xl overflow-auto rounded-md bg-muted p-4 text-xs">
                    {error.message}
                </pre>
            )}
            <button
                onClick={() => reset()}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
                Spróbuj ponownie
            </button>
        </div>
    )
}
