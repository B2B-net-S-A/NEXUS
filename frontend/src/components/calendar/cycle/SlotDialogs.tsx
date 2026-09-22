"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { CandidateCombobox, type CandidateChoice } from "@/components/calendar/CandidateCombobox";
import { RecruitmentSelect } from "@/components/calendar/RecruitmentSelect";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { interviewCycleApi } from "@/lib/api/interviewCycle";
import {
  candidateLabel,
  formatSlot,
  pairContext,
  type PairInfo,
  type SlotRequest,
} from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

/** `datetime-local` → ISO z przesunięciem przeglądarki (serwer normalizuje do UTC). */
function localToIso(value: string): string {
  return new Date(value).toISOString();
}

function nextWorkdayAt(hour: number, offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
  d.setHours(hour, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(hour)}:00`;
}

function useInvalidateCycle() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["interview-cycle"] });
    qc.invalidateQueries({ queryKey: ["calendar-events"] });
    qc.invalidateQueries({ queryKey: ["calendar-upcoming"] });
  };
}

/**
 * DL wpisuje terminy od klienta. Z karty pary kandydat i rekrutacja są znane;
 * z przycisku „Dodaj terminy od klienta” wybiera się je tutaj.
 */
export function SlotRequestDialog({
  open,
  onOpenChange,
  pair,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pair: PairInfo | null;
}) {
  const toast = useToast();
  const invalidate = useInvalidateCycle();
  const [candidate, setCandidate] = useState<CandidateChoice | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [slots, setSlots] = useState<string[]>([]);
  const [duration, setDuration] = useState(60);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setCandidate(null);
    setJobId(null);
    setSlots([nextWorkdayAt(10, 1), nextWorkdayAt(14, 2)]);
    setDuration(60);
    setNote("");
    setError(null);
  }, [open, pair]);

  const candidateId = pair?.candidate_id ?? candidate?.id ?? null;
  const targetJobId = pair?.job_id ?? jobId;

  const mutation = useMutation({
    mutationFn: () =>
      interviewCycleApi.createSlots({
        candidate_id: candidateId as number,
        job_id: targetJobId as number,
        slots: slots.filter(Boolean).map((s) => ({ start: localToIso(s) })),
        duration_minutes: duration,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      invalidate();
      toast.showSuccess("Terminy wysłane rekruterowi — ustali termin z kandydatem.");
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać terminów.")),
  });

  const submit = () => {
    setError(null);
    if (candidateId == null || targetJobId == null) {
      setError("Wybierz kandydata i rekrutację.");
      return;
    }
    const filled = slots.filter(Boolean);
    if (filled.length === 0) {
      setError("Dodaj co najmniej jeden termin od klienta.");
      return;
    }
    if (filled.some((s) => new Date(s).getTime() < Date.now())) {
      setError("Termin rozmowy nie może być w przeszłości.");
      return;
    }
    mutation.mutate();
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Terminy rozmowy od klienta"
      description="Rekruter dostanie je w NEXUSIE, ustali jeden z kandydatem i odeśle Ci wybór."
      footer={
        <>
          <button type="button" onClick={() => onOpenChange(false)} className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground">
            Anuluj
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={mutation.isPending}
            className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Wyślij rekruterowi
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {pair ? (
          <div className="rounded-lg bg-muted/50 px-3 py-2 text-sm">
            <div className="font-semibold">{candidateLabel(pair)}</div>
            <div className="text-xs text-muted-foreground">{pairContext(pair)}</div>
          </div>
        ) : (
          <>
            <div>
              <span id="slot-candidate-label" className="mb-1 block text-xs font-semibold text-muted-foreground">
                Kandydat
              </span>
              <CandidateCombobox value={candidate} onChange={setCandidate} labelledBy="slot-candidate-label" />
            </div>
            <div>
              <label htmlFor="slot-job" className="mb-1 block text-xs font-semibold text-muted-foreground">
                Rekrutacja
              </label>
              <RecruitmentSelect id="slot-job" candidateId={candidate?.id ?? null} value={jobId} onChange={setJobId} />
            </div>
          </>
        )}
        <fieldset className="space-y-2">
          <legend className="mb-1 text-xs font-semibold text-muted-foreground">Terminy od klienta</legend>
          {slots.map((value, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="datetime-local"
                aria-label={`Termin ${i + 1}`}
                value={value}
                onChange={(e) => setSlots((s) => s.map((v, j) => (j === i ? e.target.value : v)))}
                className={INPUT}
              />
              {slots.length > 1 ? (
                <button
                  type="button"
                  aria-label={`Usuń termin ${i + 1}`}
                  onClick={() => setSlots((s) => s.filter((_, j) => j !== i))}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              ) : null}
            </div>
          ))}
          {slots.length < 6 ? (
            <button
              type="button"
              onClick={() => setSlots((s) => [...s, ""])}
              className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
            >
              <Plus className="h-3.5 w-3.5" /> Dodaj termin
            </button>
          ) : null}
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="slot-duration" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Czas rozmowy
            </label>
            <select id="slot-duration" value={duration} onChange={(e) => setDuration(Number(e.target.value))} className={INPUT}>
              {[30, 45, 60, 90, 120].map((m) => (
                <option key={m} value={m}>
                  {m} min
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label htmlFor="slot-note" className="mb-1 block text-xs font-semibold text-muted-foreground">
            Notatka dla rekrutera (opcjonalnie)
          </label>
          <textarea
            id="slot-note"
            rows={2}
            maxLength={1000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="np. rozmowa z kamerką, 2 osoby od klienta"
            className={cn(INPUT, "resize-none")}
          />
        </div>
        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}

/**
 * Wybór (rekruter) albo potwierdzenie (DL) terminu. DL może potwierdzić inny
 * termin niż wybrany, gdy klient zmienił zdanie.
 */
export function SlotDecisionDialog({
  open,
  onOpenChange,
  mode,
  pair,
  request,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "pick" | "confirm";
  pair: PairInfo | null;
  request: SlotRequest | null;
}) {
  const toast = useToast();
  const invalidate = useInvalidateCycle();
  const [index, setIndex] = useState<number | null>(null);
  const [addToOutlook, setAddToOutlook] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setIndex(request?.chosen_index ?? (request?.slots.length === 1 ? 0 : null));
    setAddToOutlook(true);
    setError(null);
  }, [open, request]);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!request || index == null) throw new Error("no-index");
      if (mode === "pick") return interviewCycleApi.chooseSlot(request.id, index);
      return interviewCycleApi.confirmSlot(request.id, { index, add_to_outlook: addToOutlook });
    },
    onSuccess: (res) => {
      invalidate();
      if (mode === "pick") {
        toast.showSuccess("Termin wysłany do DL — potwierdzi go u klienta.");
      } else {
        const outlook = (res as { outlook?: string }).outlook;
        toast.showSuccess(
          outlook === "added"
            ? "Termin potwierdzony — rozmowa jest w kalendarzu rekrutera i w jego Outlooku."
            : "Termin potwierdzony — rozmowa jest w kalendarzu rekrutera w NEXUSIE.",
        );
      }
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać wyboru.")),
  });

  const title = mode === "pick" ? "Termin ustalony z kandydatem" : "Potwierdź termin u klienta";
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={
        mode === "pick"
          ? "Zaznacz termin, który pasuje kandydatowi — DL odpowie klientowi."
          : "Zaznacz termin, który klient potwierdził. Rozmowa trafi do kalendarza rekrutera."
      }
      footer={
        <>
          <button type="button" onClick={() => onOpenChange(false)} className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground">
            Anuluj
          </button>
          <button
            type="button"
            disabled={index == null || mutation.isPending}
            onClick={() => {
              setError(null);
              mutation.mutate();
            }}
            className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {mode === "pick" ? "Wyślij do DL" : "Potwierdź termin"}
          </button>
        </>
      }
    >
      {pair && request ? (
        <div className="space-y-4">
          <div className="rounded-lg bg-muted/50 px-3 py-2 text-sm">
            <div className="font-semibold">{candidateLabel(pair)}</div>
            <div className="text-xs text-muted-foreground">{pairContext(pair)}</div>
          </div>
          <fieldset>
            <legend className="mb-2 text-xs font-semibold text-muted-foreground">Terminy od klienta</legend>
            <div className="flex flex-wrap gap-2">
              {request.slots.map((slot, i) => (
                <label
                  key={slot.start}
                  className={cn(
                    "flex h-11 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm",
                    index === i ? "border-primary bg-primary/10 font-semibold text-primary" : "border-border hover:bg-muted",
                  )}
                >
                  <input
                    type="radio"
                    name="slot-choice"
                    className="sr-only"
                    checked={index === i}
                    onChange={() => setIndex(i)}
                  />
                  {formatSlot(slot)}
                  {mode === "confirm" && request.chosen_index === i ? (
                    <span className="text-xs font-normal text-muted-foreground">(wybór kandydata)</span>
                  ) : null}
                </label>
              ))}
            </div>
          </fieldset>
          {request.note ? <p className="text-xs text-muted-foreground">Notatka DL: {request.note}</p> : null}
          {mode === "confirm" ? (
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={addToOutlook}
                onChange={(e) => setAddToOutlook(e.target.checked)}
                className="mt-0.5 h-4 w-4"
              />
              <span>
                Dodaj blokadę do Outlooka rekrutera
                <span className="block text-xs text-muted-foreground">
                  Bez uczestników — kandydata zaprasza klient.
                </span>
              </span>
            </label>
          ) : null}
          {error ? (
            <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </AppModal>
  );
}
