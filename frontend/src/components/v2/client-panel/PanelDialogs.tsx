"use client";

/**
 * Okna panelu klienta: pytanie, zmiana wymagań, „nie pasuje” i terminy rozmowy.
 *
 * Imię i e-mail są niezweryfikowane: serwer nie wysyła na nie automatów, a tu
 * sprawdzamy tylko, czy adres ma kształt adresu. Dane zostają w tej przeglądarce,
 * żeby nie wpisywać ich przy każdym pytaniu.
 */

import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Check, X } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import type { PanelAuthor, PanelCandidate, PanelView } from "@/lib/api/clientPanel";
import { cn } from "@/lib/utils";
import { warsawClock, warsawToday } from "@/lib/warsaw-date";

import { usePanelContext } from "./panel-context";
import {
  MAX_SLOTS,
  SLOT_DURATIONS,
  SLOT_HOURS,
  isValidEmail,
  loadAuthor,
  questionFromHint,
  questionHints,
  saveAuthor,
  slotKey,
  slotKeyLabel,
  slotWeeks,
  togglePicked,
  warsawLocalToIso,
  type SlotKey,
} from "./panel-logic";

const BODY_LIMIT = 2000;
const FIELD_LABEL = "grid gap-1 text-xs text-muted-foreground";
const SELECT_CLASS =
  "h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

const NOT_FIT_REASONS = [
  "Za mało doświadczenia",
  "Brak kluczowej technologii",
  "Stawka",
  "Dostępność",
  "Lokalizacja",
  "Inny powód",
] as const;

/**
 * Dzienny limit panelu (429) ma własne zdanie serwera; `apiErrorMessage` przy 429
 * mówi „odczekaj minutę”, co przy limicie dziennym byłoby nieprawdą.
 */
function submitErrorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response;
  if (response?.status === 429 && typeof response.data?.detail === "string") {
    return response.data.detail;
  }
  return apiErrorMessage(error, fallback);
}

/** Wspólna ścieżka zapisu: dane autora, wysyłka, odświeżenie panelu, toast, błąd w oknie. */
function usePanelSubmit(success: string, fallback: string, onDone: () => void) {
  const { token } = usePanelContext();
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  const [author, setAuthor] = useState(() => loadAuthor());
  const [problem, setProblem] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (send: (who: PanelAuthor) => Promise<void>) =>
      send({ author_name: author.name.trim(), author_email: author.email.trim() }),
    onSuccess: () => {
      saveAuthor({ name: author.name.trim(), email: author.email.trim() });
      void queryClient.invalidateQueries({ queryKey: ["client-panel", token] });
      showSuccess(success);
      onDone();
    },
    onError: (error) => setProblem(submitErrorMessage(error, fallback)),
  });

  const submit = (localProblem: string | null, send: (who: PanelAuthor) => Promise<void>) => {
    const authorProblem = !author.name.trim()
      ? "Podaj imię, żeby opiekun wiedział, z kim rozmawia."
      : !isValidEmail(author.email)
        ? "Podaj poprawny adres e-mail."
        : null;
    const found = localProblem ?? authorProblem;
    setProblem(found);
    if (!found) mutation.mutate(send);
  };

  return { author, setAuthor, problem, submit, sending: mutation.isPending };
}

function AuthorFields({
  author,
  onChange,
}: {
  author: { name: string; email: string };
  onChange: (next: { name: string; email: string }) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <label className={FIELD_LABEL}>
        Twoje imię
        <Input
          value={author.name}
          autoComplete="name"
          maxLength={120}
          onChange={(event) => onChange({ ...author, name: event.target.value })}
        />
      </label>
      <label className={FIELD_LABEL}>
        Twój e-mail
        <Input
          type="email"
          value={author.email}
          autoComplete="email"
          maxLength={200}
          onChange={(event) => onChange({ ...author, email: event.target.value })}
        />
      </label>
    </div>
  );
}

function DialogFooter({
  sendLabel,
  sending,
  disabled,
  onClose,
  onSend,
}: {
  sendLabel: string;
  sending: boolean;
  disabled?: boolean;
  onClose: () => void;
  onSend: () => void;
}) {
  return (
    <>
      <Button variant="outline" onClick={onClose}>
        Anuluj
      </Button>
      <Button disabled={sending || disabled} onClick={onSend}>
        {sending ? "Wysyłam…" : sendLabel}
      </Button>
    </>
  );
}

