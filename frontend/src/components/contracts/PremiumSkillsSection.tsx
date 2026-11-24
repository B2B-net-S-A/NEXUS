"use client";

// „Technologie premium” na karcie „Umowa ramowa” (F3, 15.11.2026): propozycja
// NEXUSA „zna / korzysta”, decyzja Delivery Leada, prośba do klienta i wynik.
// Przyznana dopłata podnosi limit (nie stawkę) — zapis przez ścieżkę z F1.
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useClaimAction,
  useCreateClaim,
  useJustificationDraft,
  usePremiumSkills,
  type PremiumClaim,
  type PremiumEvidence,
} from "@/lib/api/framework-rates";
import { formatIsoDatePl } from "@/lib/date-pl";
import { CLAIM_LABEL, coveredBy, grantedClaim, justificationDraft, lastRefusal, openClaimFor, proposalLabel } from "@/lib/premium-skills";
import { warsawToday } from "@/lib/warsaw-date";

type Dialog =
  | { kind: "decide"; evidence: PremiumEvidence }
  | { kind: "justify"; evidence: PremiumEvidence; claim: PremiumClaim }
  | { kind: "grant"; claim: PremiumClaim }
  | { kind: "refuse"; claim: PremiumClaim }
  | null;

export function PremiumSkillsSection({
  contractId,
  canEdit,
  category,
}: {
  contractId: number;
  canEdit: boolean;
  category: string | null;
}) {
  const query = usePremiumSkills(contractId, true);
  const action = useClaimAction(contractId);
  const { showError } = useToast();
  const [dialog, setDialog] = useState<Dialog>(null);

  // Awaria nie udaje braku technologii: nagłówek sekcji zostaje z błędem.
  if (query.isError) {
    return (
      <div className="mt-3 border-t border-border pt-3" data-testid="premium-skills">
        <div className="mb-1 text-xs font-semibold text-foreground">Technologie premium z umowy</div>
        <QueryStateNotice
          state="error"
          className="py-4"
          description={apiErrorMessage(query.error, "Nie udało się sprawdzić technologii premium.")}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }
  if (!query.isSuccess) return null;
  const { evidence, claims } = query.data;
  const run = async (claim: PremiumClaim, kind: "send" | "drop") => {
    try {
      await action.mutateAsync({ claimId: claim.id, action: kind });
    } catch (err) {
      showError(apiErrorMessage(err, "Nie udało się zmienić wniosku."));
    }
  };

  return (
    <div className="mt-3 border-t border-border pt-3" data-testid="premium-skills">
      <div className="mb-1 text-xs font-semibold text-foreground">Technologie premium z umowy</div>
      {evidence.length === 0 ? (
        <p className="text-xs text-muted-foreground">NEXUS nie znalazł technologii z umowy w CV, osi czasu ani karcie technicznej projektu.</p>
      ) : (
        <ul className="space-y-2">
          {evidence.map((e) => {
            const open = openClaimFor(claims, e.technology);
            const granted = open ? null : grantedClaim(claims, e.technology);
            const covered = open || granted ? null : coveredBy(claims, evidence, e.technology);
            const refused = lastRefusal(claims, e.technology);
            return (
              <li key={e.technology} className="text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-foreground">
                    {e.technology} <span className="text-muted-foreground">+{Number(e.percent)}%</span>
                  </span>
                  <span className="flex flex-wrap items-center gap-1">
                    <Badge variant={e.uses ? "soft" : "outline"} size="sm">
                      NEXUS: {proposalLabel(e)}
                    </Badge>
                    {open && <Badge variant="info" size="sm">{CLAIM_LABEL[open.status]}</Badge>}
                    {granted && (
                      <Badge variant="success" size="sm">
                        Przyznana{granted.client_confirmed_on ? ` ${formatIsoDatePl(granted.client_confirmed_on)}` : ""}
                      </Badge>
                    )}
                  </span>
                </div>
                <div className="text-[11px] text-muted-foreground">{e.sources.join(" · ")}</div>
                {covered && (
                  <div className="text-[11px] text-muted-foreground">
                    Umowa daje jedną dopłatę — przyznana już za {covered.technology}.
                  </div>
                )}
                {refused && !open && !granted && (
                  <div className="text-[11px] text-warning">
                    Odmowa klienta: {refused.outcome_reason}
                    {refused.next_try_on ? ` · ponów od ${formatIsoDatePl(refused.next_try_on)}` : ""}
                  </div>
                )}
                {canEdit && (
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {!open && !granted && !covered && (
                      <Button size="sm" variant="outline" data-tour="contracts.premium-skills" onClick={() => setDialog({ kind: "decide", evidence: e })}>
                        Oceń i złóż wniosek
                      </Button>
                    )}
                    {open?.status === "approved" && (
                      <Button size="sm" variant="outline" disabled={action.isPending} onClick={() => void run(open, "send")}>
                        Wysłane do klienta
                      </Button>
                    )}
                    {open && (
                      <>
                        <Button size="sm" variant="outline" data-tour="contracts.premium-justification" onClick={() => setDialog({ kind: "justify", evidence: e, claim: open })}>
                          Uzasadnienie (EN)
                        </Button>
                        <Button size="sm" onClick={() => setDialog({ kind: "grant", claim: open })}>
                          Klient przyznał
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setDialog({ kind: "refuse", claim: open })}>
                          Odmowa
                        </Button>
                        <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => void run(open, "drop")}>
                          Wycofaj
                        </Button>
                      </>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {dialog?.kind === "decide" && (
        <DecideDialog contractId={contractId} evidence={dialog.evidence} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "justify" && (
        <JustificationDialog
          contractId={contractId}
          claimId={dialog.claim.id}
          canDraft={canEdit}
          text={justificationDraft({
            technology: dialog.evidence.technology,
            percent: dialog.evidence.percent,
            category,
            sources: dialog.evidence.sources,
            dlNote: dialog.claim.dl_note,
          })}
          technology={dialog.evidence.technology}
          onClose={() => setDialog(null)}
        />
      )}
      {(dialog?.kind === "grant" || dialog?.kind === "refuse") && (
        <OutcomeDialog contractId={contractId} claim={dialog.claim} kind={dialog.kind} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}

function DecideDialog({ contractId, evidence, onClose }: { contractId: number; evidence: PremiumEvidence; onClose: () => void }) {
  const create = useCreateClaim(contractId);
  const [knows, setKnows] = useState(evidence.knows);
  const [uses, setUses] = useState(evidence.uses);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    try {
      await create.mutateAsync({ technology: evidence.technology, knows, uses, note: note.trim() || null });
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zapisać decyzji."));
    }
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => !next && onClose()}
      title={`${evidence.technology}: zna i korzysta?`}
      description="Klient przyznaje dopłatę, gdy konsultant zna technologię i używa jej na projekcie na co dzień, a nie sporadycznie."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={create.isPending}>
            {knows && uses ? "Zatwierdzam wniosek" : "Zapisz: bez wniosku"}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-xs text-muted-foreground">Propozycja NEXUSA: {proposalLabel(evidence)} ({evidence.sources.join(" · ")}).</p>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={knows} onChange={(e) => setKnows(e.target.checked)} />
          Zna technologię (potwierdzone w rozmowie)
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={uses} onChange={(e) => setUses(e.target.checked)} />
          Korzysta z niej na projekcie klienta na co dzień
        </label>
        <div className="space-y-1">
          <Label htmlFor="claim-note">Przykłady z projektu (do uzasadnienia)</Label>
          <Textarea id="claim-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
    </AppModal>
  );
}

function OutcomeDialog({
  contractId,
  claim,
  kind,
  onClose,
}: {
  contractId: number;
  claim: PremiumClaim;
  kind: "grant" | "refuse";
  onClose: () => void;
}) {
  const action = useClaimAction(contractId);
  const { showSuccess } = useToast();
  const [by, setBy] = useState("");
  const [on, setOn] = useState(warsawToday());
  const [evidence, setEvidence] = useState("");
  const [reason, setReason] = useState("");
  const [nextTry, setNextTry] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    try {
      await action.mutateAsync(
        kind === "grant"
          ? { claimId: claim.id, action: "grant", confirmed_by: by.trim() || null, confirmed_on: on || null, client_evidence: evidence.trim() || null }
          : { claimId: claim.id, action: "refuse", reason: reason.trim() || null, next_try_on: nextTry || null },
      );
      if (kind === "grant") showSuccess(`Dopłata za ${claim.technology} zapisana — limit podniesiony`);
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zapisać wyniku."));
    }
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => !next && onClose()}
      title={kind === "grant" ? `Klient przyznał dopłatę: ${claim.technology}` : `Odmowa klienta: ${claim.technology}`}
      description={
        kind === "grant"
          ? "Dopłata podnosi limit z umowy ramowej od daty potwierdzenia. Zamówienie i stawka przychodowa się nie zmieniają."
          : "Powód zostaje w historii osoby i wróci przy następnej prolongacji."
      }
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={action.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      {kind === "grant" ? (
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="space-y-1">
            <Label htmlFor="grant-by">Potwierdził po stronie klienta</Label>
            <Input id="grant-by" value={by} onChange={(e) => setBy(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="grant-on">Data potwierdzenia</Label>
            <Input id="grant-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
          </div>
          <div className="col-span-2 space-y-1">
            <Label htmlFor="grant-evidence">Dowód (mail, wpis w zapytaniu klienta)</Label>
            <Textarea id="grant-evidence" rows={3} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
          </div>
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <div className="space-y-1">
            <Label htmlFor="refuse-reason">Powód odmowy</Label>
            <Textarea id="refuse-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="np. „nice to have”, „używana sporadycznie”" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="refuse-next">Ponów od (opcjonalnie)</Label>
            <Input id="refuse-next" type="date" value={nextTry} onChange={(e) => setNextTry(e.target.value)} />
          </div>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
    </AppModal>
  );
}


export function JustificationDialog({
  contractId,
  claimId,
  canDraft,
  text,
  technology,
  onClose,
}: {
  contractId: number;
  claimId: number;
  canDraft: boolean;
  text: string;
  technology: string;
  onClose: () => void;
}) {
  const { showSuccess } = useToast();
  const draft = useJustificationDraft(contractId);
  const [value, setValue] = useState(text);
  const [fromModel, setFromModel] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  const propose = async () => {
    setNotice(null);
    setWarnings([]);
    try {
      const result = await draft.mutateAsync(claimId);
      if (result.text) {
        setValue(result.text);
        setFromModel(true);
        setWarnings(result.warnings);
      } else {
        setNotice(result.message ?? "Nie udało się przygotować szkicu — popraw szablon uzasadnienia albo napisz je sam.");
      }
    } catch (err) {
      setNotice(apiErrorMessage(err, "Nie udało się przygotować szkicu — popraw szablon uzasadnienia albo napisz je sam."));
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      showSuccess("Skopiowano uzasadnienie");
    } catch {
      const field = document.getElementById("justification-text") as HTMLTextAreaElement | null;
      field?.select();
    }
  };
  return (
    <AppModal
      open
      onOpenChange={(next) => !next && onClose()}
      title={`Uzasadnienie dopłaty: ${technology}`}
      description={
        fromModel
          ? "Szkic z modelu AI z faktów NEXUSA i Twoich przykładów. Przeczytaj i popraw przed wysłaniem — wysyłasz Ty."
          : "Szkic z faktów NEXUSA i Twoich przykładów. Popraw przed wysłaniem — NEXUS nie dopisuje zdań bez dowodu."
      }
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Zamknij
          </Button>
          {canDraft && (
            <Button variant="outline" onClick={() => void propose()} disabled={draft.isPending}>
              {draft.isPending ? "Przygotowuję szkic…" : fromModel ? "Zaproponuj ponownie" : "Zaproponuj uzasadnienie"}
            </Button>
          )}
          <Button onClick={() => void copy()}>Kopiuj</Button>
        </>
      }
    >
      <Label htmlFor="justification-text" className="sr-only">
        Uzasadnienie po angielsku
      </Label>
      <Textarea id="justification-text" rows={14} value={value} onChange={(e) => setValue(e.target.value)} />
      {notice && (
        <p role="status" className="mt-2 text-sm text-muted-foreground">
          {notice}
        </p>
      )}
      {warnings.map((w) => (
        <p key={w} role="alert" className="mt-2 text-sm text-warning">
          {w}
        </p>
      ))}
    </AppModal>
  );
}
