"use client";

import Link from "next/link";
import { ChevronDown, ChevronRight, Users } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DecisionMapEntry } from "@/lib/api/sales";
import {
  useFactoryQueue,
  type FactoryQueuePerson,
  type KnownCounts,
} from "@/lib/api/sales-factories";
import { permissionLabel } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";

import { DecisionPersonDialog } from "../DecisionPersonDialog";

import { ClientHandoff } from "./ClientHandoff";
import { channelsLabel, knownLabel, levelLabel, matchesSearch, peopleLabel } from "./factories";

interface FactoryQueueProps {
  /** Opiekun z filtra Szans; `null` to kolejka zalogowanej osoby. */
  ownerId: number | null;
  /** Filtr wskazuje inną osobę, a konto nie może otworzyć jej kolejki. */
  ownerDenied: boolean;
  /** Konto z „Sprzedaż: edycja”: „Zapisz kontakt” otwiera okno osoby z mapy. */
  canEdit: boolean;
  search: string;
  known: ReadonlyMap<number, KnownCounts>;
}

interface Editing {
  opportunityId: number;
  entry: DecisionMapEntry;
}

interface PersonRowProps {
  row: FactoryQueuePerson;
  known: KnownCounts | undefined;
  onEdit?: () => void;
}

function PersonRow({ row, known, onEdit }: PersonRowProps) {
  const { person, company, client } = row;
  const role = person.role_in_company?.trim();
  return (
    <li className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5">
      <div className="min-w-0 flex-1 basis-80 leading-tight">
        <p className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-sm">
          <span className="font-medium text-foreground">{person.name}</span>
          {role && <span className="text-muted-foreground">{role}</span>}
          <span className="text-muted-foreground">
            ·{" "}
            <Link href={`/sales/opportunities/${row.opportunity.id}`} className="hover:text-foreground hover:underline">
              {company.name}
            </Link>
          </span>
          {client && (
            <Badge variant="info" size="sm" className="self-center">
              Klient NEXUSA
            </Badge>
          )}
        </p>
        <p className="text-xs text-muted-foreground">
          {[levelLabel(person), channelsLabel(person), knownLabel(known)].filter(Boolean).join(" · ")}
        </p>
        {client && (
          <p className="text-xs">
            <ClientHandoff client={client} />
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center justify-end gap-2">
        <Button asChild size="sm" variant="outline" className="h-7 px-2.5">
          <Link href={`/sales/companies/${company.id}?tab=people`} aria-label={`Kto ich zna: ${company.name}`}>
            Kto ich zna
          </Link>
        </Button>
        {onEdit && (
          <Button size="sm" className="h-7 px-2.5" aria-label={`Zapisz kontakt: ${person.name}`} onClick={onEdit}>
            Zapisz kontakt
          </Button>
        )}
      </div>
    </li>
  );
}

/**
 * Kolejka do pierwszego kontaktu: zarząd i dyrektorzy bez kontaktu z map opiekuna.
 * Niższe poziomy są zwinięte. Nie ma tu celu, postępu ani rankingu, a kontakt
 * zaczyna człowiek: lista niczego nie wysyła i nie dzwoni.
 */
export function FactoryQueue({ ownerId, ownerDenied, canEdit, search, known }: FactoryQueueProps) {
  const queue = useFactoryQueue(ownerId);
  const [showLower, setShowLower] = useState(false);
  const [editing, setEditing] = useState<Editing | null>(null);
  const data = queue.data;
  const people = (data?.people ?? []).filter((row) => matchesSearch(row, search));
  const lower = (data?.lower_levels ?? []).filter((row) => matchesSearch(row, search));
  const total = (data?.people.length ?? 0) + (data?.lower_levels.length ?? 0);
  const state = resolveViewState({
    isLoading: queue.isLoading,
    error: queue.error,
    isSuccess: queue.isSuccess,
    isEmpty: total === 0,
  });

  if (state === "loading") return <p className="py-6 text-sm text-muted-foreground">Wczytywanie kolejki…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void queue.refetch()} />;
  }

  const own = ownerId === null;
  const row = (item: FactoryQueuePerson) => (
    <PersonRow
      key={`${item.opportunity.id}-${item.person.key}`}
      row={item}
      known={known.get(item.company.id)}
      onEdit={canEdit ? () => setEditing({ opportunityId: item.opportunity.id, entry: item.person }) : undefined}
    />
  );

  return (
    <div className="space-y-2">
      {ownerDenied && (
        <p role="status" className="text-xs text-muted-foreground">
          Kolejkę innej osoby otwiera konto z uprawnieniem „{permissionLabel("sales_edit")}”. Poniżej jest Twoja.
        </p>
      )}
      {state === "empty" ? (
        <EmptyState
          icon={Users}
          title="Nikt nie czeka na pierwszy kontakt"
          description={
            own
              ? `Na mapach kont, które prowadzisz w tym lejku, nie ma osób bez kontaktu.${
                  canEdit ? " Kolejkę innej osoby pokaże filtr „Opiekun”." : ""
                }`
              : `Na mapach kont, które prowadzi ${data?.owner.name ?? "ta osoba"}, nie ma osób bez kontaktu.`
          }
        />
      ) : (
        <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 border-b border-border bg-muted/40 px-3 py-1">
            <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Do pierwszego kontaktu · poziom 1 i 2 · {own ? "Twoje mapy" : `mapy: ${data?.owner.name}`}
            </h2>
            <span className="text-xs tabular-nums text-muted-foreground">{peopleLabel(data?.people.length ?? 0)}</span>
          </div>
          <p className="border-b border-border px-3 py-1 text-xs text-muted-foreground">
            Wpis na mapie nie daje prawa do zimnego kontaktu. Zacznij od osoby, którą znamy („Kto ich zna”), albo
            działaj w ramach pilota.
          </p>
          {people.length > 0 ? (
            <ul className="divide-y divide-border">{people.map(row)}</ul>
          ) : (
            <p className="px-3 py-3 text-sm text-muted-foreground">
              {search.trim() && (data?.people.length ?? 0) > 0
                ? "Nikt z poziomu 1 i 2 nie pasuje do wyszukiwania."
                : "Na poziomie 1 i 2 wszyscy mają kontakt za sobą."}
            </p>
          )}
          {(data?.lower_levels.length ?? 0) > 0 && (
            <>
              <button
                type="button"
                aria-expanded={showLower}
                className="flex w-full items-center gap-1.5 border-t border-border px-3 py-1.5 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
                onClick={() => setShowLower((value) => !value)}
              >
                {showLower ? (
                  <ChevronDown className="size-3.5" aria-hidden />
                ) : (
                  <ChevronRight className="size-3.5" aria-hidden />
                )}
                Niższe poziomy (kierownicy, zespół) · {peopleLabel(data?.lower_levels.length ?? 0)} bez kontaktu
              </button>
              {showLower &&
                (lower.length > 0 ? (
                  <ul className="divide-y divide-border border-t border-border">{lower.map(row)}</ul>
                ) : (
                  <p className="border-t border-border px-3 py-3 text-sm text-muted-foreground">
                    Nikt z niższych poziomów nie pasuje do wyszukiwania.
                  </p>
                ))}
            </>
          )}
        </div>
      )}
      {editing && (
        <DecisionPersonDialog
          opportunityId={editing.opportunityId}
          entry={editing.entry}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
