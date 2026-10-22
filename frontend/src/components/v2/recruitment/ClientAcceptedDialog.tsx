"use client";

/**
 * Okno „Klient zaakceptował” (D1–D6, 16.10.2026, makiety „Akceptacja klienta
 * na Tablicy”). Jedno miejsce na akceptację: przycisk na karcie w „Rozmowie
 * u klienta”, w panelu osoby i werdykt „Akceptuje” po rozmowie otwierają to
 * samo okno.
 *
 * Okno zbiera datę akceptacji, opcjonalnie planowany start i to, co
 * powiedział klient, pokazuje, kto dostanie dzwonek, i pilnuje debriefu po
 * rozmowie (D3): gdy go brakuje, „Uzupełnij debrief” otwiera okno debriefu
 * na wierzchu, a zapis akceptacji czeka, aż debrief będzie. Sam ruch
 * i werdykt wykonuje wołający (`onConfirm`) wspólną ścieżką ruchu.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

import api, { hiringManagerFeedbackApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { DebriefRequiredDialog } from "@/components/v2/recruitment/DebriefRequiredDialog";
import { useMoveRequirements } from "@/lib/api/moveRequirements";
import { validateAcceptance, type ClientAcceptanceRecipient } from "@/lib/client-acceptance";
import { warsawToday } from "@/lib/warsaw-date";

export interface ClientAcceptanceValues {
  acceptedOn: string;
  plannedStartOn: string | null;
  clientNote: string | null;
  /** 0506: po zapisie — prośba o umowę przedwstępną „przed umową B2B”. */
  requestPreContract?: boolean;
}

export interface ClientAcceptedDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  candidateId: number;
  candidateName: string;
  /** Podtytuł: klient · rekrutacja. */
  context?: string | null;
  /** Etap „Akceptacja” szablonu — cel ruchu i wymagań (debrief). */
  acceptanceStageDefId: number | null;
  /** Notatka wpisana już w formularzu werdyktu („Akceptuje” z „Rozmów”). */
  initialNote?: string | null;
  onConfirm: (values: ClientAcceptanceValues, recipients: ClientAcceptanceRecipient[]) => void;
}

export const CLIENT_ACCEPTANCE_RECIPIENTS_KEY = "client-acceptance-recipients";

const NOTE_MAX = 8000;

function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? [words[0][0], words[words.length - 1][0]] : [words[0]?.[0] ?? "?"];
  return letters.join("").toUpperCase();
}

