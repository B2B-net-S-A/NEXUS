"use client";

// Harness ekranu Ustawienia → „Klucze API” (14.10.2026). Renderuje PRAWDZIWY
// `ApiKeysSettingsView` na danych fikcyjnych trzymanych w pamięci strony —
// zero zapytań (komponent nie ma react-query, sieć i tak odcina layout
// `/preview`). Zapisy działają na kopii w pamięci, więc formularze, wydanie
// klucza, odwołanie i usuwanie da się przeklikać.
//
// `?state=` (domyślnie lista):
// - `revealed` — klucz pokazany raz zaraz po wydaniu;
// - `create` — otwarty formularz nowego konta;
// - `empty` — brak kont; `disabled` — klucze wyłączone na serwerze;
// - `loading`, `error` — stany ładowania i awarii pierwszego zapytania.
//
// Daty liczą się od chwili otwarcia, żeby ostrzeżenia o wygaśnięciu były
// zawsze widoczne. Klucze, konta i adresy są zmyślone.

import { useEffect, useMemo, useState } from "react";

import { ApiKeysSettingsView } from "@/components/settings/api-keys/ApiKeysSettingsView";
import type {
  AccountWritesState,
  ApiKeysActions,
  ApiKeysLoad,
  RevealedApiKey,
} from "@/components/settings/api-keys/types";
import type {
  ScopeInfoDto,
  ServiceAccountConfigDto,
  ServiceAccountDto,
  ServiceAccountKeyDto,
  ServiceAccountWriteDto,
} from "@/lib/api";

type State = "list" | "revealed" | "create" | "empty" | "disabled" | "loading" | "error";
const STATES: readonly State[] = ["list", "revealed", "create", "empty", "disabled", "loading", "error"];

const DAY = 24 * 60 * 60 * 1000;
const FAKE_KEY = "nxs_v2_000000000000000000000009_PODGLAD-to-nie-jest-prawdziwy-klucz";

const SCOPES: ScopeInfoDto[] = [
  { value: "traffit:sync", label: "Uruchamianie synchronizacji Traffit" },
  { value: "traffit:read", label: "Odczyt statusu synchronizacji Traffit" },
  { value: "ops:snapshot", label: "Odczyt migawki operacyjnej (/api/admin/snapshot)" },
  { value: "contractors:read", label: "Eksport kontraktorów dla COMPASSA (bez kwot)" },
  { value: "clients:read", label: "Klienci: odczyt (nazwa, NIP, Delivery Lead)" },
  { value: "contracts:read", label: "Kontrakty: odczyt (osoba, klient, okres, status)" },
  { value: "orders:read", label: "Zamówienia: odczyt (okresy, linie, PDF-y)" },
  { value: "md:read", label: "Zużycie MD: odczyt (salda, importy)" },
  { value: "md:write", label: "Zużycie MD: zapis (import, przypisanie wiersza, korekta miesiąca)" },
  { value: "finance:read", label: "Finanse: odczyt (zmiany w zamówieniach, PDF-y, wyniki)" },
  { value: "finance:write", label: "Finanse: zapis („Zrobione”, import wyników)" },
  { value: "invoices:read", label: "Faktury: odczyt (rejestr, DSO)" },
  { value: "invoices:write", label: "Faktury: zapis (wystawienie, zmiana, anulowanie)" },
  { value: "amounts:read", label: "Stawki i kwoty: podgląd w zamówieniach i kontraktach" },
];

const CONFIG: ServiceAccountConfigDto = {
  enabled: true,
  default_ttl_days: 90,
  max_ttl_days: 365,
  header: "X-API-Key",
};

const iso = (now: Date, offsetDays: number) => new Date(now.getTime() + offsetDays * DAY).toISOString();

