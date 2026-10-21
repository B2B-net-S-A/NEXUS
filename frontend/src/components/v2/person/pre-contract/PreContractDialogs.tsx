"use client";

/**
 * Okna umowy przedwstępnej (0506, makiety VWyCFF3aU7CLCNSXGCSx2R):
 * prośba, wgranie podpisanej umowy (forma podpisu), powód zamknięcia,
 * rezygnacja kandydata (dowód do decyzji o karze) i decyzja o karze.
 * Każde okno samo woła API i zgłasza sukces przez `onDone`.
 */

import { useId, useState } from "react";
import { Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  NEEDED_BEFORE_OPTIONS,
  SIGNATURE_FORM_OPTIONS,
  WITHDRAWAL_OPTIONS,
  preContractsApi,
  type PreContractNeededBefore,
  type PreContractRequest,
  type PreContractSignatureForm,
  type PreContractWithdrawalKind,
} from "@/lib/api/preContracts";
import { warsawToday } from "@/lib/warsaw-date";

type Done = (request: PreContractRequest) => void;

function Choice<T extends string>({
  name,
  value,
  options,
  onChange,
  label,
}: {
  name: string;
  value: T | null;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <RadioGroup
      value={value ?? ""}
      onValueChange={(v) => onChange(v as T)}
      aria-label={label}
      className="grid gap-2 sm:grid-cols-2"
    >
      {options.map((o) => {
        const id = `${name}-${o.value}`;
        return (
          <label
            key={o.value}
            htmlFor={id}
            className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm hover:bg-muted"
          >
            <RadioGroupItem id={id} value={o.value} />
            {o.label}
          </label>
        );
      })}
    </RadioGroup>
  );
}

