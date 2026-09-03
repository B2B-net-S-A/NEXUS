"use client";

/**
 * Harness designu karty klienta — cztery stany obok siebie.
 *
 * Renderuje PRAWDZIWY `ClientPlaybookCard`, ale nie rusza sieci: cache
 * react-query jest zasiany z góry (`setQueryData` + `staleTime: Infinity`)
 * dla KAŻDEGO klucza, po który sięgają hooki karty (`client-playbook`
 * i `client-cv-rule`, per klient). To warunek wejścia do `PUBLIC_PATHS`
 * w middleware.ts — stronę otwiera Playwright bez sesji; niezasiany klucz
 * to 401 → przekierowanie na `/login`, czyli harness, którego nie da się
 * obejrzeć.
 *
 * Bez sesji `useCapability` daje `false`, więc linków „Edytuj kartę" /
 * „Załóż kartę" tu nie widać — pokrywają je testy jednostkowe karty.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ClientPlaybookCard } from "@/components/client-playbook/ClientPlaybookCard";
import {
  makeClientPlaybook,
  makeEmptyClientPlaybook,
} from "@/test/fixtures/client-playbook";
import { makeCvRule } from "@/test/fixtures/cv-rule";

function Case({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section data-testid={id} className="rounded-xl border border-dashed border-border p-4">
      <h2 className="mb-3 text-xs font-bold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

export default function ClientPlaybookPreviewPage() {
  const queryClient = useMemo(() => {
    // `retryOnMount: false` — patrz klient 3 niżej.
    const qc = new QueryClient({
      defaultOptions: {
        queries: { retry: false, retryOnMount: false, staleTime: Infinity },
      },
    });
    qc.setQueryData(["client-playbook", 1], makeClientPlaybook());
    qc.setQueryData(["client-cv-rule", 1], makeCvRule());
    qc.setQueryData(
      ["client-playbook", 2],
      makeEmptyClientPlaybook(2, "PKO Bank Polski"),
    );
    qc.setQueryData(
      ["client-cv-rule", 2],
      makeCvRule({
        client_id: 2,
        client_name: "PKO Bank Polski",
        is_active: false,
        confirmed_at: null,
        client_policy: "",
        filename_preview: null,
      }),
    );
    // Klient 3 = gałąź błędu. Domyślny `queryFn` w QueryClient NIE zadziała:
    // hook `useClientPlaybook` ma własny queryFn, który wygrywa przy scalaniu
    // opcji i poszedłby do API (401 → przekierowanie na /login). Zasiewamy
    // stan błędu wprost w cache; `retryOnMount: false` powyżej sprawia, że
    // obserwator nie ponawia przy montowaniu. „Spróbuj ponownie" w tym
    // harnessie strzela do prawdziwego API — to oczekiwane.
    const failed = qc.getQueryCache().build(qc, { queryKey: ["client-playbook", 3] });
    failed.setState({
      status: "error",
      fetchStatus: "idle",
      error: new Error("podgląd: symulowana awaria"),
      errorUpdateCount: 1,
      errorUpdatedAt: Date.now(),
    });
    qc.setQueryData(["client-cv-rule", 3], makeCvRule({ client_id: 3 }));
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto flex max-w-5xl flex-col gap-8 p-6">
        <header>
          <h1 className="text-lg font-semibold text-foreground">Karta klienta — stany</h1>
          <p className="text-xs text-muted-foreground">
            Harness. Zero wywołań API; bez sesji capability = false, więc linków
            „Edytuj" nie widać (pokrywają testy).
          </p>
        </header>

        <Case id="case-full" title="1. Pełna karta (klient 1, reguła CV obowiązuje)">
          <ClientPlaybookCard
            clientId={1}
            variant="full"
            editHref="/settings/cv-rules?client=1&tab=playbook"
          />
        </Case>

        <Case id="case-empty" title="2. Brak karty (klient 2, exists=false)">
          <ClientPlaybookCard
            clientId={2}
            variant="full"
            editHref="/settings/cv-rules?client=2&tab=playbook"
          />
        </Case>

        <Case id="case-compact" title="3. Wariant compact (strona oferty)">
          <ClientPlaybookCard clientId={1} variant="compact" />
        </Case>

        <Case id="case-error" title="4. Awaria pobrania (klient 3)">
          <ClientPlaybookCard clientId={3} variant="full" />
        </Case>
      </main>
    </QueryClientProvider>
  );
}
