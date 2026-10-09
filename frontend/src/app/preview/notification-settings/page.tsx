"use client";

/**
 * Harness ekranu Ustawienia → „Powiadomienia” — prawdziwy
 * `NotificationsSettings` na zasianym cache react-query, ZERO zapytań
 * (strażnik: `harness-seeds.test.ts`); sieć odcina interceptor, zapisy także
 * layout `/preview`. Zapis w podglądzie kończy się komunikatem o błędzie —
 * to zamierzone.
 *
 * Warianty:
 * - bez parametrów — administrator, zakładka „Kto co dostaje”;
 * - `?tab=moje|role|maile|etapy` — zakładka startowa;
 * - `?as=recruiter` — konto bez uprawnień administratora: samo „Moje”,
 *   bez paska zakładek, z jedną kategorią wyłączoną dla roli.
 *
 * Osoby, liczby i adresy są zmyślone.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { NOTIFICATION_DELIVERY_QUERY_KEY } from "@/components/settings/NotificationDeliverySettings";
import { NotificationsSettings } from "@/components/settings/NotificationsSettings";
import { api } from "@/lib/api";
import type {
  NotificationDeliveryOverview,
  NotificationDeliveryType,
} from "@/lib/api/notificationDelivery";
import {
  notificationPreferencesQueryKey,
  type NotificationPreferences,
} from "@/lib/api/notificationPreferences";
import { notificationRolesQueryKey } from "@/lib/api/notificationRoles";
import {
  USER_PREFERENCES_QUERY_KEY,
  type UserPreferences,
} from "@/lib/api/userPreferences";
import type {
  NotificationRoleCategory,
  NotificationRoleGroup,
  NotificationRolesView,
} from "@/lib/notification-role-matrix";
import {
  isNotificationsSubTab,
  type NotificationsSubTab,
} from "@/lib/settings-notifications-subtab";
import { useAuthStore } from "@/store/auth";

type Persona = "admin" | "recruiter";

const ROLES: NotificationRolesView["roles"] = [
  { key: "admin", label: "Admin", accounts: 3 },
  { key: "head_of_recruitment", label: "Head of Recruitment", accounts: 1 },
  { key: "delivery_lead", label: "Delivery Lead", accounts: 5 },
  { key: "recruiter", label: "Rekruter", accounts: 9 },
  { key: "talent_community_manager", label: "Talent Community Manager", accounts: 4 },
  { key: "finance", label: "Finanse", accounts: 2 },
];

const ROLE_KEYS = ROLES.map((role) => role.key);

/** Grupa z liczbami w kolejności kolumn; `mutedFor` = role z wyłączoną grupą. */
function group(
  key: string,
  label: string,
  counts: number[],
  mutedFor: string[] = [],
): NotificationRoleGroup {
  return {
    key,
    label,
    muted: Object.fromEntries(ROLE_KEYS.map((role) => [role, mutedFor.includes(role)])),
    muted_at: Object.fromEntries(
      ROLE_KEYS.map((role) => [
        role,
        mutedFor.includes(role) ? "2026-10-06T09:15:00+00:00" : null,
      ]),
    ),
    received_30d: Object.fromEntries(ROLE_KEYS.map((role, index) => [role, counts[index] ?? 0])),
  };
}

function category(
  key: string,
  label: string,
  description: string,
  groups: NotificationRoleGroup[],
  mandatory = false,
): NotificationRoleCategory {
  return { key, label, description, mandatory, groups };
}