function key(now: Date, n: number, over: Partial<ServiceAccountKeyDto>): ServiceAccountKeyDto {
  return {
    key_id: `v2$00000000000000000000000${n}`,
    label: `Klucz ${n}`,
    created_at: iso(now, -30),
    created_by: 1,
    expires_at: iso(now, 60),
    revoked_at: null,
    revoked_by: null,
    revoke_reason: null,
    last_used_at: null,
    last_used_ip: null,
    ...over,
  };
}

function seedAccounts(now: Date): ServiceAccountDto[] {
  return [
    {
      id: 1,
      slug: "rozliczenia-n8n",
      name: "Automatyzacja rozliczeń (n8n)",
      description: "Import zużycia MD z arkuszy klientów i oznaczanie zmian w Finansach.",
      scopes: [
        "clients:read",
        "contracts:read",
        "orders:read",
        "md:write",
        "finance:write",
        "invoices:read",
        "amounts:read",
      ],
      is_active: true,
      created_by: 1,
      created_at: iso(now, -120),
      updated_at: iso(now, -2),
      keys: [
        key(now, 1, {
          label: "n8n — produkcja",
          created_at: iso(now, -40),
          expires_at: iso(now, 50),
          last_used_at: new Date(now.getTime() - 12 * 60 * 1000).toISOString(),
          last_used_ip: "192.0.2.10",
        }),
        key(now, 2, {
          label: "n8n — wymiana w toku",
          created_at: iso(now, -85),
          expires_at: iso(now, 5),
          last_used_at: iso(now, -1),
          last_used_ip: "192.0.2.10",
        }),
        key(now, 3, {
          label: "Skrypt testowy",
          created_at: iso(now, -100),
          expires_at: iso(now, -10),
          revoked_at: iso(now, -20),
          revoked_by: 1,
          revoke_reason: "Koniec testów",
        }),
      ],
    },
    {
      id: 2,
      slug: "raport-power-automate",
      name: "Raport miesięczny (Power Automate)",
      description: null,
      scopes: ["clients:read", "orders:read", "md:read", "finance:read"],
      is_active: true,
      created_by: 1,
      created_at: iso(now, -200),
      updated_at: iso(now, -200),
      keys: [
        key(now, 4, {
          label: "Power Automate",
          created_at: iso(now, -95),
          expires_at: iso(now, -3),
          last_used_at: iso(now, -4),
          last_used_ip: "198.51.100.7",
        }),
      ],
    },
    {
      id: 3,
      slug: "kontraktorzy-przyklad",
      name: "Eksport kontraktorów (przykład)",
      description: "Wyłączone na czas zmiany systemu po drugiej stronie.",
      scopes: ["contractors:read", "ops:snapshot", "legacy:read"],
      is_active: false,
      created_by: 1,
      created_at: iso(now, -300),
      updated_at: iso(now, -7),
      keys: [],
    },
  ];
}

function seedWrites(now: Date): ServiceAccountWriteDto[] {
  const at = (minutes: number) => new Date(now.getTime() - minutes * 60 * 1000).toISOString();
  return [
    {
      id: 503,
      key_id: "v2$000000000000000000000001",
      method: "POST",
      route: "/api/integrations/v1/md/imports",
      state: "done",
      status_code: 201,
      created_at: at(12),
      completed_at: at(12),
    },
    {
      id: 502,
      key_id: "v2$000000000000000000000001",
      method: "POST",
      route: "/api/integrations/v1/finance/order-changes/checks",
      state: "done",
      status_code: 200,
      created_at: at(95),
      completed_at: at(95),
    },
    {
      id: 501,
      key_id: "v2$000000000000000000000002",
      method: "POST",
      route: "/api/integrations/v1/md/imports",
      state: "pending",
      status_code: null,
      created_at: at(60 * 26),
      completed_at: null,
    },
  ];
}

const pause = () => new Promise((resolve) => setTimeout(resolve, 300));

function readState(): State {
  const raw = new URLSearchParams(window.location.search).get("state");
  return STATES.find((s) => s === raw) ?? "list";
}

