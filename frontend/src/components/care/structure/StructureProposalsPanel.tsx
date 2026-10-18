"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Check, Undo2 } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
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
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CONFIDENCE_LABELS,
  SOURCE_LABELS,
  certainManagerChoices,
  certainReportsToChoices,
  useApplyManagers,
  useApplyReportsTo,
  useClientStructureProposals,
  useSkipProposal,
  type ApplyResult,
  type ClientStructureProposals,
  type ManagerChoice,
  type ManagerProposal,
  type ProposalCandidate,
  type ProposalConfidence,
  type ProposalPerson,
  type ReportsToProposal,
  type SkipKind,
} from "@/lib/api/structure-proposals";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

const TONE: Record<ProposalConfidence, StatusDotTone> = {
  certain: "success",
  uncertain: "warning",
  none: "neutral",
};
const NEW_PERSON = "__new__";

function personLabel(person: ProposalPerson | null): string {
  if (!person) return "—";
  return [person.name, person.position].filter(Boolean).join(" · ");
}

/** „z: „Line Manager” na kontrakcie (Anna Nowak) · hiring manager rekrutacji (Java)” */
export function sourcesLabel(candidate: ProposalCandidate): string {
  return candidate.sources
    .map((s) => (s.detail ? `${SOURCE_LABELS[s.source]} (${s.detail})` : SOURCE_LABELS[s.source]))
    .join(" · ");
}

function ConfidenceDot({ confidence }: { confidence: ProposalConfidence }) {
  return <StatusDot tone={TONE[confidence]}>{CONFIDENCE_LABELS[confidence]}</StatusDot>;
}

interface ChangeChoice {
  contactId?: number;
  newPersonName?: string;
  newPersonPosition?: string;
}

/** „Zmień”: osoba klienta z listy albo nowa osoba (tylko przy menedżerze). */
function ChangePicker({
  people,
  excludeId,
  allowNewPerson,
  busy,
  onSave,
  onCancel,
}: {
  people: ProposalPerson[];
  excludeId?: number;
  allowNewPerson: boolean;
  busy: boolean;
  onSave: (choice: ChangeChoice) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState<string>("");
  const [name, setName] = useState("");
  const [position, setPosition] = useState("");
  const isNew = value === NEW_PERSON;
  const ready = isNew ? name.trim().split(/\s+/).length >= 2 : value !== "";
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2">
      <Select value={value} onValueChange={setValue} disabled={busy}>
        <SelectTrigger aria-label="Wybierz osobę klienta" className="h-8 w-64">
          <SelectValue placeholder="Wybierz osobę klienta" />
        </SelectTrigger>
        <SelectContent>
          {people
            .filter((p) => p.id !== excludeId)
            .map((p) => (
              <SelectItem key={p.id} value={String(p.id)}>
                {personLabel(p)}
              </SelectItem>
            ))}
          {allowNewPerson ? <SelectItem value={NEW_PERSON}>Nowa osoba…</SelectItem> : null}
        </SelectContent>
      </Select>
      {isNew ? (
        <>
          <Input
            aria-label="Imię i nazwisko"
            placeholder="Imię i nazwisko"
            className="h-8 w-48"
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
          />
          <Input
            aria-label="Stanowisko"
            placeholder="Stanowisko (opcjonalnie)"
            className="h-8 w-48"
            value={position}
            maxLength={500}
            onChange={(e) => setPosition(e.target.value)}
          />
        </>
      ) : null}
      <Button
        size="sm"
        className="h-8"
        disabled={!ready || busy}
        onClick={() =>
          onSave(
            isNew
              ? { newPersonName: name.trim(), newPersonPosition: position.trim() || undefined }
              : { contactId: Number(value) },
          )
        }
      >
        Zapisz
      </Button>
      <Button variant="ghost" size="sm" className="h-8" onClick={onCancel}>
        Anuluj
      </Button>
    </div>
  );
}

