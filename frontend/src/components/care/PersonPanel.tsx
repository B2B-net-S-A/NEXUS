"use client";

import Link from "next/link";

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
import {
  useUpdateContactOrg,
  type ClientOrg,
  type ContactOrgPayload,
  type OrgConsultant,
  type OrgPerson,
} from "@/lib/api/client-people";
import { CALM_EMPTY, CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { AreaPicker, NONE } from "./AreaPicker";
import {
  endLabel,
  feedbackLabel,
  managerOptions,
  orgPeople,
  reasonsLabel,
} from "./client-people-format";

export interface FeedbackTarget {
  manager: { id: number; name: string };
  consultants: OrgConsultant[];
}

export function ConsultantLine({ consultant }: { consultant: OrgConsultant }) {
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

export function PersonPanel({
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
          // `key`: wpisywana nazwa nowego działu należy do tej osoby, nie do następnej.
          <AreaPicker
            key={person.id}
            org={org}
            person={person}
            saving={update.isPending}
            onSave={save}
          />
        ) : (
          <p>
            {org.areas.find((area) => area.id === person.area_id)?.name ??
              person.department_text ?? <span className={CALM_EMPTY}>—</span>}
          </p>
        )}
      </div>

      {person.subordinates.length ? (
        <div className={section}>
          <h4 className={CALM_HEAD}>Zespół</h4>
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
