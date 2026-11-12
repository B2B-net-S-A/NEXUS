"use client";

import { useSearchParams } from "next/navigation";
import { Target } from "lucide-react";
import { useMemo } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import type { Opportunity } from "@/lib/api/sales";
import { useBotPeoplePending } from "@/lib/api/sales-bot-people";
import { useFactoryAccounts, useFactoryKnownPeople } from "@/lib/api/sales-factories";
import { useUrlWriter } from "@/lib/url-selection";

import { FactoryAccountsTable, type KnownState } from "./FactoryAccountsTable";
import { FactoryQueue } from "./FactoryQueue";
import { summarizeAccounts, summaryLine } from "./factories";

type Mode = "accounts" | "queue";

interface FactoriesViewProps {
  /** Szanse lejka po filtrach zakładki (opiekun, szukanie, archiwum). */
  items: readonly Opportunity[];
  /** Opiekun z filtra Szans („Moje” albo wybrana osoba); `null` bez filtra. */
  ownerId: number | null;
  currentUserId: number | null;
  canEdit: boolean;
  archived: boolean;
  search: string;
}

/**
 * Lejek Fabryki IT jako lista kont mierzona kontaktem, z przełącznikiem na kolejkę
 * osób do pierwszego kontaktu (decyzje Artura 10.11.2026). Sam odczyt i podpowiedzi:
 * nic tu nie blokuje zapisu etapu.
 */
export function FactoriesView({ items, ownerId, currentUserId, canEdit, archived, search }: FactoriesViewProps) {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const mode: Mode = searchParams?.get("kolejka") === "1" ? "queue" : "accounts";
  const accounts = useFactoryAccounts(archived);
  const known = useFactoryKnownPeople(archived);

  const facts = useMemo(
    () => (accounts.data ? new Map(accounts.data.map((account) => [account.opportunity_id, account])) : null),
    [accounts.data],
  );
  const knownByCompany = useMemo(
    () => new Map((known.data?.items ?? []).map((counts) => [counts.company_id, counts])),
    [known.data],
  );
  const knownState: KnownState = known.isSuccess ? "ready" : known.isError ? "error" : "loading";
  // Plakietka „Osoby od bota”: dodatek, bez flagi albo przy błędzie po prostu jej nie ma.
  const botPeople = useBotPeoplePending();
  const botPending = useMemo(
    () => new Map((botPeople.data?.enabled ? botPeople.data.items : []).map((item) => [item.company.id, item])),
    [botPeople.data],
  );

  const setMode = (next: Mode) => {
    const params = new URLSearchParams(window.location.search);
    if (next === "queue") params.set("kolejka", "1");
    else params.delete("kolejka");
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };

  // Cudzą kolejkę otwiera konto z „Sprzedaż: edycja” (także admin); serwer pilnuje tego samego.
  const otherOwner = ownerId !== null && ownerId !== currentUserId;
  const queueOwnerId = otherOwner && canEdit ? ownerId : null;

  return (
    <div className="space-y-2">
      <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <p className="text-sm text-muted-foreground">
          {mode === "accounts" && facts && items.length > 0 ? summaryLine(summarizeAccounts(items, facts)) : null}
        </p>
        <div data-tour="sales.factories.mode">
          <SegmentedRadio
            size="sm"
            label="Zakres listy"
            options={[
              { value: "accounts", label: "Wszystkie" },
              { value: "queue", label: "Kolejka" },
            ]}
            value={mode}
            onChange={setMode}
          />
        </div>
      </div>
      {accounts.isError && mode === "accounts" && items.length > 0 && (
        <p role="alert" className="flex flex-wrap items-center gap-2 text-xs text-warning">
          Nie udało się wczytać liczników map. Konta są na liście, ale bez liczb z mapy.
          <Button size="sm" variant="outline" className="h-6 px-2" onClick={() => void accounts.refetch()}>
            Spróbuj ponownie
          </Button>
        </p>
      )}
      {known.isError && (
        <p role="alert" className="flex flex-wrap items-center gap-2 text-xs text-warning">
          Nie udało się policzyć osób z bazy („Znamy teraz”, „Kiedyś”).
          <Button size="sm" variant="outline" className="h-6 px-2" onClick={() => void known.refetch()}>
            Spróbuj ponownie
          </Button>
        </p>
      )}
      {known.data?.truncated && (
        <p role="status" className="text-xs text-muted-foreground">
          Osób z bazy jest więcej, niż obejmuje jedno przeliczenie: „Znamy teraz” i „Kiedyś” to dolna granica.
        </p>
      )}
      {mode === "accounts" && items.length === 0 ? (
        // Lista szans wczytała się i jest pusta (awarię pokazuje zakładka wyżej).
        <EmptyState
          icon={Target}
          title="Brak kont na liście"
          description="Żadna szansa tego lejka nie pasuje do wyszukiwania i filtrów. Kolejka osób od nich nie zależy."
        />
      ) : mode === "accounts" ? (
        <FactoryAccountsTable
          items={items}
          accounts={facts}
          known={knownByCompany}
          knownState={knownState}
          botPending={botPending}
        />
      ) : (
        <FactoryQueue
          ownerId={queueOwnerId}
          ownerDenied={otherOwner && !canEdit}
          canEdit={canEdit}
          search={search}
          known={knownByCompany}
        />
      )}
    </div>
  );
}
