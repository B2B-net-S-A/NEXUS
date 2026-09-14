import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { focusManager, QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import { AxiosError } from 'axios';
import { QueryProvider } from '@/components/QueryProvider';
import { DeferUntilVisible } from '@/components/v2/DeferUntilVisible';
import { api } from '@/lib/api';
import { useNotifications } from '@/hooks/useNotifications';
import { NOTIFICATIONS_FALLBACK_POLL_MS, WS_BACKED_SAFETY_POLL_MS } from '@/lib/polling';
import * as Sentry from '@sentry/nextjs';

vi.mock('@/store/auth', () => ({ useAuthStore: () => ({ token: 'local-audit-token' }) }));
vi.mock('@sentry/nextjs', () => ({ init: vi.fn(), replayIntegration: vi.fn(), captureException: vi.fn() }));

const clients: QueryClient[] = [];
beforeEach(() => { vi.useFakeTimers(); vi.spyOn(Math, 'random').mockReturnValue(0); });
afterEach(() => { cleanup(); clients.forEach(c => c.clear()); clients.length = 0; vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); focusManager.setFocused(undefined); });

function providerClient() {
  let client!: QueryClient;
  function Probe() { client = useQueryClient(); return null; }
  render(<QueryProvider><Probe /></QueryProvider>);
  clients.push(client);
  return client;
}

for (const override of [undefined, 1]) {
  it(`actual QueryProvider plus Axios produces ${override === 1 ? 6 : 3} attempts for retry override ${override}`, async () => {
    const client = providerClient();
    let attempts = 0;
    const failed = client.fetchQuery({
      queryKey: ['local-audit', override],
      ...(override === undefined ? {} : { retry: override }),
      queryFn: () => api.get('/local-audit-never-sent', { adapter: async (config) => {
        attempts++;
        throw new AxiosError('503', 'ERR_BAD_RESPONSE', config, {}, { config, status: 503, statusText: '', data: {}, headers: {} });
      } }),
    }).catch(() => undefined);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    await failed;
    expect(attempts).toBe(override === 1 ? 6 : 3);
  });
}

it('Retry-After HTTP-date is ignored and retries before the specified future time', async () => {
  const times: number[] = [];
  const start = Date.now();
  const failed = api.get('/local-audit-never-sent', { adapter: async config => {
    times.push(Date.now() - start);
    throw new AxiosError('503', 'ERR_BAD_RESPONSE', config, {}, { config, status: 503, statusText: '', data: {}, headers: { 'retry-after': new Date(start + 60_000).toUTCString() } });
  } }).catch(() => undefined);
  await vi.advanceTimersByTimeAsync(10_000);
  await failed;
  expect(times).toEqual([0, 1500, 4500]);
});

it('actual WS fallback refetches an active notifications query while document is hidden', async () => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
  focusManager.setFocused(false);
  vi.stubGlobal('WebSocket', class { constructor() { throw new Error('offline synthetic'); } });
  const queryFn = vi.fn(async () => ({ items: [] }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  function Probe() {
    useNotifications();
    useQuery({ queryKey: ['notifications', 'audit'], queryFn });
    return null;
  }
  render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(queryFn).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(queryFn).toHaveBeenCalledTimes(2);
});

it('DeferUntilVisible defers first mount and intentionally remains mounted after leaving viewport', async () => {
  let callback!: (entries: { isIntersecting: boolean }[]) => void;
  vi.stubGlobal('IntersectionObserver', class {
    constructor(fn: typeof callback) { callback = fn; }
    observe() {}
    disconnect() {}
  });
  const Child = vi.fn(() => <div data-testid="content">Ready</div>);
  const view = render(<DeferUntilVisible><Child /></DeferUntilVisible>);
  expect(Child).not.toHaveBeenCalled();
  await act(async () => callback([{ isIntersecting: true }]));
  expect(view.getByTestId('content')).toBeTruthy();
  await act(async () => callback([{ isIntersecting: false }]));
  expect(view.getByTestId('content')).toBeTruthy();
});

it('a short WS outage and reconnect does not reconcile missed notifications within the next minute', async () => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
  focusManager.setFocused(true);
  const sockets: any[] = [];
  vi.stubGlobal('WebSocket', class {
    onopen?: () => void;
    onclose?: () => void;
    constructor() { sockets.push(this); }
    send() {}
    close() {}
  });
  const queryFn = vi.fn(async () => ({ items: [] }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  function Probe() {
    const { wsConnected } = useNotifications();
    useQuery({ queryKey: ['notifications', 'audit-reconnect'], queryFn,
      refetchInterval: wsConnected ? WS_BACKED_SAFETY_POLL_MS : NOTIFICATIONS_FALLBACK_POLL_MS });
    return null;
  }
  render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>);
  await act(async () => { sockets[0].onopen(); await vi.advanceTimersByTimeAsync(1_000); });
  expect(queryFn).toHaveBeenCalledTimes(1);
  await act(async () => { sockets[0].onclose(); await vi.advanceTimersByTimeAsync(1_000); });
  await act(async () => { sockets[1].onopen(); });
  await act(async () => { await vi.advanceTimersByTimeAsync(61_000); });
  expect(queryFn).toHaveBeenCalledTimes(1);
});

it('Sentry now accepts sampled ERR_NETWORK but still discards timeouts and chunk failures', async () => {
  vi.stubEnv('NEXT_PUBLIC_SENTRY_DSN', 'https://example.invalid');
  await import('/tmp/nexus-performance-reaudit-2026-09-14/frontend/sentry.client.config.ts');
  const cfg = vi.mocked(Sentry.init).mock.calls.at(-1)![0] as any;
  expect(cfg.beforeSend({}, { originalException: { code: 'ERR_NETWORK' } })).toMatchObject({ fingerprint: ['network-error'] });
  expect(cfg.beforeSend({}, { originalException: { code: 'ECONNABORTED' } })).toBeNull();
  expect(cfg.ignoreErrors.some((p: unknown) => p instanceof RegExp && p.test('ChunkLoadError'))).toBe(true);
});

it('handled useQuery network failure reaches error state without Sentry capture or an unhandled rejection', async () => {
  const unhandled = vi.fn();
  window.addEventListener('unhandledrejection', unhandled);
  vi.mocked(Sentry.captureException).mockClear();
  let state = '';
  function Probe() {
    const query = useQuery({ queryKey: ['handled-network-failure'], queryFn: () => api.get('/local-audit-never-sent', { adapter: async config => { throw new AxiosError('Network Error', 'ERR_NETWORK', config, {}); } }) });
    state = query.status;
    return <div>{state}</div>;
  }
  render(<QueryProvider><Probe /></QueryProvider>);
  await act(async () => { await vi.advanceTimersByTimeAsync(6_000); });
  expect(state).toBe('error');
  expect(Sentry.captureException).not.toHaveBeenCalled();
  expect(unhandled).not.toHaveBeenCalled();
  window.removeEventListener('unhandledrejection', unhandled);
});
