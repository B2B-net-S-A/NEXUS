"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import { useClientTechMap, type ClientTechMap } from "@/lib/api/care";
import { jobsNewHref } from "@/lib/api/care-clients";
import {
  canReadClientPeople,
  useClientOrg,
  type ClientOrg,
  type OrgPerson,
} from "@/lib/api/client-people";
import { hasCapability } from "@/lib/capabilities";
import { formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { ClientFeedbackDialog } from "../ClientFeedbackDialog";
import { ClientPeopleTab } from "../ClientPeopleTab";
import { ClientTechnologiesTab, StackNoteDialog } from "../ClientTechnologiesTab";
import { orgPeople } from "../client-people-format";
import type { FeedbackTarget } from "../PersonPanel";
import { ApprovalBar } from "./ApprovalBar";
import { DepartmentsView } from "./DepartmentsView";
import {
  PEOPLE_VIEW_LABELS,
  completeness,
  departmentCards,
  topSkillIds,
  type Completeness,
  type PeopleView,
} from "./people-tech-format";

function completenessLine(c: Completeness): string {
  return [
    countPl(c.consultants, "nasz konsultant", "naszych konsultantów", "naszych konsultantów"),
    `${c.departmentsWithOurs} z ${c.departmentsTotal} ${c.departmentsTotal === 1 ? "działu" : "działów"} z naszymi`,
    c.withManager !== null ? `${c.withManager} z ${c.consultants} z menedżerem` : null,
    c.mapOn ? `mapa z ${formatIsoDatePl(c.mapOn)}` : "mapa bez źródeł",
    c.requests !== null
      ? countPl(c.requests, "prośba o opinię", "prośby o opinię", "próśb o opinię")
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Zakładka klienta „Ludzie i technologie” (`?tab=ludzie`, decyzja 5 z makiet
 * 22.10.2026) — zastępuje „Strukturę u klienta” i „Technologie”. Widoki:
 * Działy (domyślny) · Drzewo osób (dawny `ClientPeopleTab`, krąg D11) · Mapa
 * (dawna mapa cieplna z kartami z Compassa). Nad widokami liczby
 * kompletności wiedzy i pasek „Do zatwierdzenia” z jedną propozycją
 * automatu. Drzewo czyta tylko krąg D11 — reszta (np. Finanse) widzi działy
 * z mapy, bez osób i opinii.
 */
export function ClientPeopleTechTab({
  clientId,
  view,
  onViewChange,
  proposalsOpen = false,
}: {
  clientId: number;
  view: PeopleView;
  onViewChange: (view: PeopleView) => void;
  /** Pełny panel propozycji automatu rozwinięty od wejścia. */
  proposalsOpen?: boolean;
}) {
  const user = useAuthStore((s) => s.user);
  const canReadPeople = canReadClientPeople(user);
  // `/jobs/new` odsyła na listę każdego bez `job.create` (np. TCM).
  const canCreateJob = !!user && hasCapability(user, "job.create");
  const mapQuery = useClientTechMap(clientId);
  const orgQuery = useClientOrg(clientId, canReadPeople);
  const [feedback, setFeedback] = useState<FeedbackTarget | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);

  const current: PeopleView = view === "drzewo" && !canReadPeople ? "dzialy" : view;
  const viewOptions = (["dzialy", "drzewo", "mapa"] as const)
    .filter((key) => key !== "drzewo" || canReadPeople)
    .map((key) => ({ value: key, label: PEOPLE_VIEW_LABELS[key] }));

  const mapState = resolveViewState({
    isLoading: mapQuery.isLoading,
    isError: mapQuery.isError,
    error: mapQuery.error,
    isSuccess: mapQuery.isSuccess,
  });
  const org = orgQuery.data ?? null;
  const map = mapQuery.data ?? null;
  const orgFailed = canReadPeople && orgQuery.isError;

  const switcher = (
    <SegmentedRadio
      label="Widok zakładki Ludzie i technologie"
      size="sm"
      value={current}
      onChange={onViewChange}
      options={viewOptions}
    />
  );

  // Drzewo i mapa mają własne stany ładowania i błędów — nie czekają na drugie zapytanie.
  const header = (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2">
      <p className="min-w-0 text-sm text-muted-foreground" data-people-tech-completeness>
        {map ? completenessLine(completeness(map, org)) : "Wczytywanie liczb klienta…"}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {org?.can_write_feedback ? (
          <FeedbackPicker
            people={orgPeople(org)}
            requests={org.requests.map((request) => request.contact_id)}
            onPick={setFeedback}
          />
        ) : null}
        {canCreateJob && map ? <NewJobPicker clientId={clientId} map={map} org={org} /> : null}
      </div>
    </div>
  );

  let body: ReactNode;
  if (current === "drzewo") {
    body = <ClientPeopleTab clientId={clientId} showProposals={false} />;
  } else if (current === "mapa") {
    body = <ClientTechnologiesTab clientId={clientId} />;
  } else if (mapState === "loading") {
    body = <p className="p-4 text-sm text-muted-foreground">Wczytywanie działów klienta…</p>;
  } else if (!map) {
    body = (
      <QueryStateNotice
        state={mapState === "forbidden" || mapState === "not_found" ? mapState : "error"}
        description={
          mapState === "forbidden" || mapState === "not_found"
            ? apiErrorMessage(mapQuery.error, "Nie możesz zobaczyć działów tego klienta.")
            : undefined
        }
        onRetry={() => mapQuery.refetch()}
      />
    );
  } else {
    body = (
      <DepartmentsView
        clientId={clientId}
        map={map}
        org={org}
        canCreateJob={canCreateJob}
        onFeedback={setFeedback}
        onAddNote={map.can_edit ? () => setNoteOpen(true) : null}
        onShowTree={canReadPeople ? () => onViewChange("drzewo") : null}
      />
    );
  }

  return (
    <div className="space-y-3">
      {header}
      <div className="flex flex-wrap items-center gap-2">{switcher}</div>
      {canReadPeople ? <ApprovalBar clientId={clientId} defaultExpanded={proposalsOpen} /> : null}
      {orgFailed && current === "dzialy" ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(orgQuery.error, "Nie udało się wczytać osób klienta")} — karty działów
          pokazują menedżerów z mapy.{" "}
          <button
            type="button"
            className="font-medium text-primary underline-offset-2 hover:underline"
            onClick={() => orgQuery.refetch()}
          >
            Spróbuj ponownie
          </button>
        </p>
      ) : null}
      {body}

      {feedback && org ? (
        <ClientFeedbackDialog
          clientId={clientId}
          clientName={org.client_name}
          manager={feedback.manager}
          consultants={feedback.consultants}
          open
          onOpenChange={(open) => {
            if (!open) setFeedback(null);
          }}
        />
      ) : null}
      {noteOpen ? <StackNoteDialog clientId={clientId} onClose={() => setNoteOpen(false)} /> : null}
    </div>
  );
}

