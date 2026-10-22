"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
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
  CONFIDENCE_LABELS,
  useApplyManagers,
  useApplyReportsTo,
  useClientStructureProposals,
  useSkipProposal,
  type ProposalConfidence,
} from "@/lib/api/structure-proposals";

import { StructureProposalsPanel, sourcesLabel } from "../structure/StructureProposalsPanel";
import { firstProposal, openProposalCount } from "./people-tech-format";

const TONE: Record<ProposalConfidence, StatusDotTone> = {
  certain: "success",
  uncertain: "warning",
  none: "neutral",
};

/**
 * Pasek „Do zatwierdzenia” (decyzja 5, 22.10.2026): JEDNA propozycja automatu
 * struktury — menedżer konsultanta albo „Podlega pod” — z „Zatwierdź / Zmień /
 * Pomiń” na tych samych trasach co `StructureProposalsPanel`, i link
 * „Wszystkie propozycje (N)” rozwijający pełny panel. Nic nie zapisuje się
 * samo; awaria propozycji chowa pasek (drzewo i mapa zostają).
 */
export function ApprovalBar({
  clientId,
  defaultExpanded = false,
}: {
  clientId: number;
  /** Pełny panel propozycji od razu rozwinięty (harness, link z dzwonka). */
  defaultExpanded?: boolean;
}) {
  const query = useClientStructureProposals(clientId);
  const { showToast } = useToast();
  const applyManagers = useApplyManagers(clientId);
  const applyOrg = useApplyReportsTo(clientId);
  const skip = useSkipProposal(clientId);
  const [changing, setChanging] = useState(false);
  const [picked, setPicked] = useState("");
  const [expanded, setExpanded] = useState(defaultExpanded);
  const data = query.data;
  if (!data) return null;
  const total = openProposalCount(data);
  const first = firstProposal(data);
  if (!total && !expanded) return null;
  const busy = applyManagers.isPending || applyOrg.isPending || skip.isPending;
  const canApply = first
    ? first.kind === "manager"
      ? data.can_apply_managers
      : data.can_apply_org
    : false;

  const done = (message: string) => ({
    onSuccess: () => {
      setChanging(false);
      setPicked("");
      showToast(message, "success");
    },
    onError: (err: unknown) =>
      showToast(apiErrorMessage(err, "Nie udało się zapisać propozycji."), "error"),
  });
  const save = (contactId: number) => {
    if (!first) return;
    if (first.kind === "manager") {
      applyManagers.mutate(
        [{ contract_id: first.row.contract_id, contact_id: contactId }],
        done("Menedżer zapisany"),
      );
    } else {
      applyOrg.mutate(
        [{ contact_id: first.row.contact.id, reports_to_contact_id: contactId }],
        done("Struktura zapisana"),
      );
    }
  };
  const skipFirst = () => {
    if (!first) return;
    skip.mutate(
      first.kind === "manager"
        ? {
            kind: "managers",
            subjectId: first.row.contract_id,
            proposedContactId: first.row.proposal?.contact?.id ?? null,
          }
        : {
            kind: "reports-to",
            subjectId: first.row.contact.id,
            proposedContactId: first.row.proposal?.contact?.id ?? null,
          },
      done("Pominięto"),
    );
  };

  const proposal = first?.row.proposal ?? null;
  const subject = first
    ? first.kind === "manager"
      ? (first.row.candidate_name ?? `Kontrakt #${first.row.contract_id}`)
      : first.row.contact.name
    : null;
  const excludeId = first?.kind === "reports_to" ? first.row.contact.id : undefined;

  return (
    <section aria-label="Do zatwierdzenia" className="space-y-2">
      {first && proposal?.contact ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-border bg-card px-3 py-2 text-sm">
          <span className="inline-flex items-center gap-1.5 font-semibold">
            <Sparkles className="size-4 text-primary" aria-hidden />
            Do zatwierdzenia
          </span>
          <span className="min-w-0 flex-1">
            <span className="font-medium">{subject}</span>
            <span className="text-muted-foreground">
              {first.kind === "manager" ? " pracuje pod " : " podlega pod "}
            </span>
            <span className="font-medium">{proposal.contact.name}</span>
            <span className="ml-2 inline-block align-middle">
              <StatusDot tone={TONE[first.row.confidence]}>
                {CONFIDENCE_LABELS[first.row.confidence]}
              </StatusDot>
            </span>
            <span className="block truncate text-xs text-muted-foreground" title={sourcesLabel(proposal)}>
              Skąd: {sourcesLabel(proposal)}
            </span>
          </span>
          {canApply ? (
            <span className="flex shrink-0 items-center gap-1.5">
              <Button size="sm" className="h-7" disabled={busy} onClick={() => save(proposal.contact!.id)}>
                Zatwierdź
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7"
                disabled={busy}
                aria-expanded={changing}
                onClick={() => setChanging((value) => !value)}
              >
                Zmień
              </Button>
              <Button variant="ghost" size="sm" className="h-7" disabled={busy} onClick={skipFirst}>
                Pomiń
              </Button>
            </span>
          ) : null}
          <Button
            variant="tertiary"
            size="sm"
            className="h-7 px-0"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Zwiń propozycje" : `Wszystkie propozycje (${total})`}
          </Button>
          {changing ? (
            <span className="flex w-full flex-wrap items-center gap-2">
              <Select value={picked} onValueChange={setPicked} disabled={busy}>
                <SelectTrigger aria-label="Wybierz osobę klienta" className="h-8 w-72">
                  <SelectValue placeholder="Wybierz osobę klienta" />
                </SelectTrigger>
                <SelectContent>
                  {data.people
                    .filter((person) => person.id !== excludeId)
                    .map((person) => (
                      <SelectItem key={person.id} value={String(person.id)}>
                        {[person.name, person.position].filter(Boolean).join(" · ")}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                className="h-8"
                disabled={!picked || busy}
                onClick={() => save(Number(picked))}
              >
                Zapisz
              </Button>
              <Button variant="ghost" size="sm" className="h-8" onClick={() => setChanging(false)}>
                Anuluj
              </Button>
            </span>
          ) : null}
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm">
          <span>
            <span className="font-semibold">Do zatwierdzenia</span>
            <span className="text-muted-foreground">
              {" "}
              · automat nie wskazał osoby — przejrzyj pozycje ręcznie
            </span>
          </span>
          <Button
            variant="tertiary"
            size="sm"
            className="h-7 px-0"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Zwiń propozycje" : `Wszystkie propozycje (${total})`}
          </Button>
        </div>
      )}
      {expanded ? <StructureProposalsPanel clientId={clientId} /> : null}
    </section>
  );
}