const ROLE_VIEW: NotificationRolesView = {
  revision: 4,
  updated_at: "2026-10-06T09:15:00+00:00",
  updated_by_name: "Aniela Administrująca",
  window_days: 30,
  roles: ROLES,
  categories: [
    category(
      "mentions",
      "Wzmianki (@) i imienne zadania",
      "Ktoś oznaczył Cię w notatce albo czeka na Twój ruch.",
      [group("mentions", "Wzmianki (@) i imienne zadania", [2, 1, 14, 31, 9, 0])],
      true,
    ),
    category(
      "interviews",
      "Rozmowy u klienta",
      "Terminy od klienta, przypomnienie i telefon po rozmowie.",
      [group("interviews", "Rozmowy u klienta", [40, 3, 88, 6, 11, 0])],
      true,
    ),
    category("pipeline", "Ruchy w rekrutacjach", "Kandydat zmienił etap w Twojej rekrutacji.", [
      group("pipeline", "Ruchy w rekrutacjach", [61, 10, 42, 120, 27, 0]),
    ]),
    category("reminders", "Zaległości i przypomnienia", "Kandydat stoi na etapie albo coś czeka na ruch.", [
      group("stage_stale_6h", "Kandydat stoi na etapie 6 h", [910, 880, 190, 0, 0, 0], ["admin"]),
      group("stage_stuck_7d", "Kandydat stoi na etapie 7 dni", [0, 0, 150, 96, 0, 0]),
      group("board_tasks_digest", "Skrót „Czeka na Ciebie” w dzwonku", [21, 6, 25, 0, 0, 0]),
      group("next_step_hint", "Podpowiedź następnego kroku", [18, 0, 7, 22, 5, 0]),
      group("request_review", "Request do przejrzenia", [0, 0, 4, 0, 0, 0]),
    ]),
    category("deadlines", "Terminy rekrutacji", "Zbliża się albo minął termin rekrutacji.", [
      group("deadlines", "Terminy rekrutacji", [0, 0, 13, 18, 3, 0]),
    ]),
    category("candidates", "Nowi i pasujący kandydaci", "Nowe zgłoszenia i propozycje z bazy.", [
      group("candidates", "Nowi i pasujący kandydaci", [70, 4, 210, 390, 160, 0]),
    ]),
    category("contracts", "Kontrakty, zamówienia i podpisy", "Koniec zamówienia, umowy i prośby o podpis.", [
      group("order_ending", "Koniec zamówienia za 30 / 14 / 7 dni", [640, 0, 230, 0, 0, 0]),
      group("contract_ending", "Koniec umowy", [84, 0, 26, 0, 0, 0]),
      group("contract_activated", "Umowa aktywowana", [9, 0, 2, 0, 0, 0]),
      group("framework_ending", "Umowa ramowa wygasa", [5, 0, 1, 0, 0, 0]),
      group("order_missing", "Brak kolejnego zamówienia", [0, 0, 29, 0, 0, 0]),
      group("hired_without_order", "Zatrudniony bez zamówienia", [0, 0, 0, 0, 0, 17]),
    ]),
    category("kpi", "KPI i coaching", "Pochwały i przypomnienia o celach.", [
      group("kpi", "KPI i coaching", [8, 8, 0, 30, 0, 0], ["finance"]),
    ]),
    category(
      "system",
      "Konto i system (alarmy AI, awarie)",
      "Alarmy wydatków AI i awarie automatów.",
      [group("system", "Konto i system (alarmy AI, awarie)", [120, 0, 0, 0, 0, 0])],
      true,
    ),
  ],
};

function preferences(persona: Persona): NotificationPreferences {
  return {
    categories: [
      {
        key: "mentions",
        label: "Wzmianki (@) i imienne zadania",
        description: "Ktoś oznaczył Cię w notatce albo czeka na Twój ruch.",
        mandatory: true,
        muted: false,
        role_muted: false,
        received_30d: 6,
      },
      {
        key: "pipeline",
        label: "Ruchy w rekrutacjach",
        description: "Kandydat zmienił etap w Twojej rekrutacji.",
        mandatory: false,
        muted: false,
        role_muted: false,
        received_30d: 41,
      },
      {
        key: "reminders",
        label: "Zaległości i przypomnienia",
        description: "Kandydat stoi na etapie albo coś czeka na ruch.",
        mandatory: false,
        muted: true,
        role_muted: false,
        received_30d: 112,
      },
      {
        key: "kpi",
        label: "KPI i coaching",
        description: "Pochwały i przypomnienia o celach.",
        mandatory: false,
        muted: false,
        // Rekruter z podglądu ma tę kategorię wyłączoną dla roli.
        role_muted: persona === "recruiter",
        received_30d: 3,
      },
    ],
  };
}

const USER_PREFERENCES: UserPreferences = {
  kpi_coach_enabled: true,
  daily_digest_email_enabled: true,
  daily_digest_email_available: true,
};

function deliveryType(
  over: Pick<NotificationDeliveryType, "id" | "label" | "module" | "trigger" | "recipient_rule"> &
    Partial<NotificationDeliveryType>,
): NotificationDeliveryType {
  return {
    email_enabled: true,
    effective_enabled: true,
    send_not_before: null,
    channels: ["in_app", "email"],
    sender: "powiadomienia@example.test",
    editable: true,
    provider_kind: "graph_app",
    provider_status: "healthy",
    ...over,
  };
}

