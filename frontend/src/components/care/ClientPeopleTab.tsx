"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Users } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useClientOrg,
  useUpdateContactOrg,
  type ClientOrg,
  type ContactOrgPayload,
  type OrgConsultant,
  type OrgPerson,
} from "@/lib/api/client-people";
import { CALM_EMPTY, CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { ClientFeedbackDialog } from "./ClientFeedbackDialog";
import {
  endLabel,
  feedbackLabel,
  managerOptions,
  orgPeople,
  reasonsLabel,
} from "./client-people-format";

const NONE = "none";
const NEW_AREA = "__new__";

interface FeedbackTarget {
  manager: { id: number; name: string };
  consultants: OrgConsultant[];
}

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

function ConsultantLine({ consultant }: { consultant: OrgConsultant }) {
  return (
    <span className="min-w-0">
      <Link href={`/contracts/${consultant.contract_id}`} className="font-medium hover:underline">
        {consultant.candidate_name ?? `Kontrakt #${consultant.contract_id}`}
      </Link>
      <span className="text-muted-foreground">
        {" · "}
        {[consultant.role, endLabel(consultant)].filter(Boolean).join(" · ")}
        {" · "}
        {feedbackLabel(consultant.last_feedback)}
      </span>
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

function AreaPicker({
  org,
  person,
  saving,
  onSave,
}: {
  org: ClientOrg;
  person: OrgPerson;
  saving: boolean;
  onSave: (payload: ContactOrgPayload) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const value = person.area_id != null ? String(person.area_id) : NONE;
  return (
    <div className="grid gap-1.5">
      <Select
        value={adding ? NEW_AREA : value}
        disabled={saving}
        onValueChange={(next) => {
          if (next === NEW_AREA) {
            setAdding(true);
            return;
          }
          setAdding(false);
          onSave({ client_area_id: next === NONE ? null : Number(next) });
        }}
      >
        <SelectTrigger aria-label="Dział" className="h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>Bez działu</SelectItem>
          {org.areas.map((area) => (
            <SelectItem key={area.id} value={String(area.id)}>
              {area.name}
            </SelectItem>
          ))}
          <SelectItem value={NEW_AREA}>Nowy dział…</SelectItem>
        </SelectContent>
      </Select>
      {adding ? (
        <div className="flex gap-1.5">
          <Input
            aria-label="Nazwa nowego działu"
            value={name}
            maxLength={120}
            autoFocus
            placeholder="np. Płatności"
            onChange={(event) => setName(event.target.value)}
            className="h-8"
          />
          <Button
            size="sm"
            disabled={!name.trim() || saving}
            onClick={() => {
              onSave({ new_area_name: name.trim() });
              setAdding(false);
              setName("");
            }}
          >
            Dodaj
          </Button>
        </div>
      ) : null}
      {person.department_hint ? (
        <p className="text-xs text-muted-foreground">
          W kontakcie: „{person.department_text}”.{" "}
          <button
            type="button"
            disabled={saving}
            className="text-primary hover:underline disabled:opacity-50"
            onClick={() =>
              onSave(
                person.department_hint?.area_id != null
                  ? { client_area_id: person.department_hint.area_id }
                  : { new_area_name: person.department_hint?.name ?? "" },
              )
            }
          >
            {person.department_hint.area_id != null
              ? `Przypisz: ${person.department_hint.name}`
              : `Dodaj dział „${person.department_hint.name}”`}
          </button>
        </p>
      ) : null}
    </div>
  );
}

function PersonPanel({
  org,
  person,
  clientId,
  onSelect,
  onFeedback,
}: {
  org: ClientOrg;
  person: OrgPerson | null;
  clientId: number;
  onSelect: (id: number) => void;
  onFeedback: (target: FeedbackTarget) => void;
}) {
  const { showToast } = useToast();
  const update = useUpdateContactOrg(clientId);
  if (!person) {
    return (
      <aside className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
        Wybierz osobę z drzewa, żeby zobaczyć jej konsultantów, rekrutacje i opinie.
      </aside>
    );
  }
  const people = orgPeople(org);
  const save = (payload: ContactOrgPayload) =>
    update.mutate(
      { contactId: person.id, payload },
      {
        onSuccess: () => showToast("Struktura zapisana", "success"),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się zapisać struktury."), "error"),
      },
    );
  const section = "space-y-1.5 border-t border-border/60 pt-3";
  return (
    <aside
      aria-label={`Osoba: ${person.name}`}
      className="space-y-3 rounded-lg border border-border bg-card p-4 text-sm"
    >
      <div>
        <h3 className="font-display text-base font-semibold">{person.name}</h3>
        <p className="text-muted-foreground">{person.position ?? "Stanowisko nieznane"}</p>
        {person.email || person.phone ? (
          <p className={CALM_SUBLINE}>{[person.email, person.phone].filter(Boolean).join(" · ")}</p>
        ) : null}
      </div>

      <div className={section}>
        <h4 className={CALM_HEAD}>Podlega pod</h4>
        {org.can_edit_org ? (
          <Select
            value={person.reports_to ? String(person.reports_to.id) : NONE}
            disabled={update.isPending}
            onValueChange={(next) =>
              save({ reports_to_contact_id: next === NONE ? null : Number(next) })
            }
          >
            <SelectTrigger aria-label="Podlega pod" className="h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Nikt (najwyżej w strukturze)</SelectItem>
              {managerOptions(people, person).map((option) => (
                <SelectItem key={option.id} value={String(option.id)}>
                  {option.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <p>{person.reports_to?.name ?? <span className={CALM_EMPTY}>—</span>}</p>
        )}
        <h4 className={cn(CALM_HEAD, "pt-1.5")}>Dział</h4>
        {org.can_edit_org ? (
          <AreaPicker org={org} person={person} saving={update.isPending} onSave={save} />
        ) : (
          <p>
            {org.areas.find((area) => area.id === person.area_id)?.name ??
              person.department_text ?? <span className={CALM_EMPTY}>—</span>}
          </p>
        )}
      </div>

      {person.subordinates.length ? (
        <div className={section}>
          <h4 className={CALM_HEAD}>Podwładni</h4>
          <ul className="flex flex-wrap gap-1.5">
            {person.subordinates.map((sub) => (
              <li key={sub.id}>
                <Button variant="ghost" size="sm" className="h-7" onClick={() => onSelect(sub.id)}>
                  {sub.name}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className={section}>
        <h4 className={CALM_HEAD}>Nasi konsultanci</h4>
        {person.consultants.length ? (
          <ul className="space-y-1 text-xs">
            {person.consultants.map((consultant) => (
              <li key={consultant.contract_id}>
                <ConsultantLine consultant={consultant} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">
            Żaden kontrakt nie wskazuje tej osoby jako menedżera u klienta.
          </p>
        )}
      </div>

      {person.hiring_manager_jobs.length ? (
        <div className={section}>
          <h4 className={CALM_HEAD}>Hiring manager w rekrutacjach</h4>
          <ul className="space-y-0.5 text-xs">
            {person.hiring_manager_jobs.map((job) => (
              <li key={job.id}>
                <Link href={`/jobs/${job.id}`} className="hover:underline">
                  {job.title}
                </Link>
                {job.status === "closed" ? (
                  <span className="text-muted-foreground"> · zamknięta</span>
                ) : null}
              </li>
            ))}
          </ul>
          {person.hiring_manager_jobs_total > person.hiring_manager_jobs.length ? (
            <p className="text-xs text-muted-foreground">
              i {person.hiring_manager_jobs_total - person.hiring_manager_jobs.length} starszych
            </p>
          ) : null}
        </div>
      ) : null}

      <div className={section}>
        <h4 className={CALM_HEAD}>Opinia od klienta</h4>
        <p className="text-xs">{feedbackLabel(person.last_feedback)}</p>
        {person.feedback_request ? (
          <p className="text-xs text-muted-foreground">
            Prośba: {reasonsLabel(person.feedback_request.reasons)} · od{" "}
            {formatIsoDatePl(person.feedback_request.due_on)}
          </p>
        ) : null}
        {org.can_write_feedback ? (
          <Button
            size="sm"
            variant={person.feedback_request ? "primary" : "outline"}
            onClick={() =>
              onFeedback({
                manager: { id: person.id, name: person.name },
                consultants: person.consultants,
              })
            }
          >
            Zapisz opinię
          </Button>
        ) : null}
      </div>
    </aside>
  );
}

/**
 * Zakładka klienta „Struktura u klienta” (etap 2, 17.10.2026): działy → osoby
 * klienta z wcięciem po „Podlega pod” → nasi konsultanci pod menedżerem;
 * panel osoby z edycją „Podlega pod” i „Dział” oraz zapisem opinii (D8–D11).
 */
export function ClientPeopleTab({ clientId }: { clientId: number }) {
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
