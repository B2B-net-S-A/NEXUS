"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Users } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useClientOrg, type OrgPerson } from "@/lib/api/client-people";
import { useClientStructureProposals } from "@/lib/api/structure-proposals";
import { CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { ClientFeedbackDialog } from "./ClientFeedbackDialog";
import { feedbackLabel, orgPeople, reasonsLabel } from "./client-people-format";
import { ConsultantLine, PersonPanel, type FeedbackTarget } from "./PersonPanel";
import { StructureProposalsPanel } from "./structure/StructureProposalsPanel";

function Marker({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex items-center rounded border border-border px-1.5 text-[11px] leading-4 text-muted-foreground"
    >
      {children}
    </span>
  );
}

function PersonRow({
  person,
  selected,
  onSelect,
}: {
  person: OrgPerson;
  selected: boolean;
  onSelect: (id: number) => void;
}) {
  // Wcięcie po „Podlega pod” — głębokość z serwera, przycięta, żeby długi
  // łańcuch nie wypchnął nazwiska z wąskiego kontenera.
  const indent = { paddingLeft: `${0.5 + Math.min(person.depth, 6) * 1.25}rem` };
  return (
    <li className="border-b border-border/60 last:border-b-0">
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => onSelect(person.id)}
        style={indent}
        className={cn(
          "flex w-full flex-wrap items-center gap-x-2 gap-y-1 py-1.5 pr-3 text-left text-sm hover:bg-muted/60",
          selected && "bg-muted",
        )}
      >
        <span className="font-medium text-foreground">{person.name}</span>
        {person.position ? (
          <span className="text-muted-foreground">{person.position}</span>
        ) : null}
        {person.is_manager ? (
          <Marker title="Menedżer naszych konsultantów u klienta">
            menedżer naszych · {person.consultants.length}
          </Marker>
        ) : null}
        {person.is_hiring_manager ? (
          <Marker title="Hiring manager w rekrutacjach klienta">HM</Marker>
        ) : null}
        {person.is_decision_maker ? <Marker>decydent</Marker> : null}
        {person.feedback_request ? (
          <StatusDot tone={person.feedback_request.overdue ? "warning" : "info"}>
            prośba o opinię
          </StatusDot>
        ) : null}
        {person.is_manager ? (
          <span className="ml-auto text-xs text-muted-foreground">
            {feedbackLabel(person.last_feedback)}
          </span>
        ) : null}
      </button>
      {person.consultants.length ? (
        <ul
          className="pb-1.5 text-xs"
          style={{ paddingLeft: `${1.75 + Math.min(person.depth, 6) * 1.25}rem` }}
        >
          {person.consultants.map((consultant) => (
            <li key={consultant.contract_id} className="py-0.5 pr-3">
              <ConsultantLine consultant={consultant} />
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/**
 * Propozycje automatu nad drzewem (decyzja Artura 18.10.2026 „Propozycja
 * automatu + akcept DL”) — zwinięte, żeby drzewo zostało głównym widokiem.
 * Awaria propozycji nie zasłania drzewa: sekcja wtedy znika.
 */
function ProposalsSection({ clientId }: { clientId: number }) {
  const query = useClientStructureProposals(clientId);
  const [open, setOpen] = useState(false);
  const data = query.data;
  if (!data) return null;
  const c = data.counts;
  const orgOpen = data.reports_to.filter((row) => !row.skipped).length;
  if (!c.open && !orgOpen && !open) return null;
  const summary = [
    c.open ? `${countPl(c.open, "konsultant", "konsultantów", "konsultantów")} bez menedżera` : null,
    c.certain ? countPl(c.certain, "pewna propozycja", "pewne propozycje", "pewnych propozycji") : null,
    orgOpen
      ? `${countPl(orgOpen, "propozycja", "propozycje", "propozycji")} „Podlega pod”`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <section aria-label="Propozycje struktury" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm">
        <span>
          <span className="font-medium">Propozycje automatu</span>
          {summary ? <span className="text-muted-foreground"> · {summary}</span> : null}
        </span>
        <Button
          variant="outline"
          size="sm"
          className="h-7"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Zwiń propozycje" : "Przejrzyj propozycje"}
        </Button>
      </div>
      {open ? <StructureProposalsPanel clientId={clientId} /> : null}
    </section>
  );
}

/**
 * Drzewo osób klienta (etap 2, 17.10.2026; od 22.10.2026 widok „Drzewo osób”
 * zakładki „Ludzie i technologie”): działy → osoby klienta z wcięciem po
 * „Podlega pod” → nasi konsultanci pod menedżerem; panel osoby z edycją
 * „Podlega pod” i „Dział” oraz zapisem opinii (D8–D11). Zakładka ma nad
 * widokami własny pasek „Do zatwierdzenia” — wtedy `showProposals={false}`.
 */
export function ClientPeopleTab({
  clientId,
  showProposals = true,
}: {
  clientId: number;
  showProposals?: boolean;
}) {
  const query = useClientOrg(clientId);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<FeedbackTarget | null>(null);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: !query.data || (query.data.people_count === 0 && query.data.consultants_count === 0),
  });
  if (state === "loading") {
    return <p className="p-4 text-sm text-muted-foreground">Wczytywanie struktury u klienta…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "forbidden" || state === "not_found"
            ? apiErrorMessage(query.error, "Nie możesz zobaczyć struktury tego klienta.")
            : undefined
        }
        onRetry={() => query.refetch()}
      />
    );
  }
  const org = query.data;
  if (state === "empty") {
    return (
      <EmptyState
        icon={Users}
        title="Nie ma jeszcze osób klienta ani naszych konsultantów"
        description="Osoby klienta dodaje się w zakładce „Kontakty klienta”; konsultanci pojawią się z aktywnymi kontraktami."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href={`/clients/${clientId}?tab=kontakty`}>Kontakty klienta</Link>
          </Button>
        }
      />
    );
  }
  const people = orgPeople(org);
  const selected = people.find((person) => person.id === selectedId) ?? null;
  const openFeedbackFor = (contactId: number) => {
    const person = people.find((p) => p.id === contactId);
    const request = org.requests.find((r) => r.contact_id === contactId);
    if (!person && !request) return;
    setFeedback({
      manager: { id: contactId, name: person?.name ?? request?.contact_name ?? "" },
      consultants: person?.consultants ?? request?.consultants ?? [],
    });
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <InlineStats
          id="care-org-stats"
          stats={[
            { id: "people", label: "osób klienta", value: org.people_count },
            { id: "consultants", label: "naszych konsultantów", value: org.consultants_count },
            { id: "requests", label: "prośby o opinię", value: org.requests.length },
            { id: "without", label: "bez menedżera", value: org.without_manager.length },
          ]}
        />
        <Button variant="outline" size="sm" asChild>
          <Link href={`/clients/${clientId}?tab=kontakty`}>Kontakty klienta</Link>
        </Button>
      </div>

      {showProposals ? <ProposalsSection clientId={clientId} /> : null}

      {org.requests.length ? (
        <section
          aria-labelledby="care-org-requests"
          className="rounded-lg border border-border bg-card p-3"
        >
          <h3 id="care-org-requests" className="text-sm font-semibold">
            Prośby o opinię ({org.requests.length})
          </h3>
          <ul className="mt-1.5 divide-y divide-border/60">
            {org.requests.map((request) => (
              <li
                key={request.contact_id}
                className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-sm"
              >
                <span className="min-w-0">
                  <button
                    type="button"
                    className="font-medium hover:underline"
                    onClick={() => setSelectedId(request.contact_id)}
                  >
                    {request.contact_name}
                  </button>
                  <span className="text-muted-foreground">
                    {" · "}
                    {request.consultants
                      .map((c) => c.candidate_name ?? `#${c.contract_id}`)
                      .join(", ")}
                    {" · "}
                    {reasonsLabel(request.reasons)} · {feedbackLabel(request.last_feedback)}
                  </span>
                </span>
                {org.can_write_feedback ? (
                  <Button size="sm" onClick={() => openFeedbackFor(request.contact_id)}>
                    Zapisz opinię
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div
          role="region"
          aria-label="Struktura u klienta"
          className="max-h-[calc(100dvh-17rem)] min-h-64 overflow-y-auto rounded-lg border border-border bg-card"
        >
          {org.departments.map((department) => (
            <section key={department.area?.id ?? "none"} aria-label={department.area?.name ?? "Bez działu"}>
              <h3
                className={cn(
                  CALM_HEAD,
                  "sticky top-0 z-10 border-b border-border/60 bg-card px-3 py-1.5",
                )}
              >
                {department.area?.name ?? "Bez działu"}
                <span className="ml-1.5 normal-case tracking-normal">
                  · {department.people.length}
                </span>
              </h3>
              <ul>
                {department.people.map((person) => (
                  <PersonRow
                    key={person.id}
                    person={person}
                    selected={person.id === selectedId}
                    onSelect={setSelectedId}
                  />
                ))}
              </ul>
            </section>
          ))}
          {org.without_manager.length ? (
            <section aria-label="Bez wskazanego menedżera">
              <h3
                className={cn(
                  CALM_HEAD,
                  "sticky top-0 z-10 border-b border-border/60 bg-card px-3 py-1.5",
                )}
              >
                Bez wskazanego menedżera
                <span className="ml-1.5 normal-case tracking-normal">
                  · {org.without_manager.length}
                </span>
              </h3>
              <ul className="text-xs">
                {org.without_manager.map((row) => (
                  <li
                    key={row.contract_id}
                    className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3 py-1.5 last:border-b-0"
                  >
                    <span className="min-w-0">
                      <ConsultantLine consultant={row} />
                      {row.line_manager || row.client_pm_name ? (
                        <span className={CALM_SUBLINE}>
                          {row.line_manager
                            ? `Line Manager (tekst): „${row.line_manager}”`
                            : `PM (tekst): „${row.client_pm_name}”`}
                          {row.hint ? ` · podpowiedź: ${row.hint.name}` : ""}
                        </span>
                      ) : null}
                      {row.manager_outside_client ? (
                        <span className={CALM_SUBLINE}>
                          Wskazany menedżer jest kontaktem innego klienta.
                        </span>
                      ) : null}
                    </span>
                    <Button variant="outline" size="sm" className="h-7" asChild>
                      <Link href={`/contracts/${row.contract_id}`}>Wskaż menedżera</Link>
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>

        <div className="xl:sticky xl:top-0 xl:self-start">
          <PersonPanel
            org={org}
            person={selected}
            clientId={clientId}
            onSelect={setSelectedId}
            onFeedback={setFeedback}
          />
        </div>
      </div>

      {feedback ? (
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
    </div>
  );
}