function ProposalLine({
  confidence,
  proposal,
  alternatives,
  onPick,
  canApply,
}: {
  confidence: ProposalConfidence;
  proposal: ProposalCandidate | null;
  alternatives: ProposalCandidate[];
  onPick: (contactId: number) => void;
  canApply: boolean;
}) {
  if (!proposal?.contact) {
    return (
      <span className={CALM_SUBLINE}>
        Automat nie znalazł osoby w danych NEXUSA — wskaż ją ręcznie („Zmień”).
      </span>
    );
  }
  return (
    <>
      <span className="mt-0.5 block text-sm">
        <span aria-hidden>→ </span>
        <span className="font-medium">{personLabel(proposal.contact)}</span>
        {proposal.contact.area ? (
          <span className="text-muted-foreground"> · {proposal.contact.area}</span>
        ) : null}
        <span className="ml-2 align-middle">
          <ConfidenceDot confidence={confidence} />
        </span>
      </span>
      <span className={CALM_SUBLINE}>Skąd: {sourcesLabel(proposal)}</span>
      {alternatives.length ? (
        <span className={cn(CALM_SUBLINE, "flex flex-wrap items-center gap-x-2")}>
          Inne:
          {alternatives.map((alt) =>
            alt.contact ? (
              <span key={alt.contact.id} title={sourcesLabel(alt)}>
                {canApply ? (
                  <button
                    type="button"
                    className="underline-offset-2 hover:underline"
                    onClick={() => onPick(alt.contact!.id)}
                  >
                    {alt.contact.name}
                  </button>
                ) : (
                  alt.contact.name
                )}
                <span className="text-muted-foreground/80"> ({sourcesLabel(alt)})</span>
              </span>
            ) : null,
          )}
        </span>
      ) : null}
    </>
  );
}

function RowActions({
  canApply,
  hasProposal,
  busy,
  onApprove,
  onChange,
  onSkip,
}: {
  canApply: boolean;
  hasProposal: boolean;
  busy: boolean;
  onApprove: () => void;
  onChange: () => void;
  onSkip: () => void;
}) {
  if (!canApply) return null;
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      {hasProposal ? (
        <Button size="sm" className="h-7" disabled={busy} onClick={onApprove}>
          Zatwierdź
        </Button>
      ) : null}
      <Button variant="outline" size="sm" className="h-7" disabled={busy} onClick={onChange}>
        Zmień
      </Button>
      <Button variant="ghost" size="sm" className="h-7" disabled={busy} onClick={onSkip}>
        Pomiń
      </Button>
    </div>
  );
}

