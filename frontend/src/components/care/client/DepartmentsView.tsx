"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { BriefcaseBusiness } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import { HEALTH_DOT } from "@/lib/api/care-board";
import { consultantHealth, jobsNewHref } from "@/lib/api/care-clients";
import { useCareOwners, useSetClientDefaultOwner, type ClientTechMap } from "@/lib/api/care";
import {
  formatAverage,
  useUpdateContactOrg,
  type ClientOrg,
  type OrgConsultant,
  type OrgPerson,
} from "@/lib/api/client-people";
import { CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";

import { GapsCard } from "../ClientTechnologiesTab";
import type { FeedbackTarget } from "../PersonPanel";
import { candidatesHref } from "../tech-gaps";
import {
  departmentCards,
  peopleOutsideDepartments,
  strengthDots,
  strengthLabel,
  topSkillIds,
  type DepartmentCard,
  type DepartmentManager,
} from "./people-tech-format";

/** Ile technologii działu stoi na karcie — reszta liczbą („+4”). */
const TECH_ON_CARD = 6;

function ConsultantRow({ consultant }: { consultant: OrgConsultant }) {
  const health = consultantHealth(consultant);
  const name = consultant.candidate_name ?? `Kontrakt #${consultant.contract_id}`;
  const about = [
    consultant.role,
    consultant.end_date ? `do ${formatDayMonthPl(consultant.end_date)}` : null,
  ].filter(Boolean);
  return (
    <span className="inline-flex min-w-0 items-baseline gap-1">
      {health ? (
        <span
          aria-hidden
          title={`${health.label}${health.reasons.length ? ` — ${health.reasons.join(", ")}` : ""}`}
          className={cn("size-1.5 shrink-0 translate-y-[-1px] rounded-full", HEALTH_DOT[health.level])}
        />
      ) : null}
      <Link href={`/care?contract=${consultant.contract_id}`} className="truncate font-medium hover:underline">
        {name}
        {health ? <span className="sr-only">{`, ${health.label}`}</span> : null}
      </Link>
      {about.length ? (
        <span className="truncate text-xs text-muted-foreground">· {about.join(" · ")}</span>
      ) : null}
    </span>
  );
}

/** „opinia: czeka od 19.10”, „opinia 16.08 · 4,3”, „bez opinii”. */
export function opinionText(manager: Pick<DepartmentManager, "lastFeedback" | "feedbackRequest">): string {
  if (manager.feedbackRequest) return `opinia: czeka od ${formatDayMonthPl(manager.feedbackRequest.due_on)}`;
  if (manager.lastFeedback) {
    const average = manager.lastFeedback.average;
    return `opinia ${formatDayMonthPl(manager.lastFeedback.held_on)}${average != null ? ` · ${formatAverage(average)}` : ""}`;
  }
  return "bez opinii";
}

function ManagerLine({
  card,
  canWriteFeedback,
  onFeedback,
}: {
  card: DepartmentCard;
  canWriteFeedback: boolean;
  onFeedback: (target: FeedbackTarget) => void;
}) {
  if (!card.managers.length) {
    return (
      <p className="text-xs text-muted-foreground">
        menedżer: <span className="text-foreground">nie wskazano</span>
        {card.consultantsCount ? "" : " · nikt z naszych tu nie pracuje"}
        <span className="block">bez opinii</span>
      </p>
    );
  }
  return (
    <ul className="space-y-1">
      {card.managers.map((manager) => {
        const waiting = manager.feedbackRequest != null;
        return (
          <li key={manager.id} className="text-xs">
            <span className="text-muted-foreground">menedżer naszych: </span>
            <span className="text-sm font-medium text-foreground">{manager.name}</span>
            <span className="text-muted-foreground">
              {manager.position ? ` · ${manager.position}` : ""}
              {" → podlega pod "}
              {manager.reportsTo
                ? `${manager.reportsTo}${manager.reportsToPosition ? ` (${manager.reportsToPosition})` : ""}`
                : "—"}
            </span>
            <span className="block">
              <span className={cn(waiting ? "font-medium text-warning-muted-foreground" : "text-muted-foreground")}>
                {opinionText(manager)}
              </span>
              {canWriteFeedback ? (
                <button
                  type="button"
                  className="ml-2 text-primary hover:underline"
                  onClick={() =>
                    onFeedback({
                      manager: { id: manager.id, name: manager.name },
                      consultants: manager.consultants,
                    })
                  }
                >
                  Zapisz opinię
                </button>
              ) : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** „Szukają: Java Developer (otwarta) · „klient zatrudnia: Java, QA” z rozmowy 08.10 · w bazie 212 pasujących”. */
function SeekingLine({ card }: { card: DepartmentCard }) {
  const signal = card.hiringSignals[0] ?? null;
  const baseHref = card.base.count != null && card.base.count > 0 ? candidatesHref(card.base.skills) : null;
  const parts: ReactNode[] = [
    ...card.openJobs.map((job) => (
      <Link key={`job-${job.id}`} href={`/jobs/${job.id}`} className="hover:underline">
        {job.title} (otwarta)
      </Link>
    )),
    signal ? (
      <span key="signal">
        „klient zatrudnia: {signal.roles.join(", ")}” z rozmowy {formatDayMonthPl(signal.on)}
      </span>
    ) : null,
  ].filter(Boolean);
  if (!parts.length) return null;
  if (card.base.count != null) {
    parts.push(
      baseHref ? (
        <Link key="base" href={baseHref} className="text-primary hover:underline">
          w bazie {card.base.count} pasujących
        </Link>
      ) : (
        <span key="base">w bazie {card.base.count} pasujących</span>
      ),
    );
  }
  return (
    <p className="text-xs">
      <span className="font-semibold text-warning-muted-foreground">Szukają: </span>
      {parts.map((part, index) => (
        <span key={index}>
          {index ? " · " : null}
          {part}
        </span>
      ))}
    </p>
  );
}

function DepartmentCardView({
  card,
  clientId,
  canCreateJob,
  canWriteFeedback,
  onFeedback,
}: {
  card: DepartmentCard;
  clientId: number;
  canCreateJob: boolean;
  canWriteFeedback: boolean;
  onFeedback: (target: FeedbackTarget) => void;
}) {
  const hiring = card.openJobs.length > 0;
  const lead = card.managers[0] ?? null;
  return (
    <article
      aria-label={`Dział ${card.area.name}`}
      className={cn(
        "flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3 text-sm",
        // Żółta ramka = dział ma otwartą rekrutację (makieta 22.10.2026).
        hiring ? "border-warning ring-1 ring-warning/40" : "border-border",
      )}
    >
      <header className="flex items-start justify-between gap-2">
        <h3 className="min-w-0 truncate font-semibold text-foreground">{card.area.name}</h3>
        {canCreateJob ? (
          <Button variant="ghost" size="sm" className="h-7 shrink-0 px-2" asChild>
            <Link
              href={jobsNewHref({
                clientId,
                hmId: lead?.id ?? null,
                skillIds: topSkillIds(card),
              })}
              title={`Nowa rekrutacja z działu ${card.area.name}`}
            >
              <BriefcaseBusiness className="size-3.5" aria-hidden />
              <span className="sr-only">Nowa rekrutacja z działu {card.area.name}</span>
            </Link>
          </Button>
        ) : null}
      </header>

      <ManagerLine card={card} canWriteFeedback={canWriteFeedback} onFeedback={onFeedback} />

      {card.consultants.length ? (
        <div>
          <h4 className={CALM_HEAD}>Nasi ({card.consultants.length})</h4>
          <ul className="space-y-0.5">
            {card.consultants.map((consultant) => (
              <li key={consultant.contract_id} className="min-w-0">
                <ConsultantRow consultant={consultant} />
              </li>
            ))}
          </ul>
        </div>
      ) : card.consultantsCount ? (
        <p className="text-xs text-muted-foreground">
          {countPl(card.consultantsCount, "nasz konsultant", "naszych konsultantów", "naszych konsultantów")}
        </p>
      ) : null}

      <div>
        <h4 className={CALM_HEAD}>Technologie działu · siła źródeł</h4>
        {card.technologies.length ? (
          <ul className="flex flex-wrap gap-x-3 gap-y-0.5" aria-label={`Technologie działu ${card.area.name}`}>
            {card.technologies.slice(0, TECH_ON_CARD).map((tech) => (
              <li key={tech.skill_id} className="whitespace-nowrap" title={strengthLabel(tech.source_count)}>
                <span className={cn(tech.stale && "text-muted-foreground")}>{tech.name}</span>{" "}
                <span aria-hidden className="text-[10px] tracking-tighter text-primary">
                  {strengthDots(tech.source_count)}
                </span>
                <span className="sr-only">{`, ${strengthLabel(tech.source_count)}`}</span>
              </li>
            ))}
            {card.technologiesTotal > Math.min(TECH_ON_CARD, card.technologies.length) ? (
              <li className="text-xs text-muted-foreground">
                +{card.technologiesTotal - Math.min(TECH_ON_CARD, card.technologies.length)}
              </li>
            ) : null}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">Żadne źródło nie wskazuje technologii.</p>
        )}
      </div>

      <SeekingLine card={card} />
      {card.gap ? (
        <p className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">Luka: </span>
          {card.gap}
        </p>
      ) : null}
    </article>
  );
}

/** „Przypisz dział” przy osobie klienta bez działu — ta sama trasa co drzewo. */
function AssignArea({ person, org, clientId }: { person: OrgPerson; org: ClientOrg; clientId: number }) {
  const { showToast } = useToast();
  const update = useUpdateContactOrg(clientId);
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button type="button" className="text-xs text-primary hover:underline" onClick={() => setOpen(true)}>
        Przypisz dział
      </button>
    );
  }
  return (
    <Select
      disabled={update.isPending}
      onValueChange={(value) =>
        update.mutate(
          { contactId: person.id, payload: { client_area_id: Number(value) } },
          {
            onSuccess: () => {
              setOpen(false);
              showToast("Dział zapisany", "success");
            },
            onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać działu."), "error"),
          },
        )
      }
    >
      <SelectTrigger aria-label={`Dział: ${person.name}`} className="h-7 w-full">
        <SelectValue placeholder="Wybierz dział…" />
      </SelectTrigger>
      <SelectContent>
        {org.areas.map((area) => (
          <SelectItem key={area.id} value={String(area.id)}>
            {area.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * Widok „Działy” (domyślny) zakładki „Ludzie i technologie”: karta na dział —
 * menedżer naszych z „Podlega pod”, nasi z kropką zdrowia (gdy serwer ją
 * podał), technologie działu słowem z kropkami siły (●●● = liczba rodzajów
 * źródeł), żółta ramka = otwarta rekrutacja, „Szukają: …” i luka działu.
 * Z prawej: luki do dopytania, ludzie klienta poza działami (z „Przypisz
 * dział”), dostawcy i notatki o stacku. Domyślnego opiekuna ustawia się
 * w „Zespole opiekunów” → „Ustawienia przydziału” (makieta P6). Działy bez sygnału schowane jak na
 * mapie (Nordea: 67 pustych działów).
 */
export function DepartmentsView({
  clientId,
  map,
  org,
  canCreateJob,
  onFeedback,
  onAddNote,
  onShowTree,
}: {
  clientId: number;
  map: ClientTechMap;
  org: ClientOrg | null;
  canCreateJob: boolean;
  onFeedback: (target: FeedbackTarget) => void;
  onAddNote: (() => void) | null;
  onShowTree: (() => void) | null;
}) {
  const [showAll, setShowAll] = useState(false);
  const cards = departmentCards(map, org);
  const withSignal = cards.filter((card) => card.hasSignal);
  const hidden = cards.length - withSignal.length;
  const visible = showAll ? cards : withSignal;
  const outside = peopleOutsideDepartments(org);
  const canWriteFeedback = org?.can_write_feedback === true;

  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div className="@container min-w-0 space-y-2" data-help="client.people.departments">
        {visible.length ? (
          <div className="grid gap-3 @2xl:grid-cols-2">
            {visible.map((card) => (
              <DepartmentCardView
                key={card.area.id}
                card={card}
                clientId={clientId}
                canCreateJob={canCreateJob}
                canWriteFeedback={canWriteFeedback}
                onFeedback={onFeedback}
              />
            ))}
          </div>
        ) : (
          <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
            {cards.length
              ? "Żaden dział nie ma jeszcze technologii, naszych konsultantów ani otwartych rekrutacji."
              : "Klient nie ma jeszcze działów — dodaje się je przy osobie w „Drzewie osób” albo w formularzu kontaktu."}
          </p>
        )}
        {hidden > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs text-muted-foreground"
            aria-expanded={showAll}
            onClick={() => setShowAll((value) => !value)}
          >
            {showAll ? "Schowaj działy bez sygnału" : `Pokaż wszystkie działy (${cards.length})`}
          </Button>
        ) : null}
      </div>

      <div className="grid content-start gap-3">
        <GapsCard gaps={map.gaps} clientId={clientId} onAddNote={onAddNote} />
        {org ? (
          <section className="space-y-2 rounded-lg border border-border bg-card p-4">
            <h3 className="text-sm font-semibold">Ludzie klienta poza działami</h3>
            {outside.length ? (
              <ul className="space-y-2 text-sm">
                {outside.map((person) => (
                  <li key={person.id} className="space-y-1">
                    <span>
                      <span className="font-medium">{person.name}</span>
                      <span className="text-muted-foreground">
                        {person.position ? ` · ${person.position}` : ""} · bez działu
                      </span>
                    </span>
                    {person.department_text ? (
                      <span className={CALM_SUBLINE}>W kontakcie: „{person.department_text}”</span>
                    ) : null}
                    {org.can_edit_org && org.areas.length ? (
                      <AssignArea person={person} org={org} clientId={clientId} />
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Każda osoba klienta ma dział.</p>
            )}
            {outside.length && onShowTree && !(org.can_edit_org && org.areas.length) ? (
              <button
                type="button"
                className="text-xs text-primary hover:underline"
                onClick={onShowTree}
              >
                Zobacz w „Drzewie osób”
              </button>
            ) : null}
          </section>
        ) : null}
        <section className="space-y-2 rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-semibold">Dostawcy u klienta</h3>
          <p className="text-sm">
            {map.vendors.length ? (
              map.vendors.map((vendor) => vendor.name).join(", ")
            ) : (
              <span className="text-muted-foreground">Nikt nie wskazał dostawców.</span>
            )}
          </p>
        </section>
        <section className="space-y-2 rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-semibold">Opiekun domyślny</h3>
          <DefaultOwner map={map} clientId={clientId} />
          <p className={CALM_SUBLINE}>Dostają go nowi konsultanci tego klienta.</p>
        </section>
        <section className="space-y-2 rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Notatki o stacku</h3>
            {onAddNote ? (
              <button type="button" className="text-xs text-primary hover:underline" onClick={onAddNote}>
                Dodaj
              </button>
            ) : null}
          </div>
          {map.notes.length ? (
            <ul className="space-y-2 text-sm">
              {map.notes.map((note) => (
                <li key={note.id}>
                  <span className="line-clamp-3 whitespace-pre-line">{note.content}</span>
                  <span className={CALM_SUBLINE}>{formatIsoDatePl(note.created_on)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Brak notatek o stacku.</p>
          )}
        </section>
      </div>
    </div>
  );
}

const DEFAULT_OWNER = "none";

/** Opiekun domyślny klienta — tu dla DL i opiekunów, w „Ustawieniach przydziału” dla head back office (decyzja Artura 22.10.2026). */
function DefaultOwner({ map, clientId }: { map: ClientTechMap; clientId: number }) {
  const { showToast } = useToast();
  const owners = useCareOwners(map.can_edit);
  const save = useSetClientDefaultOwner(clientId);
  if (!map.can_edit) {
    return <span className="text-sm">{map.default_owner?.name ?? "Delivery Lead kontraktu"}</span>;
  }
  return (
    <>
      <Select
        value={map.default_owner ? String(map.default_owner.id) : DEFAULT_OWNER}
        // Przy awarii listy wybór „Delivery Lead kontraktu” skasowałby opiekuna (audyt 22.10, F89).
        disabled={save.isPending || owners.isError}
        onValueChange={(next) =>
          save.mutate(next === DEFAULT_OWNER ? null : Number(next), {
            onSuccess: () => showToast("Domyślny opiekun zapisany", "success"),
            onError: (err) =>
              showToast(apiErrorMessage(err, "Nie udało się zapisać opiekuna."), "error"),
          })
        }
      >
        <SelectTrigger aria-label="Domyślny opiekun konsultantów klienta" className="h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={DEFAULT_OWNER}>Delivery Lead kontraktu</SelectItem>
          {/* Opiekun spoza listy (wykluczony z puli, nieaktywne konto) albo lista
              jeszcze/wcale nie wczytana — inaczej pole byłoby puste, jak gdyby
              opiekuna nie było. */}
          {map.default_owner && !(owners.data ?? []).some((o) => o.id === map.default_owner?.id) ? (
            <SelectItem value={String(map.default_owner.id)}>
              {map.default_owner.name}
              {owners.isSuccess ? " (spoza listy opiekunów)" : ""}
            </SelectItem>
          ) : null}
          {(owners.data ?? []).map((owner) => (
            <SelectItem key={owner.id} value={String(owner.id)}>
              {owner.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {owners.isError ? (
        <p className="text-xs text-destructive">
          {apiErrorMessage(owners.error, "Nie udało się wczytać listy opiekunów.")}
        </p>
      ) : null}
    </>
  );
}