export default function ApiKeysHarness() {
  const [state, setState] = useState<State | null>(null);
  const now = useMemo(() => new Date(), []);
  const [accounts, setAccounts] = useState<ServiceAccountDto[]>([]);
  const [writes, setWrites] = useState<Record<number, AccountWritesState>>({});

  useEffect(() => {
    const next = readState();
    setState(next);
    setAccounts(next === "empty" ? [] : seedAccounts(now));
  }, [now]);

  const actions = useMemo<ApiKeysActions>(
    () => ({
      createAccount: async (payload) => {
        await pause();
        setAccounts((prev) => [
          {
            id: Math.max(0, ...prev.map((a) => a.id)) + 1,
            slug: payload.slug,
            name: payload.name,
            description: payload.description ?? null,
            scopes: payload.scopes,
            is_active: true,
            created_by: 1,
            created_at: now.toISOString(),
            updated_at: now.toISOString(),
            keys: [],
          },
          ...prev,
        ]);
      },
      updateAccount: async (id, payload) => {
        await pause();
        setAccounts((prev) =>
          prev.map((a) =>
            a.id === id
              ? {
                  ...a,
                  ...(payload.name !== undefined ? { name: payload.name } : {}),
                  ...(payload.description !== undefined ? { description: payload.description } : {}),
                  ...(payload.scopes !== undefined ? { scopes: payload.scopes } : {}),
                  ...(payload.is_active !== undefined ? { is_active: payload.is_active } : {}),
                }
              : a,
          ),
        );
      },
      deleteAccount: async (id) => {
        await pause();
        setAccounts((prev) => prev.filter((a) => a.id !== id));
      },
      issueKey: async (id, payload) => {
        await pause();
        const issued = key(now, 9, {
          label: payload.label,
          created_at: now.toISOString(),
          expires_at: iso(now, payload.expires_in_days ?? CONFIG.default_ttl_days),
        });
        setAccounts((prev) => prev.map((a) => (a.id === id ? { ...a, keys: [issued, ...a.keys] } : a)));
        return { key: issued, api_key: FAKE_KEY };
      },
      revokeKey: async (id, keyId, reason) => {
        await pause();
        setAccounts((prev) =>
          prev.map((a) =>
            a.id === id
              ? {
                  ...a,
                  keys: a.keys.map((k) =>
                    k.key_id === keyId
                      ? { ...k, revoked_at: now.toISOString(), revoked_by: 1, revoke_reason: reason }
                      : k,
                  ),
                }
              : a,
          ),
        );
      },
    }),
    [now],
  );

  if (!state) return null;

  const load: ApiKeysLoad =
    state === "loading"
      ? { status: "loading" }
      : state === "error"
        ? {
            status: "error",
            message: "Nie udało się pobrać kont serwisowych. Spróbuj ponownie.",
            onRetry: () => undefined,
          }
        : {
            status: "success",
            accounts,
            scopes: SCOPES,
            config: state === "disabled" ? { ...CONFIG, enabled: false } : CONFIG,
          };

  const revealed: RevealedApiKey | null =
    state === "revealed" ? { accountId: 1, keyLabel: "n8n — produkcja", apiKey: FAKE_KEY } : null;

  return (
    <div className="min-h-dvh bg-background p-4">
      <ApiKeysSettingsView
        load={load}
        actions={actions}
        writes={writes}
        onWritesOpenChange={(accountId, open) => {
          if (!open) return;
          // Pierwsze konto ma zapisy, drugie pusto, trzecie pokazuje awarię.
          setWrites((prev) => ({
            ...prev,
            [accountId]:
              accountId === 1
                ? { status: "success", writes: seedWrites(now) }
                : accountId === 3
                  ? {
                      status: "error",
                      message: "Nie udało się pobrać ostatnich zapisów.",
                      onRetry: () => undefined,
                    }
                  : { status: "success", writes: [] },
          }));
        }}
        initialRevealedKey={revealed}
        initialCreating={state === "create"}
        now={now}
      />
    </div>
  );
}