/** „Zapisz opinię menedżera” — wybór menedżera (najpierw ci z prośbą o opinię). */
function FeedbackPicker({
  people,
  requests,
  onPick,
}: {
  people: OrgPerson[];
  requests: number[];
  onPick: (target: FeedbackTarget) => void;
}) {
  const managers = people
    .filter((person) => person.is_manager || person.consultants.length > 0)
    .sort(
      (a, b) =>
        Number(requests.includes(b.id)) - Number(requests.includes(a.id)) ||
        a.name.localeCompare(b.name, "pl"),
    );
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          Zapisz opinię menedżera
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel>Rozmowa z menedżerem u klienta</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {managers.length ? (
          managers.map((person) => (
            <DropdownMenuItem
              key={person.id}
              onSelect={() =>
                onPick({
                  manager: { id: person.id, name: person.name },
                  consultants: person.consultants,
                })
              }
            >
              <span className="min-w-0 flex-1 truncate">{person.name}</span>
              {requests.includes(person.id) ? (
                <span className="text-xs text-warning-muted-foreground">prośba</span>
              ) : (
                <span className="text-xs text-muted-foreground">
                  {countPl(person.consultants.length, "osoba", "osoby", "osób")}
                </span>
              )}
            </DropdownMenuItem>
          ))
        ) : (
          <DropdownMenuItem disabled>Nikt nie jest jeszcze menedżerem naszych</DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** „Nowa rekrutacja z działu” — `/jobs/new` z klientem, menedżerem działu i jego technologiami. */
function NewJobPicker({
  clientId,
  map,
  org,
}: {
  clientId: number;
  map: ClientTechMap;
  org: ClientOrg | null;
}) {
  const cards = departmentCards(map, org).filter((card) => card.hasSignal);
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button size="sm">
          Nowa rekrutacja z działu
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel>Dział klienta</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {cards.map((card) => (
          <DropdownMenuItem key={card.area.id} asChild>
            <Link
              href={jobsNewHref({
                clientId,
                hmId: card.managers[0]?.id ?? null,
                skillIds: topSkillIds(card),
              })}
            >
              <span className="min-w-0 flex-1 truncate">{card.area.name}</span>
              {card.managers[0] ? (
                <span className="truncate text-xs text-muted-foreground">{card.managers[0].name}</span>
              ) : null}
            </Link>
          </DropdownMenuItem>
        ))}
        {cards.length ? <DropdownMenuSeparator /> : null}
        <DropdownMenuItem asChild>
          <Link href={jobsNewHref({ clientId })}>Bez działu</Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
