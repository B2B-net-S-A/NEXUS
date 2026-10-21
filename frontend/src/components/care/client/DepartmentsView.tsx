"use client";

import { useState } from "react";
import Link from "next/link";
import { BriefcaseBusiness } from "lucide-react";

import { Button } from "@/components/ui/button";
import { HEALTH_DOT } from "@/lib/api/care-board";
import { consultantHealth, jobsNewHref } from "@/lib/api/care-clients";
import type { ClientTechMap } from "@/lib/api/care";
import type { ClientOrg, OrgConsultant } from "@/lib/api/client-people";
import { CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";

import { DefaultOwner, GapsCard } from "../ClientTechnologiesTab";
import type { FeedbackTarget } from "../PersonPanel";
import {
  departmentCards,
  peopleOutsideDepartments,
  strengthDots,
  strengthLabel,
  topSkillIds,
  type DepartmentCard,
} from "./people-tech-format";

/** Ile technologii działu stoi na karcie — reszta liczbą („+4”). */
const TECH_ON_CARD = 6;

function ConsultantChip({ consultant }: { consultant: OrgConsultant }) {
  const health = consultantHealth(consultant);
  const name = consultant.candidate_name ?? `Kontrakt #${consultant.contract_id}`;
  return (
    <Link
      href={`/care?contract=${consultant.contract_id}`}
      title={
        health
          ? `${name} · ${health.label}${health.reasons.length ? ` — ${health.reasons.join(", ")}` : ""}`
          : name
      }
      className="inline-flex items-center gap-1 rounded-md border border-border/70 px-1.5 py-0.5 text-xs hover:bg-muted"
    >
      {health ? (
        <span
          aria-hidden
          className={cn("size-1.5 shrink-0 rounded-full", HEALTH_DOT[health.level])}
        />
      ) : null}
      <span className="truncate">{name}</span>
      {health ? <span className="sr-only">{`, ${health.label}`}</span> : null}
    </Link>
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
        <div className="min-w-0">
          <h3 className="truncate font-semibold text-foreground">{card.area.name}</h3>
          <p className={CALM_SUBLINE}>
            {[
              countPl(card.consultantsCount, "nasz konsultant", "naszych konsultantów", "naszych konsultantów"),
              hiring
                ? countPl(card.openJobs.length, "otwarta rekrutacja", "otwarte rekrutacje", "otwartych rekrutacji")
                : null,
              card.lastSeen ? `źródło z ${formatIsoDatePl(card.lastSeen)}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
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

      <div>
        <h4 className={CALM_HEAD}>Menedżer naszych</h4>
        {card.managers.length ? (
          <ul className="space-y-1">
            {card.managers.map((manager) => (
              <li key={manager.id} className="flex flex-wrap items-baseline gap-x-1.5">
                <span className="font-medium">{manager.name}</span>
                {manager.position ? (
                  <span className="text-xs text-muted-foreground">{manager.position}</span>
                ) : null}
                <span className="text-xs text-muted-foreground">
                  · podlega pod: {manager.reportsTo ?? "—"}
                </span>
                {canWriteFeedback ? (
                  <button
                    type="button"
                    className="text-xs text-primary hover:underline"
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
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">nie wskazano</p>
        )}
      </div>

      {card.consultants.length ? (
        <div>
          <h4 className={CALM_HEAD}>Nasi</h4>
          <ul className="flex flex-wrap gap-1">
            {card.consultants.map((consultant) => (
              <li key={consultant.contract_id} className="min-w-0 max-w-full">
                <ConsultantChip consultant={consultant} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div>
        <h4 className={CALM_HEAD}>Technologie</h4>
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

      {card.seeking.length ? (
        <p className="text-xs">
          <span className="font-semibold text-warning-muted-foreground">Szukają: </span>
          {card.seeking.join(", ")}
        </p>
      ) : null}
      {card.gap ? (
        <p className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">Luka: </span>
          {card.gap}
        </p>
      ) : null}
    </article>
  );
}

/**
 * Widok „Działy” (domyślny) zakładki „Ludzie i technologie”: karta na dział —
 * menedżer naszych z „Podlega pod”, nasi z kropką zdrowia (gdy serwer ją
 * podał), technologie działu słowem z kropkami siły (●●● = liczba rodzajów
 * źródeł), żółta ramka = otwarta rekrutacja, „Szukają: …” i luka działu.
 * Z prawej: luki do dopytania, ludzie klienta poza działami, dostawcy,
 * notatki o stacku i domyślny opiekun. Działy bez sygnału schowane jak na
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
      <div className="@container min-w-0 space-y-2">
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
              <ul className="space-y-1 text-sm">
                {outside.map((person) => (
                  <li key={person.id}>
                    <span className="font-medium">{person.name}</span>
                    {person.position ? (
                      <span className="text-muted-foreground"> · {person.position}</span>
                    ) : null}
                    {person.department_text ? (
                      <span className={CALM_SUBLINE}>W kontakcie: „{person.department_text}”</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Każda osoba klienta ma dział.</p>
            )}
            {outside.length && onShowTree ? (
              <button
                type="button"
                className="text-xs text-primary hover:underline"
                onClick={onShowTree}
              >
                Przypisz dział w „Drzewie osób”
              </button>
            ) : null}
          </section>
        ) : null}
        <section className="space-y-2 rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-semibold">Dostawcy i opiekun</h3>
          <p className="text-sm">
            {map.vendors.length ? (
              map.vendors.map((vendor) => vendor.name).join(", ")
            ) : (
              <span className="text-muted-foreground">Nikt nie wskazał dostawców.</span>
            )}
          </p>
          <div className="grid gap-1">
            <span className="text-xs text-muted-foreground">Domyślny opiekun konsultantów</span>
            <DefaultOwner map={map} clientId={clientId} />
          </div>
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