export function ClientAcceptedDialog({
  open,
  onOpenChange,
  jobId,
  candidateId,
  candidateName,
  context,
  acceptanceStageDefId,
  initialNote = null,
  onConfirm,
}: ClientAcceptedDialogProps) {
  const [acceptedOn, setAcceptedOn] = useState(() => warsawToday());
  const [plannedStartOn, setPlannedStartOn] = useState("");
  const [clientNote, setClientNote] = useState("");
  const [requestPreContract, setRequestPreContract] = useState(false);
  // Otwarte okno pytań: `eventId = null` — rozmowy nie ma w kalendarzu
  // (para bez terminu, 20.10.2026), okno pyta, kiedy była.
  const [debriefFor, setDebriefFor] = useState<{ eventId: number | null } | null>(null);
  // Pole notatki ruszone ręcznie — werdykt z serwera go już nie nadpisuje.
  const noteTouched = useRef(false);

  // Nowa osoba albo ponowne otwarcie — formularz od zera (dziś, bez startu).
  useEffect(() => {
    if (!open) return;
    setAcceptedOn(warsawToday());
    setPlannedStartOn("");
    setClientNote(initialNote ?? "");
    noteTouched.current = Boolean(initialNote);
    setDebriefFor(null);
  }, [open, candidateId, initialNote]);

  // Zapis akceptacji nadpisuje werdykt klienta tej pary — pole startuje od
  // jego notatki, żeby puste pole nie skasowało notatki z wcześniejszej rundy.
  const verdicts = useQuery({
    queryKey: ["hiring-manager-feedback", jobId],
    queryFn: () => hiringManagerFeedbackApi.list(jobId),
    enabled: open,
    retry: 0,
  });
  const existingNote = useMemo(
    () => verdicts.data?.items?.find((v) => v.candidate_id === candidateId)?.note ?? null,
    [verdicts.data, candidateId],
  );
  useEffect(() => {
    if (!open || noteTouched.current || !existingNote) return;
    setClientNote(existingNote);
  }, [open, existingNote]);

  const recipients = useQuery({
    queryKey: [CLIENT_ACCEPTANCE_RECIPIENTS_KEY, jobId, candidateId],
    queryFn: async ({ signal }) =>
      (
        await api.get<{ recipients: ClientAcceptanceRecipient[] }>(
          "/api/pipeline/client-acceptance/recipients",
          { params: { job_id: jobId, candidate_id: candidateId }, signal },
        )
      ).data.recipients,
    enabled: open,
    staleTime: 60_000,
    retry: 0,
  });

  const requirements = useMoveRequirements(
    open ? { candidateId, jobId, toStageDefId: acceptanceStageDefId } : null,
  );
  const debrief = useMemo(
    () => requirements.data?.items.find((i) => i.key === "debrief") ?? null,
    [requirements.data],
  );
  const debriefMissing = debrief != null && debrief.status === "missing";
  // api-detail-ok: `detail` wymagania ruchu jest z kontraktu napisem (`MoveRequirementItem`), nie błędem FastAPI.
  const debriefHint = debrief?.detail ?? "zapisz pytania klienta po rozmowie";
  const debriefAction = debriefMissing ? (debrief?.action ?? null) : null;

  const errors = validateAcceptance(acceptedOn, plannedStartOn);
  const hasErrors = Boolean(errors.acceptedOn || errors.plannedStartOn);
  const canSave = acceptanceStageDefId != null && !hasErrors && !debriefMissing && !requirements.isPending;

  const submit = () => {
    if (!canSave) return;
    onConfirm(
      {
        acceptedOn,
        plannedStartOn: plannedStartOn || null,
        clientNote: clientNote.trim() || null,
        requestPreContract,
      },
      recipients.data ?? [],
    );
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent size="lg" data-testid="client-accepted-dialog" aria-describedby="client-accepted-description">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-success-muted-foreground" aria-hidden="true" />
              Klient zaakceptował: {candidateName}
            </DialogTitle>
            <DialogDescription id="client-accepted-description">
              {context ? `${context} — ` : ""}karta przejdzie do „Akceptacja i umowa”.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            {acceptanceStageDefId == null && (
              <p role="alert" className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm text-warning">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                Szablon tej rekrutacji nie ma etapu „Akceptacja” — przesuń osobę strzałką na „Akceptacja i umowa”.
              </p>
            )}

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="client-accepted-on">Kiedy klient dał akceptację</Label>
                <Input
                  id="client-accepted-on"
                  type="date"
                  value={acceptedOn}
                  max={warsawToday()}
                  onChange={(e) => setAcceptedOn(e.target.value)}
                  aria-invalid={errors.acceptedOn ? true : undefined}
                  aria-describedby={errors.acceptedOn ? "client-accepted-on-error" : undefined}
                />
                {errors.acceptedOn && (
                  <p id="client-accepted-on-error" className="text-xs text-destructive">
                    {errors.acceptedOn}
                  </p>
                )}
              </div>
              <div className="space-y-1">
                <Label htmlFor="client-accepted-start">
                  Planowany start <span className="font-normal text-muted-foreground">— opcjonalnie</span>
                </Label>
                <Input
                  id="client-accepted-start"
                  type="date"
                  value={plannedStartOn}
                  min={acceptedOn || undefined}
                  onChange={(e) => setPlannedStartOn(e.target.value)}
                  aria-invalid={errors.plannedStartOn ? true : undefined}
                  aria-describedby={errors.plannedStartOn ? "client-accepted-start-error" : undefined}
                />
                {errors.plannedStartOn && (
                  <p id="client-accepted-start-error" className="text-xs text-destructive">
                    {errors.plannedStartOn}
                  </p>
                )}
              </div>
            </div>

            {requirements.isPending && acceptanceStageDefId != null ? (
              <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Sprawdzamy debrief po rozmowie…
              </p>
            ) : requirements.isError ? (
              <p role="alert" className="text-sm text-warning">
                Nie udało się sprawdzić debriefu ({apiErrorMessage(requirements.error, "brak odpowiedzi serwera")}).
                Serwer sprawdzi go przy zapisie.
              </p>
            ) : debriefMissing ? (
              <div
                data-testid="client-accepted-debrief"
                className="flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm"
              >
                <span className="min-w-0 flex-1">
                  <span className="font-semibold">Debrief po rozmowie u klienta</span>
                  <span className="block text-xs text-muted-foreground">
                    {debriefHint} — bez niego akceptacja się nie zapisze.
                  </span>
                </span>
                {debriefAction?.kind === "open_debrief" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setDebriefFor({ eventId: debriefAction.event_id ?? null })}
                  >
                    Uzupełnij debrief
                  </Button>
                )}
              </div>
            ) : debrief ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-success-muted-foreground" aria-hidden="true" />
                Debrief po rozmowie u klienta jest zapisany.
              </p>
            ) : null}

            <div className="space-y-1">
              <Label htmlFor="client-accepted-note">
                Co powiedział klient <span className="font-normal text-muted-foreground">— opcjonalnie</span>
              </Label>
              <Textarea
                id="client-accepted-note"
                rows={3}
                maxLength={NOTE_MAX}
                value={clientNote}
                onChange={(e) => {
                  noteTouched.current = true;
                  setClientNote(e.target.value);
                }}
                placeholder="Np. start od listopada, 2 dni w biurze."
              />
              <p className="text-xs text-muted-foreground">Zapisze się w werdykcie klienta („Akceptuje”).</p>
            </div>

            <label className="flex items-start gap-2 text-sm" data-testid="client-accepted-pre-contract">
              <Checkbox
                checked={requestPreContract}
                onCheckedChange={(v) => setRequestPreContract(v === true)}
                className="mt-0.5"
              />
              <span>
                Potrzebna umowa przedwstępna przed umową B2B
                <span className="block text-xs text-muted-foreground">
                  Prośba trafi do rekrutera prowadzącego osobę; dostaniesz dzwonek przy każdym kroku.
                </span>
              </span>
            </label>

            <section aria-label="Kto dostanie powiadomienie" className="space-y-2 rounded-md border border-border p-3">
              <h3 className="text-sm font-semibold">Dostaną powiadomienie „Klient zaakceptował”</h3>
              {recipients.isPending ? (
                <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  Sprawdzamy, kogo powiadomić…
                </p>
              ) : recipients.isError ? (
                <p role="alert" className="text-xs text-warning">
                  Nie udało się pobrać listy ({apiErrorMessage(recipients.error, "brak odpowiedzi serwera")}). Powiadomienie i tak
                  wyślemy po zapisie.
                </p>
              ) : recipients.data.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Nikt poza Tobą — nie ma komu wysłać powiadomienia.
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {recipients.data.map((r) => (
                    <li key={r.user_id} className="flex items-center gap-2 text-sm">
                      <span
                        aria-hidden="true"
                        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
                      >
                        {initialsOf(r.name)}
                      </span>
                      <span>
                        <span className="font-semibold">{r.name}</span>
                        <span className="text-muted-foreground"> — {r.role_label}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-xs text-muted-foreground">Ty zaznaczasz akceptację, więc powiadomienia nie dostajesz.</p>
            </section>

            <p className="rounded-md bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
              Po zapisie karta przejdzie do „Akceptacja i umowa”, a werdykt klienta zapisze się jako „Akceptuje”.
              Pomyłkę cofniesz w panelu osoby: menu „⋯” → „Cofnij akceptację klienta”.
            </p>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Anuluj
            </Button>
            <Button data-testid="client-accepted-save" onClick={submit} disabled={!canSave}>
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              Zapisz akceptację
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {debriefFor != null && (
        <DebriefRequiredDialog
          open
          onOpenChange={(next) => {
            if (!next) setDebriefFor(null);
          }}
          eventId={debriefFor.eventId}
          candidateId={candidateId}
          candidateName={candidateName}
          jobId={jobId}
          onSaved={() => {
            setDebriefFor(null);
            void requirements.refetch();
          }}
        />
      )}
    </>
  );
}
