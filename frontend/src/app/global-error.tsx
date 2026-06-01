'use client'

// Last-resort error boundary. Triggers when root layout/template OR the
// nested `app/error.tsx` itself crashes (e.g. provider tree throws before
// QueryClientProvider mounts). Must include its own <html>/<body> because
// root layout was the thing that broke.
//
// Keep this file minimal – no providers, no global CSS imports, no auth
// store, no api client. Anything that can throw belongs in deeper layers.
import { useEffect } from 'react'
import * as Sentry from '@sentry/nextjs'

interface GlobalErrorProps {
    error: Error & { digest?: string }
    reset: () => void
}

export default function GlobalError({ error, reset }: GlobalErrorProps) {
    useEffect(() => {
        Sentry.captureException(error, {
            tags: {
                boundary: 'global',
                digest: error.digest ?? 'unknown',
            },
        })
    }, [error])

    return (
        <html lang="pl">
            <body
                style={{
                    margin: 0,
                    minHeight: '100vh',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontFamily:
                        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                    background: '#fafafa',
                    color: '#18181b',
                }}
            >
                <div
                    style={{
                        maxWidth: 480,
                        padding: 32,
                        textAlign: 'center',
                    }}
                >
                    <h1
                        style={{
                            fontSize: 24,
                            fontWeight: 600,
                            marginBottom: 12,
                        }}
                    >
                        Aplikacja nie odpowiada
                    </h1>
                    <p
                        style={{
                            fontSize: 14,
                            color: '#71717a',
                            marginBottom: 24,
                            lineHeight: 1.5,
                        }}
                    >
                        Wystąpił krytyczny błąd ładowania. Zespół został powiadomiony.
                        Spróbuj odświeżyć stronę – jeśli problem będzie się powtarzał,
                        sprawdź połączenie z internetem albo skontaktuj się z administratorem.
                    </p>
                    <button
                        onClick={() => reset()}
                        style={{
                            padding: '10px 20px',
                            borderRadius: 8,
                            border: 'none',
                            background: '#18181b',
                            color: 'white',
                            fontSize: 14,
                            fontWeight: 500,
                            cursor: 'pointer',
                        }}
                    >
                        Odśwież
                    </button>
                </div>
            </body>
        </html>
    )
}