function useSubmit() {
  const { showError } = useToast();
  const [busy, setBusy] = useState(false);
  const run = async <T,>(fn: () => Promise<T>, fallback: string): Promise<T | null> => {
    setBusy(true);
    try {
      return await fn();
    } catch (e) {
      showError(apiErrorMessage(e, fallback));
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
}

// ── Prośba ───────────────────────────────────────────────────────────────────

export function PreContractRequestDialog({
  open,
  onOpenChange,
  candidateId,
  jobId,
  personLabel,
  defaultNeededBefore = "cv_sent",
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  jobId: number;
  personLabel: string;
  defaultNeededBefore?: PreContractNeededBefore;
  onDone: Done;
}) {
  const ids = useId();
  const [needed, setNeeded] = useState<PreContractNeededBefore>(defaultNeededBefore);
  const [neededBy, setNeededBy] = useState("");
  const [reason, setReason] = useState("");
  const { busy, run } = useSubmit();
  const dateMissing = needed === "date" && !neededBy;

  const submit = async () => {
    if (dateMissing) return;
    const result = await run(
      () =>
        preContractsApi.create({
          candidate_id: candidateId,
          job_id: jobId,
          needed_before: needed,
          needed_by: needed === "date" ? neededBy : null,
          reason: reason.trim() || null,
        }),
      "Nie udało się poprosić o umowę.",
    );
    if (result) {
      onDone(result);
      onOpenChange(false);
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Poproś o umowę przedwstępną"
      description={personLabel}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={busy || dateMissing} data-testid="pre-contract-request-save">
            {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
            Poproś
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <p className="text-sm font-medium">Kiedy musi być podpisana</p>
          <Choice name={`${ids}-needed`} label="Kiedy musi być podpisana" value={needed} options={NEEDED_BEFORE_OPTIONS} onChange={setNeeded} />
          {needed === "date" ? (
            <div className="space-y-1">
              <label htmlFor={`${ids}-date`} className="text-xs font-medium text-muted-foreground">
                Data
              </label>
              <Input id={`${ids}-date`} type="date" value={neededBy} min={warsawToday()} onChange={(e) => setNeededBy(e.target.value)} />
            </div>
          ) : null}
        </div>
        <div className="space-y-1">
          <label htmlFor={`${ids}-reason`} className="text-xs font-medium text-muted-foreground">
            Po co (widzi rekruter, opcjonalnie)
          </label>
          <Textarea id={`${ids}-reason`} rows={2} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          Wystawia rekruter prowadzący osobę. Ty i on dostaniecie dzwonek przy każdej zmianie:
          wystawiona, wysłana, podpisana, wygasa, kandydat zrezygnował.
        </p>
      </div>
    </AppModal>
  );
}

// ── Wgranie podpisanej umowy ─────────────────────────────────────────────────

export function PreContractUploadDialog({
  open,
  onOpenChange,
  request,
  kind,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  request: PreContractRequest;
  kind: "candidate" | "company";
  onDone: Done;
}) {
  const ids = useId();
  const [file, setFile] = useState<File | null>(null);
  const [form, setForm] = useState<PreContractSignatureForm | null>(null);
  const { busy, run } = useSubmit();
  const ready = file != null && (kind === "company" || form != null);

  const submit = async () => {
    if (!file || !ready) return;
    const result = await run(
      () =>
        kind === "candidate"
          ? preContractsApi.candidateSigned(request.id, form as PreContractSignatureForm, file)
          : preContractsApi.companySigned(request.id, file),
      "Nie udało się zapisać pliku.",
    );
    if (result) {
      onDone(result);
      onOpenChange(false);
      setFile(null);
      setForm(null);
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={kind === "candidate" ? "Wgraj umowę podpisaną przez kandydata" : "Wgraj umowę podpisaną przez firmę"}
      description={`${request.candidate_name} · ${request.job_title}`}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={busy || !ready} data-testid="pre-contract-upload-save">
            {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
            Zapisz
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1">
          <label htmlFor={`${ids}-file`} className="text-xs font-medium text-muted-foreground">
            Plik (PDF, JPG albo PNG, do 20 MB)
          </label>
          <Input
            id={`${ids}-file`}
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        {kind === "candidate" ? (
          <div className="space-y-2">
            <p className="text-sm font-medium">Jak kandydat podpisał</p>
            <Choice name={`${ids}-form`} label="Jak kandydat podpisał" value={form} options={SIGNATURE_FORM_OPTIONS} onChange={setForm} />
          </div>
        ) : (
          <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
            Po zapisie umowa obowiązuje{request.valid_until ? ` do ${request.valid_until.split("-").reverse().join(".")}` : ""}.
            Plików podpisanych obustronnie nie da się później podmienić.
          </p>
        )}
      </div>
    </AppModal>
  );
}

// ── Powód (anulowanie, odmowa kandydata) ─────────────────────────────────────

export function PreContractReasonDialog({
  open,
  onOpenChange,
  request,
  mode,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  request: PreContractRequest;
  mode: "cancel" | "refused";
  onDone: Done;
}) {
  const ids = useId();
  const [reason, setReason] = useState("");
  const { busy, run } = useSubmit();
  const ok = reason.trim().length >= 3;

  const submit = async () => {
    if (!ok) return;
    const result = await run(
      () =>
        mode === "cancel"
          ? preContractsApi.cancel(request.id, reason.trim())
          : preContractsApi.candidateRefused(request.id, reason.trim()),
      "Nie udało się zapisać.",
    );
    if (result) {
      onDone(result);
      onOpenChange(false);
      setReason("");
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={mode === "cancel" ? "Anuluj umowę przedwstępną" : "Kandydat odmówił podpisu"}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Wróć
          </Button>
          <Button variant={mode === "cancel" ? "destructive" : "primary"} onClick={() => void submit()} disabled={busy || !ok}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="space-y-1">
        <label htmlFor={`${ids}-reason`} className="text-xs font-medium text-muted-foreground">
          Powód (widzą proszący i obserwujący)
        </label>
        <Textarea id={`${ids}-reason`} rows={3} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
    </AppModal>
  );
}

// ── Rezygnacja kandydata ─────────────────────────────────────────────────────

export function PreContractWithdrawalDialog({
  open,
  onOpenChange,
  request,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  request: PreContractRequest;
  onDone: Done;
}) {
  const ids = useId();
  const [kind, setKind] = useState<PreContractWithdrawalKind | null>(null);
  const [eventOn, setEventOn] = useState(warsawToday());
  const [note, setNote] = useState("");
  const { busy, run } = useSubmit();
  const ok = kind != null && !!eventOn && note.trim().length >= 3;

  const submit = async () => {
    if (!ok || !kind) return;
    const result = await run(
      () => preContractsApi.candidateWithdrew(request.id, { kind, event_on: eventOn, note: note.trim() }),
      "Nie udało się zapisać rezygnacji.",
    );
    if (result) {
      onDone(result);
      onOpenChange(false);
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Kandydat zrezygnował — przedwstępna obowiązuje"
      description={`${request.candidate_name} · ${request.job_title}`}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={busy || !ok} data-testid="pre-contract-withdrawal-save">
            Zapisz i przekaż
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <p className="text-sm font-medium">Co się stało</p>
          <Choice name={`${ids}-kind`} label="Co się stało" value={kind} options={WITHDRAWAL_OPTIONS} onChange={setKind} />
        </div>
        <div className="space-y-1">
          <label htmlFor={`${ids}-date`} className="text-xs font-medium text-muted-foreground">
            Data zdarzenia
          </label>
          <Input id={`${ids}-date`} type="date" value={eventOn} max={warsawToday()} onChange={(e) => setEventOn(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label htmlFor={`${ids}-note`} className="text-xs font-medium text-muted-foreground">
            Opis (dowód do decyzji)
          </label>
          <Textarea id={`${ids}-note`} rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          NEXUS zapisze stan umowy w chwili zdarzenia i da znać Head of Recruitment, który decyduje
          o karze. Samo zapisanie niczego nie nalicza.
        </p>
      </div>
    </AppModal>
  );
}

// ── Decyzja o karze ──────────────────────────────────────────────────────────

export function PreContractPenaltyDialog({
  open,
  onOpenChange,
  request,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  request: PreContractRequest;
  onDone: Done;
}) {
  const ids = useId();
  const [decision, setDecision] = useState<"demand" | "waive" | null>(null);
  const [note, setNote] = useState("");
  const { busy, run } = useSubmit();
  const w = request.withdrawal;

  const submit = async () => {
    if (!decision) return;
    const result = await run(
      () => preContractsApi.penaltyDecision(request.id, decision, note.trim() || undefined),
      "Nie udało się zapisać decyzji.",
    );
    if (result) {
      onDone(result);
      onOpenChange(false);
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Decyzja o karze z umowy przedwstępnej"
      description={`${request.candidate_name} · ${request.job_title}`}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={busy || !decision}>
            Zapisz decyzję
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {w ? (
          <p className="rounded-md bg-muted px-3 py-2 text-sm">
            {w.kind_label} ({w.event_on.split("-").reverse().join(".")}): {w.note}
          </p>
        ) : null}
        <Choice
          name={`${ids}-decision`}
          label="Decyzja"
          value={decision}
          options={[
            { value: "demand", label: "Wezwanie do zapłaty kary" },
            { value: "waive", label: "Bez kary" },
          ]}
          onChange={setDecision}
        />
        <div className="space-y-1">
          <label htmlFor={`${ids}-note`} className="text-xs font-medium text-muted-foreground">
            Uzasadnienie (opcjonalnie)
          </label>
          <Textarea id={`${ids}-note`} rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
      </div>
    </AppModal>
  );
}
