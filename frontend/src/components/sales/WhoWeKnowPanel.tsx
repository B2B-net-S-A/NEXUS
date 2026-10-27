"use client";

import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  RELATIONSHIP_LABELS,
  useCompanyPeople,
  useFillCompanyDates,
  type CompanyPeople,
  type MatchedPerson,
  type PeopleRelationship,
} from "@/lib/api/sales";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { safeHref } from "./format";

const ORDER: PeopleRelationship[] = ["via_us", "current", "past", "unknown"];
/** Ile osób z grupy pokazujemy, zanim ktoś kliknie „Pokaż wszystkich”. */
const PREVIEW = 8;

/** Okres z CV: „2019–2022”, „2023–teraz”. Koniec bez roku („present”, „obecnie”) to „teraz”. */
export function period(person: Pick<MatchedPerson, "period">): string | null {
  const start = person.period?.start?.trim();
  const end = person.period?.end?.trim();
  if (!start && !end) return null;
  const until = end && /\d{4}/.test(end) ? end : "teraz";
  return `${start || "?"}–${until}`;
}

/** „uzupełniamy daty 120 osób” / „daty uzupełnione: 7 z 7” — z udanego odczytu. */
export function datesNote(state: CompanyPeople["dates_backfill"]): string | null {
  if (!state?.status) return null;
  if (state.status === "running") return `Uzupełniamy daty ${state.total ?? 0} osób z CV…`;
  if (state.status === "failed") return "Uzupełnianie dat nie powiodło się — spróbuj jeszcze raz.";
  const done = `Daty uzupełnione: ${state.updated ?? 0} z ${state.total ?? 0} osób`;
  return state.status === "partial" ? `${done} (przerwane, możesz dokończyć)` : done;
}

function PersonRow({ person }: { person: MatchedPerson }) {
  const where = [person.title, person.company_matched, period(person)].filter(Boolean).join(" · ");
  return (
    <li className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 py-2">
      <div className="min-w-0">
        <Link
          href={`/candidates/${person.candidate_id}`}
          className="font-medium text-foreground hover:underline"
        >
          {person.name} {person.lastname}
        </Link>
        {where && <p className="text-xs text-muted-foreground">{where}</p>}
      </div>
      <div className="flex flex-wrap gap-x-3 text-xs">
        {person.email && (
          <a className="text-primary hover:underline" href={`mailto:${person.email}`}>
            {person.email}
          </a>
        )}
        {person.phone && (
          <a className="text-primary hover:underline" href={`tel:${person.phone}`}>
            {person.phone}
          </a>
        )}
        {safeHref(person.linkedin) && (
          <a className="text-primary hover:underline" href={safeHref(person.linkedin)} target="_blank" rel="noreferrer">
            LinkedIn
          </a>
        )}
      </div>
    </li>
  );
}

interface WhoWeKnowPanelProps {
  companyId: number;
  companyName: string;
}

/**
 * „Kogo znamy w firmie”: osoby z bazy NEXUSA w czterech grupach, z pełnym
 * profilem i kontaktem (decyzja D4, 26.10.2026), oraz liczby dla spółek
 * z tej samej grupy kapitałowej. „Bez dat” to osoby, których CV wymienia
 * firmę bez dat — nie wiemy, czy pracują tam teraz (D3: uzupełnij daty).
 */
