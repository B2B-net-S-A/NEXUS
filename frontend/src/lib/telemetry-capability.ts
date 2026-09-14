/** Rolling deployments may serve the new frontend before the new API. */
export const apiTraceTargets: RegExp[] = []
let compatible = false
let probing: Promise<void> | undefined
export function apiSupportsCorrelation(): boolean { return compatible }

export function probeTelemetryCapability(): Promise<void> {
  if (probing) return probing
  const base = process.env.NEXT_PUBLIC_API_URL || 'https://api.nexus.dynaminds.pl'
  probing = (async () => {
    try {
      // A simple request (no custom headers) works against both API versions.
      const response = await fetch(`${base.replace(/\/$/, '')}/api/health`, {
        credentials: 'omit', signal: AbortSignal.timeout(5000),
      })
      compatible = response.ok && /^[a-f0-9-]{36}$/i.test(response.headers.get('x-request-id') ?? '')
      if (compatible && apiTraceTargets.length === 0) {
        apiTraceTargets.push(/^https:\/\/api\.nexus\.dynaminds\.pl(?:\/|$)/)
      }
    } catch { /* Errors still report; tracing waits for a compatible API. */ }
    finally { probing = undefined }
  })()
  return probing
}
