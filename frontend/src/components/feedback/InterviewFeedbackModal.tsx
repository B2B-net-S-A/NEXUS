"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Phone, Mail, CheckCircle2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogBody,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { calendarApi, candidatesApi, interviewFeedbackApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

type FeedbackSource = "candidate_side" | "client_side";

type InterviewFeedbackModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  calendarEventId: number;
  /** Wymuszony tab — jeśli brak, wybieramy per default candidate_side i user może przełączyć. */
  initialSource?: FeedbackSource;
  /** Wołane po udanym zapisie (utworzenie albo edycja). */
  onSaved?: () => void;
};

type CalendarEvent = {
  id: number;
  title: string;
  event_type: string;
  start_time: string;
  end_time?: string | null;
  candidate_id?: number | null;
  job_id?: number | null;
  status: string;
};

type CandidateLite = {
  id: number;
  // API kandydata zwraca `name`/`lastname` — do 09.2026 modal czytał
  // `first_name`/`last_name` i podpisywał osobę jako „#196867".
  name?: string | null;
  lastname?: string | null;
  phone?: string | null;
  email?: string | null;
};

type FeedbackRow = {
  id: number;
  calendar_event_id: number | null;
  feedback_source: FeedbackSource;
  overall_impression?: number | null;
  interest_level?: string | null;
  candidate_questions?: string | null;
  concerns?: string | null;
  next_step_preference?: string | null;
  technical_fit?: number | null;
  soft_fit?: number | null;
  overall_fit?: number | null;
  decision?: string | null;
  client_questions?: string | null;
  feedback_summary?: string | null;
};

type CandidateSideFields = {
  overall_impression: number | null;
  interest_level: "hot" | "warm" | "cold" | "dead" | null;
  candidate_questions: string;
  concerns: string;
  next_step_preference: "ready_for_next" | "need_info" | "pass" | null;
};

type ClientSideFields = {
  technical_fit: number | null;
  soft_fit: number | null;
  overall_fit: number | null;
  decision: "advance" | "reject" | "on_hold" | null;
  client_questions: string;
  feedback_summary: string;
};

const EMPTY_CANDIDATE: CandidateSideFields = {
  overall_impression: null,
  interest_level: null,
  candidate_questions: "",
  concerns: "",
  next_step_preference: null,
};

const EMPTY_CLIENT: ClientSideFields = {
  technical_fit: null,
  soft_fit: null,
  overall_fit: null,
  decision: null,
  client_questions: "",
  feedback_summary: "",
};

function candidateDisplayName(c?: CandidateLite | null): string {
  if (!c) return "";
  const parts = [c.name, c.lastname].map((p) => (p ?? "").trim()).filter(Boolean);
  return parts.length ? parts.join(" ") : `#${c.id}`;
}

const BINDING_KEYS = new Set([
  "calendar_event_id",
  "candidate_id",
  "job_id",
  "feedback_source",
]);

export function candidateFieldsFrom(row?: FeedbackRow | null): CandidateSideFields {
  if (!row) return EMPTY_CANDIDATE;
  return {
    overall_impression: row.overall_impression ?? null,
    interest_level: (row.interest_level as CandidateSideFields["interest_level"]) ?? null,
    candidate_questions: row.candidate_questions ?? "",
    concerns: row.concerns ?? "",
    next_step_preference:
      (row.next_step_preference as CandidateSideFields["next_step_preference"]) ?? null,
  };
}

export function clientFieldsFrom(row?: FeedbackRow | null): ClientSideFields {
  if (!row) return EMPTY_CLIENT;
  return {
    technical_fit: row.technical_fit ?? null,
    soft_fit: row.soft_fit ?? null,
    overall_fit: row.overall_fit ?? null,
    decision: (row.decision as ClientSideFields["decision"]) ?? null,
    client_questions: row.client_questions ?? "",
    feedback_summary: row.feedback_summary ?? "",
  };
}

function validateCandidateSide(
  f: CandidateSideFields,
): string | null {
  if (f.overall_impression == null) return "Ocena wrażenia jest wymagana (1-5).";
  if (f.interest_level == null) return "Poziom zainteresowania jest wymagany.";
  if (f.next_step_preference == null) return "Preferencja następnego kroku jest wymagana.";
  return null;
}

