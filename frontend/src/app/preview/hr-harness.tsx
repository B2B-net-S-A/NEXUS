"use client";

/**
 * Wspólne części harnessów „Ludzie w NEXUSIE” (`/preview/hr-*`, 17.10.2026).
 *
 * Każdy harness HR renderuje PRAWDZIWY ekran z gałęzi na zasianym cache
 * react-query i nie wysyła ani jednego żądania:
 * - `harnessQueryClient()` — dane świeże na zawsze, bez ponowień i bez
 *   odświeżania przy montowaniu i powrocie do karty (hooki HR mają własne
 *   `staleTime`, więc samo `staleTime: Infinity` w domyśle nie wystarcza);
 * - `useHrHarness()` — w jednym efekcie: interceptor odcinający sieć (każda
 *   próba kończy się błędem bez wysyłki), konto oglądającego w `useAuthStore`
 *   i dane harnessu zbudowane z parametrów adresu (`?state=`, `?as=`);
 * - `HrHarnessShell` — pasek stanów nad ekranem, `ToastProvider`
 *   i `QueryClientProvider`, padding powłoki aplikacji (`p-4 md:p-6`).
 *
 * Zapisy blokuje dodatkowo layout `/preview` (`preview-network-guard.ts`).
 * Dane osób i klientów są zmyślone (`hr-fixtures.ts`).
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { api } from "@/lib/api";
import {
  PERMISSION_KEYS,
  defaultPermissionsForRoles,
  type Permission,
} from "@/lib/permissions";
import { useAuthStore, type UserRole } from "@/store/auth";

export const HR_HARNESS_OFFLINE = "preview: sieć wyłączona w harnessie „Ludzi”";

export function harnessQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        retry: false,
        retryOnMount: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
      mutations: { retry: false },
    },
  });
}

/** Odcina sieć warstwy `api` — zwraca funkcję zdejmującą blokadę. */
export function blockHarnessNetwork(): () => void {
  const id = api.interceptors.request.use((config) =>
    Promise.reject(new AxiosError(HR_HARNESS_OFFLINE, "ECONNABORTED", config)),
  );
  return () => api.interceptors.request.eject(id);
}

export interface HarnessUser {
  id: number;
  name: string;
  email: string;
  role: UserRole;
  roles?: UserRole[];
  /** Uprawnienia ponad domyślne dla ról (np. „Sprzęt” dla recepcji). */
  grants?: Permission[];
}

/** Komplet uprawnień konta jak w `effective_action_access` z `/api/auth/me`. */
function actionAccess(user: HarnessUser): Partial<Record<Permission, "none" | "manage">> {
  const held = defaultPermissionsForRoles([user.role, ...(user.roles ?? [])]);
  for (const grant of user.grants ?? []) held.add(grant);
  return Object.fromEntries(
    PERMISSION_KEYS.map((key) => [key, held.has(key) ? "manage" : "none"]),
  );
}

export function setHarnessUser(user: HarnessUser): void {
  useAuthStore.setState({
    user: {
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
      roles: user.roles ?? [user.role],
      profile_completed: true,
      profile_completed_at: null,
      force_password_change: false,
      force_password_change_at: null,
      effective_action_access: actionAccess(user),
    },
    realUser: null,
    hydrated: true,
  });
}

export interface HrHarnessSetup<T> {
  user: HarnessUser;
  client: QueryClient;
  value: T;
}

export interface HrHarnessReady<T> {
  client: QueryClient;
  value: T;
}

/**
 * Przygotowanie harnessu po stronie przeglądarki: blokada sieci, konto
 * i zasiany klient. Do pierwszego efektu zwraca `null` (strona pokazuje
 * „Ładowanie…”), więc SSR nie dotyka `window` ani store'a.
 */
export function useHrHarness<T>(
  prepare: (params: URLSearchParams) => HrHarnessSetup<T>,
): HrHarnessReady<T> | null {
  const [ready, setReady] = useState<HrHarnessReady<T> | null>(null);
  const prepareRef = useRef(prepare);
  useEffect(() => {
    const release = blockHarnessNetwork();
    const { user, client, value } = prepareRef.current(
      new URLSearchParams(window.location.search),
    );
    setHarnessUser(user);
    setReady({ client, value });
    return release;
  }, []);
  return ready;
}

export interface HarnessStateLink {
  key: string;
  label: string;
  /** Pełny adres stanu, gdy ekran sam czyta inne parametry (np. `?tab=month`). */
  href?: string;
}

/** Wartość parametru adresu, o ile należy do znanych stanów. */
export function pickState<K extends string>(
  raw: string | null,
  known: readonly K[],
  fallback: K,
): K {
  return raw !== null && (known as readonly string[]).includes(raw) ? (raw as K) : fallback;
}

interface HrHarnessShellProps {
  client: QueryClient;
  /** Nazwa ekranu w pasku harnessu. */
  title: string;
  /** Jedno zdanie: kto ogląda i co pokazuje stan. */
  note?: string;
  states?: readonly HarnessStateLink[];
  current?: string;
  /** Parametr adresu przełączający stany (domyślnie `state`). */
  param?: string;
  children: ReactNode;
}

export function HrHarnessShell({
  client,
  title,
  note,
  states,
  current,
  param = "state",
  children,
}: HrHarnessShellProps) {
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <div className="min-h-dvh bg-background">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border px-4 py-2 text-sm md:px-6">
            <h1 className="text-sm font-semibold text-foreground">Podgląd: {title}</h1>
            {states?.map((state) => (
              <a
                key={state.key}
                href={state.href ?? `?${param}=${state.key}`}
                aria-current={current === state.key ? "page" : undefined}
                className={current === state.key ? "font-semibold text-primary" : "text-foreground hover:underline"}
              >
                {state.label}
              </a>
            ))}
            {note ? <span className="w-full text-xs text-muted-foreground">{note}</span> : null}
          </div>
          {/* Padding powłoki (`<main>` ma `p-4 md:p-6`) — ekran nie dokłada własnego. */}
          <div className="p-4 md:p-6">{children}</div>
        </div>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export function HrHarnessLoading() {
  return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
}