function SkippedToggle({ count, children }: { count: number; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  if (!count) return null;
  return (
    <div className="border-t border-border/60 pt-1.5">
      <Button
        variant="ghost"
        size="sm"
        className="h-7 px-2 text-xs text-muted-foreground"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Ukryj pominięte" : `Pominięte (${count})`}
      </Button>
      {open ? <ul className="divide-y divide-border/60">{children}</ul> : null}
    </div>
  );
}

function Section({
  id,
  title,
  note,
  action,
  children,
}: {
  id: string;
  title: string;
  note?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 id={id} className="text-sm font-semibold">
            {title}
          </h3>
          {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
        </div>
        {action}
      </div>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function conflictNote(result: ApplyResult): string {
  const parts = [`Zapisano: ${result.applied.length}`];
  if (result.conflicts.length) {
    parts.push(`bez zmian (ktoś już wpisał): ${result.conflicts.length}`);
  }
  if (result.rejected?.length) parts.push(`odrzucone: ${result.rejected.length}`);
  return parts.join(" · ");
}

/**
 * Propozycje struktury u klienta (decyzja Artura 18.10.2026 „Propozycja
 * automatu + akcept DL”): menedżer każdego konsultanta bez menedżera i „kto
 * komu podlega” — z pewnością i źródłem. Zatwierdzenie, zmiana i „Pomiń”
 * zapisuje serwer; nic nie zapisuje się samo i nic nie wychodzi do klienta.
 * Hooki mutacji siedzą tu, nie w wierszach — wiersz znika po zapisie.
 */
export function StructureProposalsPanel({
  clientId,
  initialData,
}: {
  clientId: number;
  initialData?: ClientStructureProposals;
}) {
  const query = useClientStructureProposals(clientId);
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const applyManagers = useApplyManagers(clientId);
  const applyOrg = useApplyReportsTo(clientId);
  const skip = useSkipProposal(clientId);
  const [changing, setChanging] = useState<string | null>(null);
  const data = query.data ?? initialData;
  const busy = applyManagers.isPending || applyOrg.isPending || skip.isPending;

  const view = resolveViewState({
    isLoading: query.isLoading && !data,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess || Boolean(data),
    isEmpty: false,
  });
  if (view === "loading") {
    return <p className="p-3 text-sm text-muted-foreground">Liczę propozycje struktury…</p>;
  }
  if (!data || view === "error" || view === "forbidden" || view === "not_found") {
    return (
      <QueryStateNotice
        state={view === "forbidden" || view === "not_found" ? view : "error"}
        description={apiErrorMessage(query.error, "Nie udało się policzyć propozycji.")}
        onRetry={() => query.refetch()}
      />
    );
  }

  const saveManagers = (items: ManagerChoice[], success: string) =>
    applyManagers.mutate(items, {
      onSuccess: (result) => {
        setChanging(null);
        showToast(result.conflicts.length ? conflictNote(result) : success, "success");
      },
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się zapisać menedżera."), "error"),
    });
  const saveOrg = (
    items: { contact_id: number; reports_to_contact_id: number }[],
    success: string,
  ) =>
    applyOrg.mutate(items, {
      onSuccess: (result) => {
        setChanging(null);
        const problems = result.conflicts.length + (result.rejected?.length ?? 0);
        showToast(problems ? conflictNote(result) : success, problems ? "info" : "success");
      },
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się zapisać struktury."), "error"),
    });
  const skipRow = (
    kind: SkipKind,
    subjectId: number,
    proposedContactId: number | null,
    restore = false,
  ) =>
    skip.mutate(
      { kind, subjectId, proposedContactId, restore },
      {
        onSuccess: () => showToast(restore ? "Przywrócono propozycję" : "Pominięto", "success"),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się zapisać pominięcia."), "error"),
      },
    );

  const certainManagers = certainManagerChoices(data);
  const certainOrg = certainReportsToChoices(data);
  const approveAllManagers = async () => {
    const ok = await askConfirm({
      title: `Zatwierdzić ${certainManagers.length} pewnych propozycji?`,
      description:
        "Wskazane osoby trafią na kontrakty jako „Menedżer u klienta”. Kontraktów, którym ktoś w międzyczasie wpisał menedżera, nie zmienimy.",
      confirmLabel: "Zatwierdź",
    });
    if (ok) saveManagers(certainManagers, `Zatwierdzono: ${certainManagers.length}`);
  };
  const approveAllOrg = async () => {
    const ok = await askConfirm({
      title: `Zatwierdzić ${certainOrg.length} pewnych przełożonych?`,
      description: "„Podlega pod” zapisze się w strukturze klienta. Zmiany, które zamknęłyby pętlę, odrzucimy.",
      confirmLabel: "Zatwierdź",
    });
    if (ok) saveOrg(certainOrg, `Zatwierdzono: ${certainOrg.length}`);
  };

  const managerRow = (row: ManagerProposal) => {
    const key = `m${row.contract_id}`;
    const proposed = row.proposal?.contact?.id ?? null;
    return (
      <li key={key} className="py-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <Link
              href={`/contracts/${row.contract_id}`}
              className="text-sm font-medium hover:underline"
            >
              {row.candidate_name ?? `Kontrakt #${row.contract_id}`}
            </Link>
            {row.role ? <span className="text-sm text-muted-foreground"> · {row.role}</span> : null}
            {row.manager_outside_client ? (
              <span className={CALM_SUBLINE}>
                Na kontrakcie stoi osoba innego klienta — wskaż menedżera od nowa.
              </span>
            ) : null}
            {row.skipped ? (
              <span className={CALM_SUBLINE}>
                Pominięte{row.skipped.by ? ` przez ${row.skipped.by}` : ""}
                {proposed ? ` (propozycja: ${row.proposal?.contact?.name})` : ""}
              </span>
            ) : (
              <ProposalLine
                confidence={row.confidence}
                proposal={row.proposal}
                alternatives={row.alternatives}
                canApply={data.can_apply_managers}
                onPick={(contactId) =>
                  saveManagers(
                    [{ contract_id: row.contract_id, contact_id: contactId }],
                    "Menedżer zapisany",
                  )
                }
              />
            )}
          </div>
          {row.skipped ? (
            data.can_apply_managers ? (
              <Button
                variant="ghost"
                size="sm"
                className="h-7"
                disabled={busy}
                onClick={() => skipRow("managers", row.contract_id, null, true)}
              >
                <Undo2 className="mr-1 size-3.5" aria-hidden />
                Przywróć
              </Button>
            ) : null
          ) : (
            <RowActions
              canApply={data.can_apply_managers}
              hasProposal={proposed !== null}
              busy={busy}
              onApprove={() =>
                saveManagers(
                  [{ contract_id: row.contract_id, contact_id: proposed! }],
                  "Menedżer zapisany",
                )
              }
              onChange={() => setChanging(changing === key ? null : key)}
              onSkip={() => skipRow("managers", row.contract_id, proposed)}
            />
          )}
        </div>
        {changing === key ? (
          <ChangePicker
            people={data.people}
            allowNewPerson
            busy={busy}
            onCancel={() => setChanging(null)}
            onSave={(choice) =>
              saveManagers(
                [
                  {
                    contract_id: row.contract_id,
                    contact_id: choice.contactId,
                    new_person_name: choice.newPersonName,
                    new_person_position: choice.newPersonPosition ?? null,
                  },
                ],
                "Menedżer zapisany",
              )
            }
          />
        ) : null}
      </li>
    );
  };

  const orgRow = (row: ReportsToProposal) => {
    const key = `o${row.contact.id}`;
    const proposed = row.proposal?.contact?.id ?? null;
    return (
      <li key={key} className="py-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <span className="text-sm font-medium">{personLabel(row.contact)}</span>
            {row.contact.area || row.department_text ? (
              <span className="text-sm text-muted-foreground">
                {" "}
                · {row.contact.area ?? row.department_text}
              </span>
            ) : null}
            {row.skipped ? (
              <span className={CALM_SUBLINE}>
                Pominięte{row.skipped.by ? ` przez ${row.skipped.by}` : ""}
              </span>
            ) : (
              <ProposalLine
                confidence={row.confidence}
                proposal={row.proposal}
                alternatives={row.alternatives}
                canApply={data.can_apply_org}
                onPick={(contactId) =>
                  saveOrg(
                    [{ contact_id: row.contact.id, reports_to_contact_id: contactId }],
                    "Struktura zapisana",
                  )
                }
              />
            )}
          </div>
          {row.skipped ? (
            data.can_apply_org ? (
              <Button
                variant="ghost"
                size="sm"
                className="h-7"
                disabled={busy}
                onClick={() => skipRow("reports-to", row.contact.id, null, true)}
              >
                <Undo2 className="mr-1 size-3.5" aria-hidden />
                Przywróć
              </Button>
            ) : null
          ) : (
            <RowActions
              canApply={data.can_apply_org}
              hasProposal={proposed !== null}
              busy={busy}
              onApprove={() =>
                saveOrg(
                  [{ contact_id: row.contact.id, reports_to_contact_id: proposed! }],
                  "Struktura zapisana",
                )
              }
              onChange={() => setChanging(changing === key ? null : key)}
              onSkip={() => skipRow("reports-to", row.contact.id, proposed)}
            />
          )}
        </div>
        {changing === key ? (
          <ChangePicker
            people={data.people}
            excludeId={row.contact.id}
            allowNewPerson={false}
            busy={busy}
            onCancel={() => setChanging(null)}
            onSave={(choice) =>
              choice.contactId
                ? saveOrg(
                    [{ contact_id: row.contact.id, reports_to_contact_id: choice.contactId }],
                    "Struktura zapisana",
                  )
                : undefined
            }
          />
        ) : null}
      </li>
    );
  };

  const managersLive = data.managers.filter((row) => !row.skipped);
  const managersSkipped = data.managers.filter((row) => row.skipped);
  const orgLive = data.reports_to.filter((row) => !row.skipped);
  const orgSkipped = data.reports_to.filter((row) => row.skipped);
  const c = data.counts;

  return (
    <div className="space-y-3">
      <Section
        id={`structure-managers-${clientId}`}
        title="Menedżer u klienta — propozycje"
        note="Automat szuka menedżera w kontrakcie, zamówieniach, rekrutacji i u kolegów z zespołu. Nic nie zapisuje się samo; do klienta nic nie wychodzi."
        action={
          data.can_apply_managers && certainManagers.length ? (
            <Button size="sm" disabled={busy} onClick={approveAllManagers}>
              <Check className="mr-1 size-4" aria-hidden />
              Zatwierdź pewne ({certainManagers.length})
            </Button>
          ) : null
        }
      >
        <InlineStats
          id={`structure-stats-${clientId}`}
          stats={[
            { id: "consultants", label: "konsultantów", value: c.consultants },
            { id: "without", label: "bez menedżera", value: c.without_manager },
            { id: "certain", label: "pewne", value: c.certain },
            { id: "uncertain", label: "do sprawdzenia", value: c.uncertain },
            { id: "none", label: "bez propozycji", value: c.none },
          ]}
        />
        {managersLive.length ? (
          <ul className="mt-1 divide-y divide-border/60">{managersLive.map(managerRow)}</ul>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">
            {c.without_manager
              ? "Wszystkie pozycje są pominięte."
              : "Każdy konsultant ma wskazanego menedżera u klienta."}
          </p>
        )}
        <SkippedToggle count={managersSkipped.length}>
          {managersSkipped.map(managerRow)}
        </SkippedToggle>
        {!data.can_apply_managers && data.managers.length ? (
          <p className={cn(CALM_SUBLINE, "pt-1")}>
            Propozycje zatwierdza Delivery Lead klienta albo administrator.
          </p>
        ) : null}
      </Section>

      <Section
        id={`structure-org-${clientId}`}
        title="Kto komu podlega — propozycje"
        note="Z tytułów osób klienta w tym samym dziale i z rekrutacji ich konsultantów. Ręczna zmiana: drzewo „Struktura u klienta”."
        action={
          data.can_apply_org && certainOrg.length ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={approveAllOrg}>
              <Check className="mr-1 size-4" aria-hidden />
              Zatwierdź pewne ({certainOrg.length})
            </Button>
          ) : null
        }
      >
        {orgLive.length ? (
          <ul className="divide-y divide-border/60">{orgLive.map(orgRow)}</ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Brak propozycji przełożonych — osoby mają „Podlega pod” albo dane nie wskazują nikogo.
          </p>
        )}
        <SkippedToggle count={orgSkipped.length}>{orgSkipped.map(orgRow)}</SkippedToggle>
      </Section>
      {confirmDialog}
    </div>
  );
}
