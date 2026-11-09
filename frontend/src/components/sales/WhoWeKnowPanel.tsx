"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TruncatedText } from "@/components/ds/TruncatedText";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  RELATIONSHIP_LABELS,
  useCompanyGroupPeople,
  useCompanyPeople,
  useFillCompanyDates,
  type CompanyPeople,
  type MatchedPerson,
  type PeopleRelationship,
} from "@/lib/api/sales";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { CompanyAliasStrip } from "./CompanyAliasStrip";
import { safeHref } from "./format";
import { plural } from "./peoplePlural";

const ORDER: PeopleRelationship[] = ["via_us", "current", "past", "unknown"];
/** Ile osób z grupy pokazujemy, zanim ktoś kliknie „Pokaż całą grupę”. */
const PREVIEW = 8;
/** Ilu pracujących pokazujemy na start. Kolejność ustala API. */
const START_COUNT = 5;
const ROW = "flex items-start justify-between gap-4 py-1";

type Section = PeopleRelationship | "group";

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

function startHint(decision: number, fresh: number): string {
  const decisionPart = `${decision} ${plural(decision, "rola decyzyjna", "role decyzyjne", "ról decyzyjnych")}`;
  const freshPart = fresh === 1 ? "1 najświeżej dodana" : `${fresh} najświeżej dodane`;
  if (decision === 0) return freshPart;
  return fresh === 0 ? decisionPart : `${decisionPart}, potem ${freshPart}`;
}

