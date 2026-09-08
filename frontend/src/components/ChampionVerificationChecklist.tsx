"use client";

/**
 * Verification + briefing checklist for the Champion Profile.
 *
 * The Delivery Lead confirms the profile against (a) a conversation with the
 * client — articulating what changed vs. the original request — and (b) a
 * conversation with one of our consultants already working at that client.
 * Then they record a breakout session (Fireflies) explaining the role in
 * their own words — attached here so recruiters can listen to the audio and
 * read the transcript. Soft signal only: nothing here blocks publishing a
 * job. Stamps (who/when) are set server-side.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Mic,
  MinusCircle,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import {
  api,
  championApi,
  EMPTY_CHAMPION_BRIEFING,
  EMPTY_CHAMPION_VERIFICATION,
  type ChampionBriefing,
  type ChampionVerification,
  type ChampionVerificationMethod,
  type ChampionVerificationRequest,
} from "@/lib/api";
import AudioPlayer from "@/components/calls/AudioPlayer";
import { useToast } from "@/components/Toast";
import {
  ReadinessRow,
  type ReadinessRowState,
} from "@/components/v2/jobs/ReadinessRow";
import { cn } from "@/lib/utils";

/**
 * Czy każdy z trzech warunków weryfikacji jest domknięty.
 *
 * Wyliczane TU, a nie w doku, choć to dok liczy z tego licznik „kompletność
 * zlecenia": inaczej ta sama trójka miałaby dwie definicje — jedną rysującą
 * wiersze, drugą liczącą do siedmiu — i wystarczyłaby jedna zmiana reguły, by
 * lista przeczyła liczbie nad nią.
 *
 * `skipped` po stronie konsultanta ZAMYKA pozycję (Delivery Lead świadomie
 * stwierdził, że nie mamy u tego klienta nikogo), ale nie jest weryfikacją —
 * opis wiersza mówi o tym wprost.
 */
export function championVerificationDone(
  verification?: ChampionVerification | null,
  briefing?: ChampionBriefing | null,
): { client: boolean; consultant: boolean; briefing: boolean } {
  const v = verification ?? EMPTY_CHAMPION_VERIFICATION;
  const b = briefing ?? EMPTY_CHAMPION_BRIEFING;
  return {
    client: v.client.status === "verified",
    consultant: v.consultant.status !== "pending",
    briefing: b.status === "attached",
  };
}

const METHOD_LABELS: Record<ChampionVerificationMethod, string> = {
  call: "Rozmowa telefoniczna",
  meeting: "Spotkanie",
  email: "E-mail",
  other: "Inne",
};

function formatDate(iso?: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return "";
  }
}

interface MeetingNoteRow {
  id: number;
  note_type: string;
  content: string;
  created_at?: string;
}

interface NoteListResponse {
  items: MeetingNoteRow[];
  total: number;
}

