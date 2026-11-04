"use client";

// Ustawienia → System → „Klucze API” — kontener ekranu: react-query i zapisy.
// Wygląd i logika ekranu: `components/settings/api-keys/ApiKeysSettingsView`.
// Dostęp: admin z sekcją System (middleware `/settings/api-keys` + `AdminUser`
// w `backend/app/api/service_accounts.py`).

import { useMemo, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiKeysSettingsView } from "@/components/settings/api-keys/ApiKeysSettingsView";
import type {
  AccountWebhooksState,
  AccountWritesState,
  ApiKeysActions,
  ApiKeysLoad,
} from "@/components/settings/api-keys/types";
import { serviceAccountsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { isForbiddenError } from "@/lib/view-state";

const ACCOUNTS_KEY = ["service-accounts"] as const;
const SCOPES_KEY = ["service-accounts", "scopes"] as const;
const CONFIG_KEY = ["service-accounts", "config"] as const;
const writesKey = (accountId: number) => ["service-accounts", "writes", accountId] as const;
const webhooksKey = (accountId: number) => ["service-accounts", "webhooks", accountId] as const;

/** Dodaj albo zdejmij konto z listy otwartych paneli. */
function toggleOpen(prev: readonly number[], accountId: number, open: boolean): readonly number[] {
  if (!open) return prev.filter((id) => id !== accountId);
  return prev.includes(accountId) ? prev : [...prev, accountId];
}

export default function ApiKeysSettingsPage() {
  const queryClient = useQueryClient();
  const [openWrites, setOpenWrites] = useState<readonly number[]>([]);
  const [openWebhooks, setOpenWebhooks] = useState<readonly number[]>([]);

  const accountsQuery = useQuery({
    queryKey: ACCOUNTS_KEY,
    queryFn: () => serviceAccountsApi.list().then((r) => r.data),
  });
  const scopesQuery = useQuery({
    queryKey: SCOPES_KEY,
    queryFn: () => serviceAccountsApi.scopes().then((r) => r.data),
    staleTime: 10 * 60 * 1000,
  });
  const configQuery = useQuery({
    queryKey: CONFIG_KEY,
    queryFn: () => serviceAccountsApi.config().then((r) => r.data),
    staleTime: 10 * 60 * 1000,
  });
  const writesQueries = useQueries({
    queries: openWrites.map((accountId) => ({
      queryKey: writesKey(accountId),
      queryFn: () => serviceAccountsApi.writes(accountId).then((r) => r.data),
    })),
  });
  const webhooksQueries = useQueries({
    queries: openWebhooks.map((accountId) => ({
      queryKey: webhooksKey(accountId),
      queryFn: () => serviceAccountsApi.webhooks(accountId).then((r) => r.data),
    })),
  });

  // Ekran pokazuje dane, gdy są wszystkie trzy. Nieudane odświeżenie PO
  // sukcesie (np. po wydaniu klucza) zostawia ostatnią listę — inaczej ekran
  // przeskoczyłby w błąd i zabrał kartę z kluczem pokazywanym raz. Pierwsze
  // ładowanie zakończone błędem to błąd, nigdy pusta lista.
  const queries = [accountsQuery, scopesQuery, configQuery];
  let load: ApiKeysLoad;
  if (accountsQuery.data && scopesQuery.data && configQuery.data) {
    load = {
      status: "success",
      accounts: accountsQuery.data,
      scopes: scopesQuery.data,
      config: configQuery.data,
    };
  } else {
    const failed = queries.find((q) => q.isError && q.data === undefined);
    if (failed) {
      const forbidden = isForbiddenError(failed.error);
      load = {
        status: "error",
        forbidden,
        message: forbidden
          ? "Klucze API zarządza wyłącznie administrator."
          : apiErrorMessage(failed.error, "Nie udało się pobrać kont serwisowych. Spróbuj ponownie."),
        onRetry: () => {
          for (const q of queries) if (q.isError) void q.refetch();
        },
      };
    } else {
      load = { status: "loading" };
    }
  }

  const writes: Record<number, AccountWritesState> = {};
  openWrites.forEach((accountId, index) => {
    const q = writesQueries[index];
    if (!q) return;
    if (q.data) writes[accountId] = { status: "success", writes: q.data };
    else if (q.isError) {
      writes[accountId] = {
        status: "error",
        message: apiErrorMessage(q.error, "Nie udało się pobrać ostatnich zapisów."),
        onRetry: () => void q.refetch(),
      };
    } else writes[accountId] = { status: "loading" };
  });

  const webhooks: Record<number, AccountWebhooksState> = {};
  openWebhooks.forEach((accountId, index) => {
    const q = webhooksQueries[index];
    if (!q) return;
    if (q.data) webhooks[accountId] = { status: "success", webhooks: q.data };
    else if (q.isError) {
      webhooks[accountId] = {
        status: "error",
        message: apiErrorMessage(q.error, "Nie udało się pobrać webhooków."),
        onRetry: () => void q.refetch(),
      };
    } else webhooks[accountId] = { status: "loading" };
  });

  const actions = useMemo<ApiKeysActions>(() => {
    // `invalidateQueries` nie rzuca przy nieudanym odświeżeniu, więc zapis,
    // który przeszedł, nie zamienia się w komunikat o błędzie.
    const refresh = () => queryClient.invalidateQueries({ queryKey: ACCOUNTS_KEY, exact: true });
    return {
      createAccount: async (payload) => {
        await serviceAccountsApi.create(payload);
        await refresh();
      },
      updateAccount: async (id, payload) => {
        await serviceAccountsApi.update(id, payload);
        await refresh();
      },
      deleteAccount: async (id) => {
        await serviceAccountsApi.remove(id);
        setOpenWrites((prev) => prev.filter((accountId) => accountId !== id));
        setOpenWebhooks((prev) => prev.filter((accountId) => accountId !== id));
        queryClient.removeQueries({ queryKey: writesKey(id) });
        queryClient.removeQueries({ queryKey: webhooksKey(id) });
        await refresh();
      },
      issueKey: async (id, payload) => {
        const { data } = await serviceAccountsApi.issueKey(id, payload);
        await refresh();
        return data;
      },
      revokeKey: async (id, keyId, reason) => {
        await serviceAccountsApi.revokeKey(id, keyId, reason);
        await refresh();
      },
    };
  }, [queryClient]);

  return (
    <ApiKeysSettingsView
      load={load}
      actions={actions}
      writes={writes}
      onWritesOpenChange={(accountId, open) =>
        setOpenWrites((prev) => toggleOpen(prev, accountId, open))
      }
      webhooks={webhooks}
      onWebhooksOpenChange={(accountId, open) =>
        setOpenWebhooks((prev) => toggleOpen(prev, accountId, open))
      }
    />
  );
}