const DELIVERY: NotificationDeliveryOverview = {
  enabled: true,
  updated_at: "2026-10-07T08:21:00+00:00",
  updated_by: 1,
  updated_by_name: "Aniela Administrująca",
  daily_digest_recipients: 21,
  send_not_before: "2026-10-01T06:00:00+00:00",
  provider: {
    kind: "graph_app",
    sender: "powiadomienia@example.test",
    configured: true,
    observed_status: "healthy",
    last_success_at: "2026-10-09T06:02:00+00:00",
    last_failure_at: null,
    failure_code: null,
    cooldown_until: null,
  },
  backlog: {
    scope: "chat_unread",
    pending_retry: 0,
    ready_upper_bound: 0,
    uncertain: 0,
    legacy_suppressed: 12,
  },
  types: [
    deliveryType({
      id: "daily_digest",
      label: "Poranny skrót „Twój dzień w NEXUSIE”",
      module: "Pulpit",
      trigger: "Dzień roboczy od 8:00 — to, co czeka na osobę w panelu „Czeka na Ciebie”.",
      recipient_rule: "Rekruterzy, TCM, Delivery Leadzi, Head of Recruitment i Finanse.",
      channels: ["email"],
    }),
    deliveryType({
      id: "delivery_alert",
      label: "Alerty klientów i umów",
      module: "Delivery",
      trigger: "Kończy się zamówienie albo umowa klienta.",
      recipient_rule: "Delivery Leadzi przypisani do klienta.",
      channels: ["client_panel", "email"],
    }),
    deliveryType({
      id: "mentions",
      label: "Wzmianka",
      module: "Rekrutacja",
      trigger: "Ktoś oznaczył osobę w notatce albo na czacie.",
      recipient_rule: "Oznaczona osoba.",
      email_enabled: false,
      effective_enabled: false,
    }),
    deliveryType({
      id: "password_reset",
      label: "Reset hasła",
      module: "Konto",
      trigger: "Użytkownik prosi o reset hasła.",
      recipient_rule: "Właściciel konta.",
      channels: ["email"],
      editable: false,
    }),
  ],
  excluded_channels: [
    {
      id: "manual_m365",
      label: "Maile wysyłane ręcznie",
      description: "Wysyłka z własnej skrzynki wymaga osobnej akcji użytkownika.",
    },
  ],
};

// Zasiew „świeży” na dobę naprzód — powrót do karty nie próbuje odświeżać.
const FRESH = { updatedAt: Date.now() + 24 * 60 * 60 * 1000 };

function seededClient(persona: Persona): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        retryOnMount: false,
        refetchOnWindowFocus: false,
        staleTime: Infinity,
      },
      mutations: { retry: false },
    },
  });
  qc.setQueryData(notificationPreferencesQueryKey, preferences(persona), FRESH);
  qc.setQueryData(USER_PREFERENCES_QUERY_KEY, USER_PREFERENCES, FRESH);
  qc.setQueryData(notificationRolesQueryKey, ROLE_VIEW, FRESH);
  qc.setQueryData(NOTIFICATION_DELIVERY_QUERY_KEY, DELIVERY, FRESH);
  return qc;
}

/** Bezpiecznik: nawet „Zapisz zmiany” nie wyśle żądania. */
function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(new Error("Harness /preview/notification-settings nie wysyła zapytań."), {
          isAxiosError: true,
          code: "ERR_PREVIEW_OFFLINE",
        }),
      ),
    ),
  );
  useEffect(() => () => api.interceptors.request.eject(interceptorId), [interceptorId]);
}

function NotificationSettingsPreview() {
  useNetworkBlocked();
  const params = useSearchParams();
  const persona: Persona = params?.get("as") === "recruiter" ? "recruiter" : "admin";
  const requestedTab = params?.get("tab");
  const defaultTab: NotificationsSubTab = isNotificationsSubTab(requestedTab)
    ? requestedTab
    : persona === "admin"
      ? "role"
      : "moje";
  const [qc] = useState(() => seededClient(persona));
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Ekran czyta konto z produkcyjnego store'a (zakładki zależą od roli).
    useAuthStore.setState({
      user: {
        id: persona === "admin" ? 1 : 9,
        email: persona === "admin" ? "konto1@example.com" : "konto9@example.com",
        name: persona === "admin" ? "Aniela Administrująca" : "Daria Testowa",
        role: persona,
        roles: [persona],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access:
          persona === "admin"
            ? { system_admin: "write", pipeline: "write", sourcing: "write" }
            : { pipeline: "write", sourcing: "write" },
      },
      hydrated: true,
    });
    setReady(true);
  }, [persona]);

  if (!ready) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <QueryClientProvider client={qc}>
      <main className="mx-auto max-w-7xl space-y-6 bg-background p-4 sm:p-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Powiadomienia</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Która rola dostaje które powiadomienia i które maile wychodzą do całej firmy.
          </p>
        </div>
        <NotificationsSettings defaultTab={defaultTab} />
      </main>
    </QueryClientProvider>
  );
}

export default function NotificationSettingsPreviewPage() {
  return (
    <Suspense fallback={null}>
      <NotificationSettingsPreview />
    </Suspense>
  );
}
