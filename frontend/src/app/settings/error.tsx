'use client'

import { useEffect } from 'react'
import * as Sentry from '@sentry/nextjs'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface SettingsErrorProps {
    error: Error & { digest?: string }
    reset: () => void
}

export default function SettingsError({ error, reset }: SettingsErrorProps) {
    useEffect(() => {
        Sentry.captureException(error, {
            tags: {
                boundary: 'settings',
                digest: error.digest ?? 'unknown',
            },
        })
    }, [error])

    return (
        <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
            <AlertTriangle className="h-12 w-12 text-amber-500" />
            <h2 className="text-xl font-semibold">Ustawienia chwilowo niedostępne</h2>
            <p className="max-w-md text-sm text-muted-foreground">
                Nie udało się załadować ustawień. Najczęściej pomaga odświeżenie —
                jeśli problem będzie się powtarzał, zgłoś to administratorowi.
            </p>
            {process.env.NODE_ENV === 'development' && (
                <pre className="max-w-2xl overflow-auto rounded-md bg-muted p-4 text-left text-xs">
                    {error.message}
                </pre>
            )}
            <button
                onClick={() => reset()}
                className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
                <RefreshCw className="h-4 w-4" />
                Spróbuj ponownie
            </button>
        </div>
    )
}