function Problem({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p role="alert" className="rounded-md bg-destructive/10 px-2.5 py-1.5 text-sm text-destructive">
      {text}
    </p>
  );
}

function Chip({
  on = false,
  children,
  onClick,
}: {
  on?: boolean;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
        "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        on ? "border-primary bg-primary/10 text-primary" : "border-border bg-card hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

export function AskDialog({
  view,
  candidate,
  prefill,
  onClose,
  onSent,
}: {
  view: PanelView;
  candidate: PanelCandidate;
  prefill: string;
  onClose: () => void;
  onSent: () => void;
}) {
  const { transport } = usePanelContext();
  const [body, setBody] = useState(prefill);
  const { author, setAuthor, problem, submit, sending } = usePanelSubmit(
    "Pytanie wysłane do opiekuna procesu",
    "Nie udało się wysłać pytania. Spróbuj ponownie.",
    () => {
      onSent();
      onClose();
    },
  );
  const hints = questionHints(view.requirements, candidate.statuses);
  const ownerName = view.owner?.name;

  const send = () =>
    submit(body.trim() ? null : "Wpisz treść pytania.", (who) =>
      transport.sendQuestion(candidate.public_id, { ...who, body: body.trim() }),
    );

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Pytanie o: ${candidate.name}`}
      footer={
        <DialogFooter sendLabel="Wyślij pytanie" sending={sending} onClose={onClose} onSend={send} />
      }
    >
      <div className="grid gap-2.5">
        {hints.length > 0 ? (
          <div>
            <div className="mb-1 text-xs text-muted-foreground">Podpowiedzi z braków w CV</div>
            <div className="flex flex-wrap gap-1.5">
              {hints.map((hint) => (
                <Chip
                  key={hint.key}
                  onClick={() =>
                    setBody((text) =>
                      text ? `${text}\n${questionFromHint(hint.label)}` : questionFromHint(hint.label),
                    )
                  }
                >
                  {hint.label}
                </Chip>
              ))}
            </div>
          </div>
        ) : null}
        <label className={FIELD_LABEL}>
          Twoje pytanie
          <Textarea
            value={body}
            maxLength={BODY_LIMIT}
            rows={4}
            onChange={(event) => setBody(event.target.value)}
          />
        </label>
        <AuthorFields author={author} onChange={setAuthor} />
        <p className="text-xs text-muted-foreground">
          Trafi od razu do opiekuna procesu{ownerName ? ` (${ownerName})` : ""}. Odpowiedź zobaczysz
          tutaj.
        </p>
        <Problem text={problem} />
      </div>
    </AppModal>
  );
}

export function RequirementsChangeDialog({
  ownerName,
  onClose,
}: {
  ownerName: string | null;
  onClose: () => void;
}) {
  const { transport } = usePanelContext();
  const [body, setBody] = useState("");
  const { author, setAuthor, problem, submit, sending } = usePanelSubmit(
    "Zmiana wysłana do opiekuna procesu",
    "Nie udało się wysłać zmiany. Spróbuj ponownie.",
    onClose,
  );
  const send = () =>
    submit(body.trim() ? null : "Napisz, co się zmieniło.", (who) =>
      transport.sendRequirementsChange({ ...who, body: body.trim() }),
    );

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title="Coś się zmieniło? Popraw wymagania"
      footer={
        <DialogFooter sendLabel="Wyślij zmianę" sending={sending} onClose={onClose} onSend={send} />
      }
    >
      <div className="grid gap-2.5">
        <label className={FIELD_LABEL}>
          Co się zmieniło
          <Textarea
            value={body}
            maxLength={BODY_LIMIT}
            rows={4}
            onChange={(event) => setBody(event.target.value)}
          />
        </label>
        <AuthorFields author={author} onChange={setAuthor} />
        <p className="text-xs text-muted-foreground">
          Zmiana trafi do opiekuna procesu{ownerName ? ` (${ownerName})` : ""}, a wymagania poprawi
          Delivery Lead.
        </p>
        <Problem text={problem} />
      </div>
    </AppModal>
  );
}

export function NotFitDialog({
  view,
  candidate,
  onClose,
}: {
  view: PanelView;
  candidate: PanelCandidate;
  onClose: () => void;
}) {
  const { transport } = usePanelContext();
  const [reasons, setReasons] = useState<string[]>([]);
  const [body, setBody] = useState("");
  const { author, setAuthor, problem, submit, sending } = usePanelSubmit(
    "Zapisane. Opiekun dostał powód.",
    "Nie udało się zapisać. Spróbuj ponownie.",
    onClose,
  );
  // Bez stawki w panelu powód „Stawka” byłby o czymś, czego klient tu nie widzi.
  const options = NOT_FIT_REASONS.filter(
    (reason) => reason !== "Stawka" || view.panel.show_rate,
  );
  const toggle = (reason: string) =>
    setReasons((current) =>
      current.includes(reason) ? current.filter((item) => item !== reason) : [...current, reason],
    );
  const send = () =>
    submit(reasons.length > 0 ? null : "Wybierz co najmniej jeden powód.", (who) =>
      transport.sendNotFit(candidate.public_id, {
        ...who,
        reasons,
        ...(body.trim() ? { body: body.trim() } : {}),
      }),
    );

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Dlaczego ${candidate.name} nie pasuje?`}
      footer={<DialogFooter sendLabel="Zapisz" sending={sending} onClose={onClose} onSend={send} />}
    >
      <div className="grid gap-2.5">
        <div className="flex flex-wrap gap-1.5">
          {options.map((reason) => (
            <Chip key={reason} on={reasons.includes(reason)} onClick={() => toggle(reason)}>
              {reason}
            </Chip>
          ))}
        </div>
        <label className={FIELD_LABEL}>
          Co jeszcze warto wiedzieć? (opcjonalnie)
          <Textarea
            value={body}
            maxLength={BODY_LIMIT}
            rows={3}
            placeholder="Na tej podstawie dobieramy kolejne osoby."
            onChange={(event) => setBody(event.target.value)}
          />
        </label>
        <AuthorFields author={author} onChange={setAuthor} />
        <Problem text={problem} />
      </div>
    </AppModal>
  );
}