function validateClientSide(f: ClientSideFields): string | null {
  if (f.technical_fit == null) return "Technical fit jest wymagany (1-5).";
  if (f.soft_fit == null) return "Soft fit jest wymagany (1-5).";
  if (f.overall_fit == null) return "Overall fit jest wymagany (1-5).";
  if (f.decision == null) return "Decyzja jest wymagana.";
  if (f.feedback_summary.trim().length === 0)
    return "Podsumowanie feedbacku jest wymagane.";
  return null;
}

export function InterviewFeedbackModal({
  open,
  onOpenChange,
  calendarEventId,
  initialSource,
  onSaved,
}: InterviewFeedbackModalProps) {
  const queryClient = useQueryClient();
  const [source, setSource] = useState<FeedbackSource>(
    initialSource ?? "candidate_side",
  );
  const [candidateFields, setCandidateFields] =
    useState<CandidateSideFields>(EMPTY_CANDIDATE);
  const [clientFields, setClientFields] = useState<ClientSideFields>(EMPTY_CLIENT);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (open) {
      setSource(initialSource ?? "candidate_side");
      setCandidateFields(EMPTY_CANDIDATE);
      setClientFields(EMPTY_CLIENT);
      setError(null);
      setSubmitted(false);
    }
  }, [open, initialSource]);

  const eventQuery = useQuery<CalendarEvent>({
    queryKey: ["calendar-event", calendarEventId],
    queryFn: () => calendarApi.getEvent(calendarEventId).then((r) => r.data),
    enabled: open && Number.isFinite(calendarEventId),
  });

  const candidateQuery = useQuery<CandidateLite | null>({
    queryKey: ["candidate-lite", eventQuery.data?.candidate_id],
    queryFn: async () => {
      const cid = eventQuery.data?.candidate_id;
      if (!cid) return null;
      const res = await candidatesApi.get(cid);
      return res.data as CandidateLite;
    },
    enabled: open && !!eventQuery.data?.candidate_id,
  });

  const existingQuery = useQuery<FeedbackRow[]>({
    queryKey: ["interview-feedback", "by-event", calendarEventId],
    queryFn: () =>
      interviewFeedbackApi
        .list({ calendar_event_id: calendarEventId })
        .then((r) => r.data),
    enabled: open && Number.isFinite(calendarEventId),
  });

  const existingForSource = existingQuery.data?.find(
    (row) => row.feedback_source === source,
  );
  const candidateRow = existingQuery.data?.find(
    (row) => row.feedback_source === "candidate_side",
  );
  const clientRow = existingQuery.data?.find(
    (row) => row.feedback_source === "client_side",
  );

  // Prefill zapisanego wpisu per strona — raz na wiersz, żeby odświeżenie
  // listy w tle nie kasowało tego, co użytkownik właśnie wpisuje.
  const prefilled = useRef<{ candidate: number | null; client: number | null }>({
    candidate: null,
    client: null,
  });
  useEffect(() => {
    if (!open) {
      prefilled.current = { candidate: null, client: null };
      return;
    }
    if (candidateRow && prefilled.current.candidate !== candidateRow.id) {
      prefilled.current.candidate = candidateRow.id;
      setCandidateFields(candidateFieldsFrom(candidateRow));
    }
    if (clientRow && prefilled.current.client !== clientRow.id) {
      prefilled.current.client = clientRow.id;
      setClientFields(clientFieldsFrom(clientRow));
    }
  }, [open, candidateRow, clientRow]);

  const saveMutation = useMutation({
    mutationFn: ({
      payload,
      existingId,
    }: {
      payload: Record<string, unknown>;
      existingId: number | null;
    }) => {
      if (existingId == null) return interviewFeedbackApi.create(payload);
      // Edycja: PATCH przyjmuje wyłącznie pola treści — powiązania
      // (wydarzenie, kandydat, rekrutacja, strona) ustalił zapis.
      const fields = Object.fromEntries(
        Object.entries(payload).filter(([key]) => !BINDING_KEYS.has(key)),
      );
      return interviewFeedbackApi.update(existingId, fields);
    },
    onSuccess: () => {
      const jobId = eventQuery.data?.job_id ?? null;
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["interview-feedback"] });
      queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
      queryClient.invalidateQueries({ queryKey: ["calendar-event", calendarEventId] });
      if (jobId != null) {
        queryClient.invalidateQueries({ queryKey: ["hiring-manager-feedback", jobId] });
      }
      setSubmitted(true);
      onSaved?.();
      setTimeout(() => onOpenChange(false), 900);
    },
    onError: (err: unknown) => {
      const msg = apiErrorMessage(err, "Nie udało się zapisać feedbacku.");
      setError(msg);
    },
  });

  const handleSubmit = () => {
    setError(null);
    if (!eventQuery.data?.candidate_id) {
      setError("Event nie ma powiązanego kandydata — nie mogę zapisać feedbacku.");
      return;
    }
    const payload: Record<string, unknown> = {
      calendar_event_id: calendarEventId,
      candidate_id: eventQuery.data.candidate_id,
      job_id: eventQuery.data.job_id ?? null,
      feedback_source: source,
    };
    if (source === "candidate_side") {
      const validation = validateCandidateSide(candidateFields);
      if (validation) {
        setError(validation);
        return;
      }
      Object.assign(payload, {
        overall_impression: candidateFields.overall_impression,
        interest_level: candidateFields.interest_level,
        candidate_questions: candidateFields.candidate_questions || null,
        concerns: candidateFields.concerns || null,
        next_step_preference: candidateFields.next_step_preference,
      });
    } else {
      const validation = validateClientSide(clientFields);
      if (validation) {
        setError(validation);
        return;
      }
      Object.assign(payload, {
        technical_fit: clientFields.technical_fit,
        soft_fit: clientFields.soft_fit,
        overall_fit: clientFields.overall_fit,
        decision: clientFields.decision,
        client_questions: clientFields.client_questions || null,
        feedback_summary: clientFields.feedback_summary,
      });
    }
    saveMutation.mutate({ payload, existingId: existingForSource?.id ?? null });
  };

  const candidate = candidateQuery.data;
  const candidateName = candidateDisplayName(candidate);
  const eventTitle = eventQuery.data?.title ?? `Event #${calendarEventId}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Feedback po interview</DialogTitle>
          <DialogDescription>
            {eventTitle}
            {candidateName ? ` — ${candidateName}` : ""}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-4">
          {/* Kontakt — tel: i mailto: */}
          {candidate && (candidate.phone || candidate.email) && (
            <div className="flex flex-wrap gap-2">
              {candidate.phone && (
                <a
                  href={`tel:${candidate.phone}`}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-md bg-primary/10 text-primary text-sm font-medium hover:bg-primary/15 transition-colors"
                >
                  <Phone className="w-4 h-4" />
                  Zadzwoń: {candidate.phone}
                </a>
              )}
              {candidate.email && (
                <a
                  href={`mailto:${candidate.email}`}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-md bg-muted text-foreground text-sm font-medium hover:bg-muted transition-colors"
                >
                  <Mail className="w-4 h-4" />
                  {candidate.email}
                </a>
              )}
            </div>
          )}

          {/* Source tabs */}
          <div className="flex gap-2 border-b">
            {(["candidate_side", "client_side"] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSource(s)}
                className={
                  "px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px " +
                  (source === s
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground")
                }
              >
                {s === "candidate_side"
                  ? "Feedback od kandydata"
                  : "Feedback od klienta"}
              </button>
            ))}
          </div>

          {existingForSource && !submitted && (
            <div className="p-3 rounded-md bg-muted text-muted-foreground text-sm">
              Feedback tej strony jest już zapisany — zmiany nadpiszą zapisany wpis.
            </div>
          )}

          {/* Candidate-side form */}
          {source === "candidate_side" && (
            <div className="space-y-3">
              <RatingField
                label="Ogólne wrażenie (1-5)"
                value={candidateFields.overall_impression}
                onChange={(v) =>
                  setCandidateFields({ ...candidateFields, overall_impression: v })
                }
              />
              <SelectField
                label="Poziom zainteresowania"
                value={candidateFields.interest_level}
                onChange={(v) =>
                  setCandidateFields({
                    ...candidateFields,
                    interest_level:
                      (v as CandidateSideFields["interest_level"]) ?? null,
                  })
                }
                options={[
                  { value: "hot", label: "🔥 Hot — gotowy iść dalej teraz" },
                  { value: "warm", label: "☀️ Warm — zainteresowany, ale rozważa" },
                  { value: "cold", label: "❄️ Cold — chłodne, niska pilność" },
                  { value: "dead", label: "💀 Dead — rezygnuje" },
                ]}
              />
              <SelectField
                label="Preferencja next step"
                value={candidateFields.next_step_preference}
                onChange={(v) =>
                  setCandidateFields({
                    ...candidateFields,
                    next_step_preference:
                      (v as CandidateSideFields["next_step_preference"]) ?? null,
                  })
                }
                options={[
                  { value: "ready_for_next", label: "✅ Ready for next step" },
                  { value: "need_info", label: "❓ Potrzebuje więcej info" },
                  { value: "pass", label: "🛑 Rezygnuje / pass" },
                ]}
              />
              <TextAreaField
                label="Pytania kandydata (co pytał, co chce wiedzieć)"
                value={candidateFields.candidate_questions}
                onChange={(v) =>
                  setCandidateFields({ ...candidateFields, candidate_questions: v })
                }
                placeholder="Np. o zespół, tech stack, widełki, remote policy…"
              />
              <TextAreaField
                label="Concerns / czerwone flagi"
                value={candidateFields.concerns}
                onChange={(v) =>
                  setCandidateFields({ ...candidateFields, concerns: v })
                }
                placeholder="Wątpliwości kandydata, ryzyka dla procesu…"
              />
            </div>
          )}

          {/* Client-side form */}
          {source === "client_side" && (
            <div className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-2">
                <RatingField
                  label="Technical (1-5)"
                  value={clientFields.technical_fit}
                  onChange={(v) =>
                    setClientFields({ ...clientFields, technical_fit: v })
                  }
                />
                <RatingField
                  label="Soft (1-5)"
                  value={clientFields.soft_fit}
                  onChange={(v) =>
                    setClientFields({ ...clientFields, soft_fit: v })
                  }
                />
                <RatingField
                  label="Overall (1-5)"
                  value={clientFields.overall_fit}
                  onChange={(v) =>
                    setClientFields({ ...clientFields, overall_fit: v })
                  }
                />
              </div>
              <SelectField
                label="Decyzja klienta"
                value={clientFields.decision}
                onChange={(v) =>
                  setClientFields({
                    ...clientFields,
                    decision: (v as ClientSideFields["decision"]) ?? null,
                  })
                }
                options={[
                  { value: "advance", label: "✅ Advance — iść dalej" },
                  { value: "reject", label: "❌ Reject — nie pasuje" },
                  { value: "on_hold", label: "⏸ On hold — zaczekać" },
                ]}
              />
              <TextAreaField
                label="Pytania klienta (co chce jeszcze wiedzieć)"
                value={clientFields.client_questions}
                onChange={(v) =>
                  setClientFields({ ...clientFields, client_questions: v })
                }
                placeholder="Dodatkowe pytania, czego brakowało w CV…"
              />
              <TextAreaField
                label="Podsumowanie feedbacku *"
                value={clientFields.feedback_summary}
                onChange={(v) =>
                  setClientFields({ ...clientFields, feedback_summary: v })
                }
                placeholder="Kluczowe argumenty klienta, reasoning decyzji…"
                required
              />
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm">
              {error}
            </div>
          )}

          {/* Success */}
          {submitted && (
            <div className="p-3 rounded-md bg-green-50 text-green-800 text-sm flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4" />
              Feedback zapisany. Zamykam…
            </div>
          )}
        </DialogBody>

        <DialogFooter>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="px-4 py-2 rounded-md border border-border text-sm text-foreground hover:bg-muted"
          >
            Anuluj
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={saveMutation.isPending || submitted}
            className="px-4 py-2 rounded-md bg-primary text-white text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
          >
            {saveMutation.isPending
              ? "Zapisuję…"
              : existingForSource
                ? "Zapisz zmiany"
                : "Zapisz feedback"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Sub-components ───────────────────────────────────────────────────────────

function RatingField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-foreground mb-1">
        {label}
      </label>
      {/* Pięć przycisków dzieli szerokość kolumny — sztywne 5 × 40 px nie
          mieściło się w 1/3 okna i wchodziło na sąsiednie pole. */}
      <div className="grid grid-cols-5 gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(value === n ? null : n)}
            className={
              "h-10 w-full min-w-0 rounded-md border text-sm font-semibold transition-colors " +
              (value === n
                ? "bg-primary text-white border-primary"
                : "bg-card text-foreground border-border hover:bg-muted")
            }
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string | null;
  onChange: (v: string | null) => void;
  options: { value: string; label: string }[];
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-foreground mb-1">
        {label}
      </label>
      <select
        id={id}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
      >
        <option value="">— wybierz —</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-foreground mb-1">
        {label}
        {required && <span className="text-destructive"> *</span>}
      </label>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={3}
        className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring resize-none"
      />
    </div>
  );
}
