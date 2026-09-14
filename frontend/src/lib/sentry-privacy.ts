import type { Event, Stacktrace } from '@sentry/nextjs'

const safeTags = new Set(['api_failure', 'api_status', 'api_method', 'api_path', 'operation', 'failure_kind', 'terminal', 'sampling_policy', 'integration', 'job'])
const safeIdentifier = /^[a-zA-Z0-9_./:{} -]{1,180}$/

function scrubStack(stack?: Stacktrace): void {
  for (const frame of stack?.frames ?? []) {
    delete frame.vars
    delete frame.pre_context
    delete frame.context_line
    delete frame.post_context
  }
}

/** Free-form error/request data is private. Preserve source locations and trace IDs. */
export function scrubSentryEvent<T extends Event>(event: T): T {
  delete event.user
  delete event.request
  delete event.extra
  if ('logentry' in event) delete event.logentry
  if ('message' in event) event.message = 'Application failure (private details omitted)'
  event.tags = Object.fromEntries(Object.entries(event.tags ?? {}).filter(([key, value]) => safeTags.has(key) && safeIdentifier.test(String(value))))
  const trace = event.contexts?.trace
  const correlation = event.contexts?.correlation ?? {}
  event.contexts = {
    ...(trace ? { trace: { trace_id: trace.trace_id, span_id: trace.span_id, parent_span_id: trace.parent_span_id, op: trace.op, status: trace.status, origin: trace.origin } } : {}),
    correlation: Object.fromEntries(Object.entries(correlation).filter(([key, value]) => ['request_id', 'operation_id'].includes(key) && /^[a-f0-9-]{16,36}$/i.test(String(value)))),
  }
  for (const value of ('exception' in event ? event.exception?.values : undefined) ?? []) {
    value.value = `${value.type ?? 'Error'} (private details omitted)`
    if (value.mechanism) {
      delete value.mechanism.data
    }
    scrubStack(value.stacktrace)
  }
  if ('threads' in event) {
    for (const thread of event.threads?.values ?? []) scrubStack(thread.stacktrace)
  }
  event.breadcrumbs = event.breadcrumbs?.map(({ timestamp, category, level, type }) => ({ timestamp, category, level, type }))
  if ('spans' in event) {
    for (const span of event.spans ?? []) {
      span.data = {}
      delete span.description
    }
  }
  if (event.transaction_info?.source === 'url') event.transaction = 'unmatched-route'
  return event
}

const seen = new Set<string>()
/** First occurrence per release/session survives; reloads cannot reset the limit. */
export function firstInSession(signature: string): boolean {
  const key = `nexus:sentry:${process.env.NEXT_PUBLIC_GIT_SHA ?? 'development'}:${signature}`
  try {
    if (sessionStorage.getItem(key)) return false
    sessionStorage.setItem(key, '1')
  } catch { /* Storage can be disabled; retain in-memory deduplication. */ }
  if (seen.has(key)) return false
  seen.add(key)
  return true
}