export function SlotsDialog({
  candidate,
  onClose,
  onSent,
}: {
  candidate: PanelCandidate;
  onClose: () => void;
  onSent: () => void;
}) {
  const { transport } = usePanelContext();
  const weeks = useMemo(() => slotWeeks(warsawToday(), warsawClock()), []);
  const [weekIndex, setWeekIndex] = useState(0);
  const [picked, setPicked] = useState<SlotKey[]>([]);
  const [duration, setDuration] = useState<number>(SLOT_DURATIONS[0]);
  const [interviewers, setInterviewers] = useState("");
  const [prepNote, setPrepNote] = useState("");
  const { author, setAuthor, problem, submit, sending } = usePanelSubmit(
    "Terminy wysłane do opiekuna procesu",
    "Nie udało się wysłać terminów. Spróbuj ponownie.",
    () => {
      onSent();
      onClose();
    },
  );
  const week = weeks[weekIndex];
  const holidays = week?.days.filter((day) => day.holiday).map((day) => day.label.slice(3)) ?? [];

  const send = () =>
    submit(picked.length > 0 ? null : "Zaznacz co najmniej jeden termin.", (who) =>
      transport.sendInterview(candidate.public_id, {
        ...who,
        duration_minutes: duration,
        slots: picked.map((key) => ({ start: warsawLocalToIso(key) })),
        ...(interviewers.trim() ? { interviewers: interviewers.trim() } : {}),
        ...(prepNote.trim() ? { prep_note: prepNote.trim() } : {}),
      }),
    );

  return (
    <AppModal
      open
      size="xl"
      onOpenChange={(open) => !open && onClose()}
      title={`Rozmowa: ${candidate.name}`}
      footer={
        <DialogFooter
          sendLabel="Wyślij terminy"
          sending={sending}
          disabled={picked.length === 0}
          onClose={onClose}
          onSend={send}
        />
      }
    >
      <div className="grid gap-3.5 md:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0">
          <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span className="min-w-0">
              Zaznacz terminy, które Ci pasują. Tydzień {week?.label}
              {holidays.length > 0 ? `, ${holidays.join(", ")} to dzień wolny` : ""}.
            </span>
            {weeks.length > 1 ? (
              <span className="ml-auto flex items-center gap-1">
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label="Poprzedni tydzień"
                  disabled={weekIndex === 0}
                  onClick={() => setWeekIndex((index) => index - 1)}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label="Następny tydzień"
                  disabled={weekIndex === weeks.length - 1}
                  onClick={() => setWeekIndex((index) => index + 1)}
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              </span>
            ) : null}
          </div>
          {week ? (
            <div
              className="grid grid-cols-[40px_repeat(5,minmax(0,1fr))] gap-px overflow-hidden rounded-lg border border-border bg-border text-xs"
              data-testid="slots-grid"
            >
              <div className="bg-card" />
              {week.days.map((day) => (
                <div key={day.ymd} className="bg-card px-0.5 py-1 text-center font-semibold">
                  {day.label}
                </div>
              ))}
              {SLOT_HOURS.map((hour) => (
                <div key={hour} className="contents">
                  <div className="bg-card py-1 text-center text-[11px] text-muted-foreground">
                    {hour}
                  </div>
                  {week.days.map((day) => {
                    const key = slotKey(day.ymd, hour);
                    if (!day.hours.includes(hour)) {
                      return <div key={key} className="bg-muted" aria-hidden />;
                    }
                    const on = picked.includes(key);
                    return (
                      <button
                        key={key}
                        type="button"
                        aria-pressed={on}
                        aria-label={slotKeyLabel(key)}
                        onClick={() => setPicked((current) => togglePicked(current, key))}
                        className={cn(
                          "grid min-h-6 place-items-center transition-colors pointer-coarse:min-h-9",
                          "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                          on
                            ? "bg-primary text-primary-foreground"
                            : "bg-card hover:bg-primary/10",
                        )}
                      >
                        {on ? <Check className="h-3 w-3" /> : null}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              W najbliższych dwóch tygodniach nie ma dni roboczych. Napisz do opiekuna procesu.
            </p>
          )}
        </div>
        <div className="grid content-start gap-2">
          <label className={FIELD_LABEL}>
            Długość
            <select
              className={SELECT_CLASS}
              value={duration}
              onChange={(event) => setDuration(Number(event.target.value))}
            >
              {SLOT_DURATIONS.map((minutes) => (
                <option key={minutes} value={minutes}>
                  {minutes} min
                </option>
              ))}
            </select>
          </label>
          <div>
            <div className="mb-1 text-xs text-muted-foreground" data-testid="slots-count">
              Wybrane ({picked.length} z {MAX_SLOTS})
            </div>
            {picked.length === 0 ? (
              <p className="text-xs text-muted-foreground">Zaznacz co najmniej jeden termin.</p>
            ) : (
              picked.map((key) => (
                <div
                  key={key}
                  className="mb-1 flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-sm tabular-nums"
                >
                  {slotKeyLabel(key)}
                  <button
                    type="button"
                    aria-label={`Usuń ${slotKeyLabel(key)}`}
                    className="hit-area ml-auto text-muted-foreground hover:text-foreground"
                    onClick={() => setPicked((current) => togglePicked(current, key))}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>
          <label className={FIELD_LABEL}>
            Kto rozmawia (opcjonalnie)
            <Input
              value={interviewers}
              maxLength={200}
              placeholder="np. architekt z zespołu"
              onChange={(event) => setInterviewers(event.target.value)}
            />
          </label>
          <label className={FIELD_LABEL}>
            O czym przygotować kandydata (opcjonalnie)
            <Textarea
              value={prepNote}
              maxLength={600}
              rows={2}
              placeholder="np. przegląd kodu"
              onChange={(event) => setPrepNote(event.target.value)}
            />
          </label>
          <AuthorFields author={author} onChange={setAuthor} />
          <p className="text-xs text-muted-foreground">
            Kandydat wybierze termin i przejdzie przygotowanie. Zaproszenie do Teams wysyłasz Ty, po
            potwierdzeniu godziny.
          </p>
          <Problem text={problem} />
        </div>
      </div>
    </AppModal>
  );
}