export function WhoWeKnowPanel({ companyId, companyName }: WhoWeKnowPanelProps) {
  const people = useCompanyPeople(companyId);
  const fill = useFillCompanyDates(companyId);
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { showError, showSuccess } = useToast();
  const [expanded, setExpanded] = useState<Set<PeopleRelationship>>(new Set());
  const data = people.data;
  const total = data ? ORDER.reduce((sum, key) => sum + (data.counts[key] ?? 0), 0) : 0;
  const state = resolveViewState({
    isLoading: people.isLoading,
    error: people.error,
    isSuccess: people.isSuccess,
    isEmpty: total === 0,
  });

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">Kogo znamy w {companyName}</h2>
        {data?.matched_client && (
          <Link href={`/clients/${data.matched_client.id}`} className="text-xs text-primary hover:underline">
            Klient w NEXUSIE: {data.matched_client.name}
          </Link>
        )}
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Szukamy osób z bazy…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void people.refetch()} />
      ) : data ? (
        <>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {ORDER.map((key) => (
              <div key={key} className="rounded-md border border-border px-3 py-2">
                <dt className="text-xs text-muted-foreground">{RELATIONSHIP_LABELS[key]}</dt>
                <dd className="text-lg font-semibold tabular-nums text-foreground">
                  {data.counts[key] ?? 0}
                </dd>
              </div>
            ))}
          </dl>
          {(data.counts.unknown > 0 || data.dates_backfill?.status) && (
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>
                {datesNote(data.dates_backfill) ??
                  "Osoby bez dat w CV nie wiadomo, czy pracują tam teraz."}
              </span>
              {canEdit && data.counts.unknown > 0 && data.dates_backfill?.status !== "running" && (
                <Button
                  size="sm"
                  variant="outline"
                  loading={fill.isPending}
                  onClick={() =>
                    fill.mutate(undefined, {
                      onSuccess: () => showSuccess("Uzupełniamy daty w tle — wróć za kilka minut."),
                      onError: (error) =>
                        showError(apiErrorMessage(error, "Nie udało się uruchomić uzupełniania dat.")),
                    })
                  }
                >
                  Uzupełnij daty
                </Button>
              )}
            </div>
          )}
          {state === "empty" ? (
            <p className="text-sm text-muted-foreground">
              Nikt z bazy NEXUSA nie ma tej firmy w CV ani kontraktu u niej.
            </p>
          ) : (
            ORDER.filter((key) => data.people.some((p) => p.relationship === key)).map((key) => {
              const group = data.people.filter((p) => p.relationship === key);
              const open = expanded.has(key);
              const shown = open ? group : group.slice(0, PREVIEW);
              return (
                <section key={key} aria-label={RELATIONSHIP_LABELS[key]}>
                  <h3 className="text-sm font-medium text-foreground">
                    {RELATIONSHIP_LABELS[key]} ({data.counts[key]})
                  </h3>
                  <ul className="divide-y divide-border">
                    {shown.map((person) => (
                      <PersonRow key={person.candidate_id} person={person} />
                    ))}
                  </ul>
                  {group.length > PREVIEW && (
                    <button
                      type="button"
                      className="text-xs text-primary hover:underline"
                      onClick={() =>
                        setExpanded((current) => {
                          const next = new Set(current);
                          if (open) next.delete(key);
                          else next.add(key);
                          return next;
                        })
                      }
                    >
                      {open ? "Pokaż mniej" : `Pokaż wszystkich (${group.length})`}
                    </button>
                  )}
                </section>
              );
            })
          )}
          {data.truncated && (
            <p className="text-xs text-muted-foreground">
              Lista pokazuje pierwsze {data.people.length} osób; liczby wyżej są pełne.
            </p>
          )}
          {data.group.length > 0 && (
            <div className="border-t border-border pt-3">
              <h3 className="text-sm font-medium text-foreground">Grupa kapitałowa</h3>
              <ul className="mt-1 space-y-1 text-sm">
                {data.group.map((item) => (
                  <li key={item.company.id} className="flex flex-wrap justify-between gap-2">
                    <Link href={`/sales/companies/${item.company.id}`} className="text-primary hover:underline">
                      {item.company.name}
                      <span className="text-muted-foreground">
                        {item.relation === "parent" ? " · firma matka" : " · spółka zależna"}
                      </span>
                    </Link>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      przez nas {item.counts.via_us} · teraz {item.counts.current} · kiedyś{" "}
                      {item.counts.past} · bez dat {item.counts.unknown}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : null}
    </Card>
  );
}