function formatDay(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${day}.${month}.${year}`;
}

function byName(a: MatchedPerson, b: MatchedPerson): number {
  return a.lastname.localeCompare(b.lastname, "pl") || a.name.localeCompare(b.name, "pl");
}

function whereLine(person: MatchedPerson): string {
  return [person.title, person.company_matched, period(person)].filter(Boolean).join(" · ");
}

function Contacts({ person }: { person: MatchedPerson }) {
  return (
    <div className="flex flex-wrap justify-end gap-x-3 text-xs">
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
  );
}

function PersonName({ person }: { person: MatchedPerson }) {
  return (
    <Link href={`/candidates/${person.candidate_id}`} className="font-medium text-foreground hover:underline">
      {person.name} {person.lastname}
    </Link>
  );
}

function StartRow({ person }: { person: MatchedPerson }) {
  return (
    <li className={ROW}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2">
          <PersonName person={person} />
          {person.decision_role && (
            <Badge variant="soft" size="sm">
              Rola decyzyjna
            </Badge>
          )}
          {person.cv_stale && (
            <Badge variant="warning" size="sm">
              CV sprzed 3 lat
            </Badge>
          )}
        </div>
        <TruncatedText className="max-w-none text-xs text-muted-foreground">{whereLine(person)}</TruncatedText>
      </div>
      <div className="shrink-0 text-right">
        <Contacts person={person} />
        {person.added_at && <p className="text-xs text-muted-foreground">w bazie od {formatDay(person.added_at)}</p>}
      </div>
    </li>
  );
}

function PersonRow({ person }: { person: MatchedPerson }) {
  return (
    <li className={ROW}>
      <div className="min-w-0 flex-1">
        <PersonName person={person} />
        <TruncatedText className="max-w-none text-xs text-muted-foreground">{whereLine(person)}</TruncatedText>
      </div>
      <Contacts person={person} />
    </li>
  );
}

interface GroupSectionProps {
  section: Section;
  title: string;
  total: number;
  people: MatchedPerson[];
  preview?: number;
  listed: number;
}

function GroupSection({ section, title, total, people, preview = PREVIEW, listed }: GroupSectionProps) {
  const [all, setAll] = useState(false);
  const shown = all ? people : people.slice(0, preview);
  return (
    <section id={`who-we-know-${section}`} aria-label={title} className="scroll-mt-10">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h3 className="text-sm font-medium text-foreground">
          {title} ({total})
        </h3>
        {people.length > 0 && people.length < total && (
          <span className="text-xs text-muted-foreground">
            na liście {people.length} z {total}
          </span>
        )}
      </div>
      {people.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Tych osób nie widać, bo lista kończy się na pierwszych {listed} osobach. Liczba jest pełna.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {shown.map((person) => (
            <PersonRow key={person.candidate_id} person={person} />
          ))}
        </ul>
      )}
      {people.length > preview && (
        <button type="button" className="text-xs text-primary hover:underline" onClick={() => setAll((value) => !value)}>
          {all ? "Pokaż mniej" : `Pokaż całą grupę (${people.length})`}
        </button>
      )}
    </section>
  );
}

interface WhoWeKnowPanelProps {
  companyId: number;
  companyName: string;
}

/**
 * „Kogo znamy w firmie”: pięć osób na start (role decyzyjne, potem najświeżej
 * dodani), inne nazwy z CV do dołączenia i reszta grup pod przyciskami. Pełny
 * profil i kontakt zgodnie z decyzją D4 (26.10.2026). „Bez dat” to osoby,
 * których CV wymienia firmę bez dat (D3: uzupełnij daty).
 */
export function WhoWeKnowPanel({ companyId, companyName }: WhoWeKnowPanelProps) {
  const people = useCompanyPeople(companyId);
  const [open, setOpen] = useState<ReadonlySet<Section>>(new Set());
  const [focus, setFocus] = useState<Section | null>(null);
  const group = useCompanyGroupPeople(companyId, open.has("group"));
  const fill = useFillCompanyDates(companyId);
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { showError, showSuccess } = useToast();
  const data = people.data;
  const total = data ? ORDER.reduce((sum, key) => sum + (data.counts[key] ?? 0), 0) : 0;
  const state = resolveViewState({
    isLoading: people.isLoading,
    error: people.error,
    isSuccess: people.isSuccess,
    isEmpty: total === 0,
  });

  const current = useMemo(() => (data?.people ?? []).filter((p) => p.relationship === "current"), [data]);
  const start = current.slice(0, START_COUNT);
  const rest = useMemo(() => [...current.slice(START_COUNT)].sort(byName), [current]);
  const decisionCount = start.filter((p) => p.decision_role).length;

  // Otwarta sekcja leży pod pierwszym ekranem, więc przewijamy do niej od razu.
  useEffect(() => {
    if (focus) document.getElementById(`who-we-know-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focus]);

  const toggle = (section: Section) => {
    const isOpen = open.has(section);
    const next = new Set(open);
    if (isOpen) next.delete(section);
    else next.add(section);
    setOpen(next);
    setFocus(isOpen ? null : section);
  };

  const otherGroups = data ? ORDER.filter((key) => key !== "current" && (data.counts[key] ?? 0) > 0) : [];
  const currentCount = data?.counts.current ?? 0;
  // Do pięciu osób wszyscy są już na liście startowej, więc nie ma czego rozwijać.
  const canExpand = currentCount > START_COUNT;
  const openGroups = ORDER.filter((key) => open.has(key) && (key !== "current" || canExpand));
  const listOpen = openGroups.some((key) => data?.people.some((p) => p.relationship === key));

  return (
    <Card className="space-y-2 p-4">
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
      ) : data?.own_company ? (
        <p className="text-sm text-muted-foreground">To nasza firma, więc listy osób tutaj nie pokazujemy.</p>
      ) : data ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <InlineStats
              stats={ORDER.map((key) => ({
                id: key,
                label: RELATIONSHIP_LABELS[key],
                value: data.counts[key] ?? 0,
              }))}
            />
            {(data.counts.unknown > 0 || data.dates_backfill?.status) && (
              <div className="flex min-w-0 flex-wrap items-center justify-end gap-x-3 gap-y-1">
                <p className="min-w-0 text-right text-xs text-muted-foreground">
                  {datesNote(data.dates_backfill) ?? "Osoby bez dat w CV nie wiadomo, czy pracują tam teraz."}
                </p>
                {canEdit && data.counts.unknown > 0 && data.dates_backfill?.status !== "running" && (
                  <Button
                    className="shrink-0"
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
                    Uzupełnij daty ({data.counts.unknown})
                  </Button>
                )}
              </div>
            )}
          </div>
          <CompanyAliasStrip companyId={companyId} canEdit={canEdit} />
          {state === "empty" && (
            <p className="text-sm text-muted-foreground">
              Nikt z bazy NEXUSA nie ma tej firmy w CV ani kontraktu u niej.
            </p>
          )}
          {start.length > 0 && (
            <section aria-labelledby="who-we-know-start">
              <h3 id="who-we-know-start" className="text-sm font-medium text-foreground">
                Pracują tam teraz. Zacznij od: {startHint(decisionCount, start.length - decisionCount)} ({start.length}{" "}
                z {currentCount})
              </h3>
              <ul className="divide-y divide-border">
                {start.map((person) => (
                  <StartRow key={person.candidate_id} person={person} />
                ))}
              </ul>
            </section>
          )}
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs">
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {canExpand && (
                <button
                  type="button"
                  aria-expanded={open.has("current")}
                  className="text-primary hover:underline"
                  onClick={() => toggle("current")}
                >
                  {open.has("current") ? "Pokaż mniej" : `Pokaż wszystkich pracujących (${currentCount})`}
                </button>
              )}
              {otherGroups.map((key) => (
                <button
                  key={key}
                  type="button"
                  aria-expanded={open.has(key)}
                  className="text-primary hover:underline"
                  onClick={() => toggle(key)}
                >
                  {open.has(key) ? `Zwiń: ${RELATIONSHIP_LABELS[key]}` : `${RELATIONSHIP_LABELS[key]} (${data.counts[key]})`}
                </button>
              ))}
              <button
                type="button"
                aria-expanded={open.has("group")}
                className="text-primary hover:underline"
                onClick={() => toggle("group")}
              >
                {open.has("group") ? "Zwiń: Grupa kapitałowa" : "Grupa kapitałowa"}
              </button>
            </div>
            {data.read_logged && <span className="text-muted-foreground">Odczyt zapisany w dzienniku</span>}
          </div>
          {openGroups.map((key) =>
            key === "current" ? (
              <GroupSection
                key={key}
                section={key}
                title="Pozostali, alfabetycznie"
                total={Math.max(currentCount - start.length, 0)}
                people={rest}
                preview={rest.length}
                listed={data.people.length}
              />
            ) : (
              <GroupSection
                key={key}
                section={key}
                title={RELATIONSHIP_LABELS[key]}
                total={data.counts[key] ?? 0}
                people={data.people.filter((p) => p.relationship === key)}
                listed={data.people.length}
              />
            ),
          )}
          {data.truncated && listOpen && (
            <p className="text-xs text-muted-foreground">
              Lista pokazuje pierwsze {data.people.length} osób; liczby wyżej są pełne.
            </p>
          )}
          {open.has("group") && (
            <div id="who-we-know-group" className="scroll-mt-10 border-t border-border pt-3">
              <h3 className="text-sm font-medium text-foreground">Grupa kapitałowa</h3>
              {group.isError ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Nie udało się policzyć grupy kapitałowej.{" "}
                  <button type="button" className="text-primary hover:underline" onClick={() => void group.refetch()}>
                    Spróbuj ponownie
                  </button>
                </p>
              ) : group.isSuccess ? (
                group.data.length > 0 ? (
                  <ul className="mt-1 space-y-1 text-sm">
                    {group.data.map((item) => (
                      <li key={item.company.id} className="flex flex-wrap justify-between gap-2">
                        <Link href={`/sales/companies/${item.company.id}`} className="text-primary hover:underline">
                          {item.company.name}
                          <span className="text-muted-foreground">
                            {item.relation === "parent" ? " · firma matka" : " · spółka zależna"}
                          </span>
                        </Link>
                        <span className="text-xs tabular-nums text-muted-foreground">
                          {item.counts
                            ? `przez nas ${item.counts.via_us} · teraz ${item.counts.current} · kiedyś ${item.counts.past} · bez dat ${item.counts.unknown}`
                            : "nie policzyliśmy (spróbuj później)"}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">Ta firma nie ma powiązanych spółek w kartotece.</p>
                )
              ) : (
                <p className="mt-1 text-xs text-muted-foreground">Liczymy osoby w spółkach z grupy…</p>
              )}
            </div>
          )}
        </>
      ) : null}
    </Card>
  );
}