function noteTitle(n: MeetingNoteRow): string {
  const first = (n.content || "").split("\n", 1)[0] || "";
  return first.replace(/^#+\s*/, "").trim() || `Meeting #${n.id}`;
}

export type ChampionVerificationChecklistVariant = "section" | "rows";

interface ChampionVerificationChecklistProps {
  jobId: number;
  verification?: ChampionVerification | null;
  briefing?: ChampionBriefing | null;
  canEdit: boolean;
  /**
   * `"rows"` — trzy wiersze `ReadinessRow` bez własnej ramki i nagłówka, do
   * wplecenia w JEDNĄ listę gotowości doku kroku 02 (makieta: warunki 1-3
   * z siedmiu). Formularze, mutacje i odtwarzacz nagrania są DOKŁADNIE te
   * same — różni się wyłącznie powłoka. Drugi komplet mutacji oznaczania
   * weryfikacji był jedyną realną alternatywą i rozjechałby się przy
   * pierwszej zmianie kontraktu `POST …/verify`.
   */
  variant?: ChampionVerificationChecklistVariant;
}

export function ChampionVerificationChecklist({
  jobId,
  verification,
  briefing,
  canEdit,
  variant = "section",
}: ChampionVerificationChecklistProps) {
  const qc = useQueryClient();
  const toast = useToast();
  const v = verification ?? EMPTY_CHAMPION_VERIFICATION;
  const b = briefing ?? EMPTY_CHAMPION_BRIEFING;

  const [openForm, setOpenForm] = useState<
    "client" | "consultant" | "briefing" | null
  >(null);
  const [briefingNoteId, setBriefingNoteId] = useState<number | null>(null);
  const [briefingEnrich, setBriefingEnrich] = useState(true);

  // Client form state
  const [method, setMethod] = useState<ChampionVerificationMethod>("call");
  const [corrections, setCorrections] = useState("");
  const [confirmedAsIs, setConfirmedAsIs] = useState(false);

  // Consultant form state
  const [consultantMode, setConsultantMode] = useState<"talked" | "skip">("talked");
  const [consultantId, setConsultantId] = useState<number | null>(null);
  const [consultantManualName, setConsultantManualName] = useState("");
  const [insights, setInsights] = useState("");
  const [skipReason, setSkipReason] = useState("");

  const suggestionsQuery = useQuery({
    queryKey: ["champion-consultant-suggestions", jobId],
    queryFn: () => championApi.consultantSuggestions(jobId).then((r) => r.data),
    enabled: openForm === "consultant",
    staleTime: 5 * 60 * 1000,
  });

  const meetingNotesQuery = useQuery({
    queryKey: ["job-meeting-notes", jobId],
    queryFn: () =>
      api
        .get<NoteListResponse>(`/api/notes?job_id=${jobId}`)
        .then((r) => (r.data.items || []).filter((n) => n.note_type === "meeting")),
    enabled: openForm === "briefing",
  });

  const audioUrlQuery = useQuery({
    queryKey: ["champion-briefing-audio", jobId, b.audio_storage_key ?? ""],
    queryFn: () => championApi.briefingAudioUrl(jobId).then((r) => r.data.url),
    enabled: b.status === "attached" && !!b.audio_storage_key,
    staleTime: 5 * 60 * 1000,
  });

  const briefingMutation = useMutation({
    mutationFn: (noteId: number) =>
      championApi.setBriefing(jobId, noteId, briefingEnrich),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["champion-profile", jobId] });
      qc.invalidateQueries({ queryKey: ["champion-suggestions", jobId] });
      setOpenForm(null);
      setBriefingNoteId(null);
    },
    onError: (e: unknown) => {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Nie udało się podpiąć briefingu.";
      toast.showError(detail);
    },
  });

  const clearBriefingMutation = useMutation({
    mutationFn: () => championApi.clearBriefing(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["champion-profile", jobId] });
    },
    onError: () => toast.showError("Nie udało się odpiąć briefingu."),
  });

  const mutation = useMutation({
    mutationFn: (payload: ChampionVerificationRequest) =>
      championApi.verify(jobId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["champion-profile", jobId] });
      setOpenForm(null);
    },
    onError: (e: unknown) => {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Nie udało się zapisać weryfikacji.";
      toast.showError(detail);
    },
  });

  const clientDone = v.client.status === "verified";
  const consultantDone = v.consultant.status !== "pending";
  const summary = clientDone && consultantDone ? "full" : clientDone || consultantDone ? "partial" : "none";

  const submitClient = () =>
    mutation.mutate({
      side: "client",
      client: {
        method,
        key_corrections: corrections,
        confirmed_as_is: confirmedAsIs,
      },
    });

  const submitConsultant = () => {
    if (consultantMode === "skip") {
      mutation.mutate({
        side: "consultant",
        consultant: { skipped: true, skip_reason: skipReason },
      });
    } else {
      mutation.mutate({
        side: "consultant",
        consultant: {
          consultant_candidate_id: consultantId,
          consultant_name: consultantManualName,
          insights,
        },
      });
    }
  };

  const clientSubmitDisabled =
    mutation.isPending || (!corrections.trim() && !confirmedAsIs);
  const consultantSubmitDisabled =
    mutation.isPending ||
    (consultantMode === "skip"
      ? !skipReason.trim()
      : (!consultantId && !consultantManualName.trim()) || !insights.trim());

  // ── Formularze: JEDNA definicja na trzy pola, używana przez oba warianty ──
  // Wyniesione z markupu sekcji, żeby wariant „rows" mógł je rozwinąć pod
  // swoim wierszem, zamiast dostać własną kopię (patrz `variant` w propsach).
  const clientFormBody =
    openForm === "client" && !clientDone ? (
      <div className="space-y-2">
        <label className="block">
          <span className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
            Forma rozmowy
          </span>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as ChampionVerificationMethod)}
            className="w-full px-2 py-1 text-xs border border-border rounded-md bg-card dark:bg-muted"
            data-testid="client-verification-method"
          >
            {Object.entries(METHOD_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
            Co się zmieniło względem requestu klienta?
          </span>
          <textarea
            value={corrections}
            onChange={(e) => setCorrections(e.target.value)}
            rows={3}
            placeholder="np. klient pisał o Javie 8, realnie migrują na 17; zespół rozproszony, ważniejszy angielski niż w requeście…"
            className="w-full px-2 py-1 text-xs border border-border rounded-md bg-card dark:bg-muted resize-y"
            data-testid="client-verification-corrections"
          />
        </label>
        <label className="inline-flex items-center gap-2 text-xs text-foreground">
          <input
            type="checkbox"
            checked={confirmedAsIs}
            onChange={(e) => setConfirmedAsIs(e.target.checked)}
            data-testid="client-verification-confirmed"
          />
          Request potwierdzony 1:1 — rozmowa odbyta, bez zmian
        </label>
        <div className="flex justify-end">
          <button
            type="button"
            onClick={submitClient}
            disabled={clientSubmitDisabled}
            className="inline-flex items-center gap-1.5 bg-primary hover:bg-primary/90 text-white px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-60"
            data-testid="client-verification-submit"
          >
            {mutation.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Zapisz weryfikację
          </button>
        </div>
      </div>
    ) : null;

  const consultantFormBody =
    openForm === "consultant" && !consultantDone ? (
      <div className="space-y-2">
        <div className="flex gap-3 text-xs">
          <label className="inline-flex items-center gap-1.5">
            <input
              type="radio"
              checked={consultantMode === "talked"}
              onChange={() => setConsultantMode("talked")}
            />
            Rozmawiałem z konsultantem
          </label>
          <label className="inline-flex items-center gap-1.5">
            <input
              type="radio"
              checked={consultantMode === "skip"}
              onChange={() => setConsultantMode("skip")}
              data-testid="consultant-verification-skip-radio"
            />
            Brak konsultanta u klienta
          </label>
        </div>

        {consultantMode === "talked" ? (
          <>
            <label className="block">
              <span className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                Nasi konsultanci u tego klienta
              </span>
              {suggestionsQuery.isLoading ? (
                <div className="text-[11px] text-muted-foreground inline-flex items-center gap-1.5">
                  <Loader2 className="w-3 h-3 animate-spin" /> Szukam konsultantów…
                </div>
              ) : (suggestionsQuery.data?.length ?? 0) > 0 ? (
                <select
                  value={consultantId ?? ""}
                  onChange={(e) =>
                    setConsultantId(e.target.value === "" ? null : Number(e.target.value))
                  }
                  className="w-full px-2 py-1 text-xs border border-border rounded-md bg-card dark:bg-muted"
                  data-testid="consultant-verification-picker"
                >
                  <option value="">— wybierz konsultanta —</option>
                  {suggestionsQuery.data!.map((s) => (
                    <option key={s.candidate_id} value={s.candidate_id}>
                      {s.name}
                      {s.job_title ? ` — ${s.job_title}` : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <div className="text-[11px] text-muted-foreground">
                  System nie znalazł naszych konsultantów u tego klienta — wpisz
                  ręcznie poniżej albo zaznacz „Brak konsultanta”.
                </div>
              )}
            </label>
            {!consultantId && (
              <label className="block">
                <span className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                  Lub wpisz imię i nazwisko
                </span>
                <input
                  type="text"
                  value={consultantManualName}
                  onChange={(e) => setConsultantManualName(e.target.value)}
                  placeholder="np. Jan Kowalski"
                  className="w-full px-2 py-1 text-xs border border-border rounded-md bg-card dark:bg-muted"
                  data-testid="consultant-verification-manual-name"
                />
              </label>
            )}
            <label className="block">
              <span className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                Wnioski z rozmowy — jak wygląda praca na co dzień
              </span>
              <textarea
                value={insights}
                onChange={(e) => setInsights(e.target.value)}
                rows={3}
                placeholder="np. dużo legacy, code review restrykcyjne, standup po angielsku, realnie 3 dni z biura…"
                className="w-full px-2 py-1 text-xs border border-border rounded-md bg-card dark:bg-muted resize-y"
                data-testid="consultant-verification-insights"
              />
            </label>
          </>
        ) : (
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
              Powód pominięcia
            </span>
            <textarea
              value={skipReason}
              onChange={(e) => setSkipReason(e.target.value)}
              rows={2}
              placeholder="np. nowy klient — nie mamy jeszcze nikogo na pokładzie"
              className="w-full px-2 py-1 text-xs border border-border rounded-md bg-card dark:bg-muted resize-y"
              data-testid="consultant-verification-skip-reason"
            />
          </label>
        )}

        <div className="flex justify-end">
          <button
            type="button"
            onClick={submitConsultant}
            disabled={consultantSubmitDisabled}
            className="inline-flex items-center gap-1.5 bg-primary hover:bg-primary/90 text-white px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-60"
            data-testid="consultant-verification-submit"
          >
            {mutation.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Zapisz weryfikację
          </button>
        </div>
      </div>
    ) : null;

  const briefingFormBody =
    openForm === "briefing" && b.status !== "attached" ? (
      <div className="space-y-2">
        <label className="block">
          <span className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
            Meetingi podpięte do tej rekrutacji
          </span>
          {meetingNotesQuery.isLoading ? (
            <div className="text-[11px] text-muted-foreground inline-flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" /> Szukam meetingów…
            </div>
          ) : (meetingNotesQuery.data?.length ?? 0) > 0 ? (
            <select
              value={briefingNoteId ?? ""}
              onChange={(e) =>
                setBriefingNoteId(e.target.value === "" ? null : Number(e.target.value))
              }
              className="w-full px-2 py-1 text-xs border border-border rounded-md bg-card dark:bg-muted"
              data-testid="briefing-note-picker"
            >
              <option value="">— wybierz meeting —</option>
              {meetingNotesQuery.data!.map((n) => (
                <option key={n.id} value={n.id}>
                  {noteTitle(n)}
                </option>
              ))}
            </select>
          ) : (
            <div className="text-[11px] text-muted-foreground">
              Brak meetingów Fireflies podpiętych do tej rekrutacji. Nagraj sesję
              (np. tytuł „Briefing: {"{nazwa roli}"}”) albo podepnij meeting w
              panelu „Meetingi i AI” poniżej.
            </div>
          )}
        </label>
        <label className="inline-flex items-center gap-2 text-xs text-foreground">
          <input
            type="checkbox"
            checked={briefingEnrich}
            onChange={(e) => setBriefingEnrich(e.target.checked)}
            data-testid="briefing-enrich-checkbox"
          />
          Cross-check AI: zaproponuj uzupełnienia profilu z briefingu
        </label>
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() =>
              briefingNoteId !== null && briefingMutation.mutate(briefingNoteId)
            }
            disabled={briefingMutation.isPending || briefingNoteId === null}
            className="inline-flex items-center gap-1.5 bg-primary hover:bg-primary/90 text-white px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-60"
            data-testid="briefing-submit"
          >
            {briefingMutation.isPending && (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            )}
            Ustaw jako briefing
          </button>
        </div>
      </div>
    ) : null;

  const briefingAudioBody =
    b.status === "attached" && b.audio_storage_key ? (
      audioUrlQuery.data ? (
        <AudioPlayer src={audioUrlQuery.data} />
      ) : audioUrlQuery.isLoading ? (
        <div className="text-[11px] text-muted-foreground inline-flex items-center gap-1.5">
          <Loader2 className="w-3 h-3 animate-spin" /> Ładuję nagranie…
        </div>
      ) : (
        <div className="text-[11px] text-muted-foreground">
          Nie udało się załadować nagrania.
        </div>
      )
    ) : null;

  /** „Oznacz"/„Podepnij" ↔ „Cofnij"/„Odepnij" — ta sama akcja w obu wariantach. */
  const rowAction = (
    done: boolean,
    onToggle: () => void,
    doneLabel: string,
    todoLabel: string,
    testId: string,
  ) =>
    canEdit ? (
      <button
        type="button"
        onClick={onToggle}
        className="text-[11px] font-medium text-primary hover:underline"
        data-testid={testId}
      >
        {done ? doneLabel : todoLabel}
      </button>
    ) : undefined;

  if (variant === "rows") {
    const consultantState: ReadinessRowState =
      v.consultant.status === "verified"
        ? "done"
        : v.consultant.status === "skipped"
          ? "neutral"
          : "todo";
    return (
      <>
        <ReadinessRow
          state={clientDone ? "done" : "todo"}
          title="Rozmowa z klientem"
          description={
            clientDone
              ? [
                  v.client.verified_by_name,
                  formatDate(v.client.verified_at),
                  v.client.method ? METHOD_LABELS[v.client.method] : null,
                ]
                  .filter(Boolean)
                  .join(" · ") || "Zweryfikowano"
              : "Do weryfikacji — co klient naprawdę potrzebuje vs. request?"
          }
          action={rowAction(
            clientDone,
            () =>
              clientDone
                ? mutation.mutate({ side: "client", reset: true })
                : setOpenForm(openForm === "client" ? null : "client"),
            "Cofnij",
            "Oznacz",
            "client-verification-toggle",
          )}
          data-testid="readiness-row-client-verification"
        >
          {clientFormBody}
        </ReadinessRow>

        <ReadinessRow
          state={consultantState}
          title="Rozmowa z naszym konsultantem"
          description={
            v.consultant.status === "verified"
              ? [
                  v.consultant.consultant_name || "Konsultant",
                  v.consultant.verified_by_name,
                  formatDate(v.consultant.verified_at),
                ]
                  .filter(Boolean)
                  .join(" · ")
              : v.consultant.status === "skipped"
                ? `Pominięto: ${v.consultant.skip_reason}`
                : "Do weryfikacji — jak wygląda praca u tego klienta na co dzień?"
          }
          action={rowAction(
            consultantDone,
            () =>
              consultantDone
                ? mutation.mutate({ side: "consultant", reset: true })
                : setOpenForm(openForm === "consultant" ? null : "consultant"),
            "Cofnij",
            "Oznacz",
            "consultant-verification-toggle",
          )}
          data-testid="readiness-row-consultant-verification"
        >
          {consultantFormBody}
        </ReadinessRow>

        <ReadinessRow
          state={b.status === "attached" ? "done" : "todo"}
          title="Briefing dla rekruterów"
          description={
            b.status === "attached"
              ? [b.title, b.attached_by_name, formatDate(b.attached_at)]
                  .filter(Boolean)
                  .join(" · ")
              : "Brak nagrania z Fireflies"
          }
          action={rowAction(
            b.status === "attached",
            () =>
              b.status === "attached"
                ? clearBriefingMutation.mutate()
                : setOpenForm(openForm === "briefing" ? null : "briefing"),
            "Odepnij",
            "Podepnij",
            "briefing-toggle",
          )}
          data-testid="readiness-row-briefing"
        >
          {briefingAudioBody ?? briefingFormBody}
        </ReadinessRow>
      </>
    );
  }

  return (
    <section
      className="rounded-xl border border-border dark:border-border p-4 bg-card dark:bg-muted"
      data-testid="champion-verification-checklist"
    >
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-[11px] uppercase tracking-wide text-purple-700 dark:text-purple-300 font-bold inline-flex items-center gap-1.5">
          <ShieldCheck className="w-3.5 h-3.5" />
          Weryfikacja i briefing
        </h3>
        <span
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full font-medium",
            summary === "full" &&
              "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
            summary === "partial" &&
              "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
            summary === "none" &&
              "bg-muted text-muted-foreground border border-border"
          )}
          data-testid="verification-summary-badge"
        >
          {summary === "full"
            ? "Zweryfikowano"
            : summary === "partial"
              ? "Częściowo zweryfikowano"
              : "Niezweryfikowany"}
        </span>
      </header>
      <p className="text-xs text-muted-foreground mb-3">
        Profil nie powinien być przepisanym requestem klienta. Potwierdź go w
        rozmowie z klientem (czego naprawdę potrzebują) i z naszym konsultantem
        pracującym u tego klienta (jak wygląda praca na co dzień).
      </p>

      <div className="space-y-2">
        {/* ── Client row ── */}
        <div className="rounded-lg border border-border dark:border-border bg-muted/50 dark:bg-card/30">
          <div className="flex items-center gap-2 px-3 py-2">
            <Building2 className="w-4 h-4 text-muted-foreground shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-foreground">
                Rozmowa z klientem
              </div>
              {clientDone ? (
                <div className="text-[11px] text-muted-foreground truncate">
                  {v.client.verified_by_name} • {formatDate(v.client.verified_at)}
                  {v.client.method ? ` • ${METHOD_LABELS[v.client.method]}` : ""}
                </div>
              ) : (
                <div className="text-[11px] text-muted-foreground">
                  Co klient naprawdę potrzebuje vs. co napisał w requeście?
                </div>
              )}
            </div>
            {clientDone ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700 dark:text-emerald-400 font-medium">
                <CheckCircle2 className="w-3.5 h-3.5" /> Zweryfikowano
              </span>
            ) : (
              <span className="text-[11px] text-amber-700 dark:text-amber-400 font-medium">
                Do weryfikacji
              </span>
            )}
            {canEdit && (
              <button
                type="button"
                onClick={() =>
                  clientDone
                    ? mutation.mutate({ side: "client", reset: true })
                    : setOpenForm(openForm === "client" ? null : "client")
                }
                className="text-[11px] text-primary hover:text-primary/80 font-medium inline-flex items-center gap-0.5"
                data-testid="client-verification-toggle"
              >
                {clientDone ? (
                  "Cofnij"
                ) : (
                  <>
                    Oznacz
                    {openForm === "client" ? (
                      <ChevronDown className="w-3 h-3" />
                    ) : (
                      <ChevronRight className="w-3 h-3" />
                    )}
                  </>
                )}
              </button>
            )}
          </div>
          {clientDone && (v.client.key_corrections || v.client.confirmed_as_is) && (
            <div className="px-3 pb-2 text-[11px] text-muted-foreground italic border-t border-border/60 pt-1.5">
              {v.client.confirmed_as_is && !v.client.key_corrections
                ? "Request potwierdzony 1:1 po rozmowie."
                : `Zmiany vs request: ${v.client.key_corrections}`}
            </div>
          )}
          {clientFormBody ? (
            <div className="px-3 pb-3 pt-1 border-t border-border/60">
              {clientFormBody}
            </div>
          ) : null}
        </div>

        {/* ── Consultant row ── */}
        <div className="rounded-lg border border-border dark:border-border bg-muted/50 dark:bg-card/30">
          <div className="flex items-center gap-2 px-3 py-2">
            <UserCheck className="w-4 h-4 text-muted-foreground shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-foreground">
                Rozmowa z naszym konsultantem u klienta
              </div>
              {v.consultant.status === "verified" ? (
                <div className="text-[11px] text-muted-foreground truncate">
                  {v.consultant.consultant_name || "Konsultant"} •{" "}
                  {v.consultant.verified_by_name} •{" "}
                  {formatDate(v.consultant.verified_at)}
                </div>
              ) : v.consultant.status === "skipped" ? (
                <div className="text-[11px] text-muted-foreground truncate">
                  Pominięto: {v.consultant.skip_reason}
                </div>
              ) : (
                <div className="text-[11px] text-muted-foreground">
                  Jak naprawdę wygląda praca u tego klienta na co dzień?
                </div>
              )}
            </div>
            {v.consultant.status === "verified" ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700 dark:text-emerald-400 font-medium">
                <CheckCircle2 className="w-3.5 h-3.5" /> Zweryfikowano
              </span>
            ) : v.consultant.status === "skipped" ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground font-medium">
                <MinusCircle className="w-3.5 h-3.5" /> Pominięto
              </span>
            ) : (
              <span className="text-[11px] text-amber-700 dark:text-amber-400 font-medium">
                Do weryfikacji
              </span>
            )}
            {canEdit && (
              <button
                type="button"
                onClick={() =>
                  consultantDone
                    ? mutation.mutate({ side: "consultant", reset: true })
                    : setOpenForm(openForm === "consultant" ? null : "consultant")
                }
                className="text-[11px] text-primary hover:text-primary/80 font-medium inline-flex items-center gap-0.5"
                data-testid="consultant-verification-toggle"
              >
                {consultantDone ? (
                  "Cofnij"
                ) : (
                  <>
                    Oznacz
                    {openForm === "consultant" ? (
                      <ChevronDown className="w-3 h-3" />
                    ) : (
                      <ChevronRight className="w-3 h-3" />
                    )}
                  </>
                )}
              </button>
            )}
          </div>
          {v.consultant.status === "verified" && v.consultant.insights && (
            <div className="px-3 pb-2 text-[11px] text-muted-foreground italic border-t border-border/60 pt-1.5">
              {v.consultant.insights}
            </div>
          )}
          {consultantFormBody ? (
            <div className="px-3 pb-3 pt-1 border-t border-border/60">
              {consultantFormBody}
            </div>
          ) : null}
        </div>

        {/* ── Briefing row ── */}
        <div className="rounded-lg border border-border dark:border-border bg-muted/50 dark:bg-card/30">
          <div className="flex items-center gap-2 px-3 py-2">
            <Mic className="w-4 h-4 text-muted-foreground shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-foreground">
                Briefing dla rekruterów (nagranie)
              </div>
              {b.status === "attached" ? (
                <div className="text-[11px] text-muted-foreground truncate">
                  {b.title} • {b.attached_by_name} • {formatDate(b.attached_at)}
                </div>
              ) : (
                <div className="text-[11px] text-muted-foreground">
                  Nagraj breakout session z Fireflies i opowiedz o roli własnymi
                  słowami — meeting pojawi się tu po synchronizacji.
                </div>
              )}
            </div>
            {b.status === "attached" ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700 dark:text-emerald-400 font-medium">
                <CheckCircle2 className="w-3.5 h-3.5" /> Nagrany
              </span>
            ) : (
              <span className="text-[11px] text-amber-700 dark:text-amber-400 font-medium">
                Brak briefingu
              </span>
            )}
            {canEdit && (
              <button
                type="button"
                onClick={() =>
                  b.status === "attached"
                    ? clearBriefingMutation.mutate()
                    : setOpenForm(openForm === "briefing" ? null : "briefing")
                }
                className="text-[11px] text-primary hover:text-primary/80 font-medium inline-flex items-center gap-0.5"
                data-testid="briefing-toggle"
              >
                {b.status === "attached" ? (
                  "Odepnij"
                ) : (
                  <>
                    Podepnij
                    {openForm === "briefing" ? (
                      <ChevronDown className="w-3 h-3" />
                    ) : (
                      <ChevronRight className="w-3 h-3" />
                    )}
                  </>
                )}
              </button>
            )}
          </div>
          {briefingAudioBody ? (
            <div className="px-3 pb-3 pt-1.5 border-t border-border/60">
              {briefingAudioBody}
            </div>
          ) : null}
          {b.status === "attached" && !b.audio_storage_key && (
            <div className="px-3 pb-2 text-[11px] text-muted-foreground italic border-t border-border/60 pt-1.5">
              Brak audio dla tego meetingu — transkrypcja dostępna w notatkach
              rekrutacji (panel „Meetingi i AI” poniżej).
            </div>
          )}
          {briefingFormBody ? (
            <div className="px-3 pb-3 pt-1 border-t border-border/60">
              {briefingFormBody}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
