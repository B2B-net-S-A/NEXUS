"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { interviewCycleApi } from "@/lib/api/interviewCycle";
import {
  prepMeetingsApi,
  prepSuggestionsQueryKey,
  type PrepSuggestion,
} from "@/lib/api/prepMeetings";
import {
  candidateLabel,
  formatSlot,
  pairContext,
  type PairInfo,
  type SlotRequest,
} from "@/lib/interview-cycle";
import {
  candidateWindowError,
  checkManualPrep,
  dayStrip,
  hhmm,
  interviewStart,
  isWindow,
  localDay,
  manualStart,
  nearestFreeStarts,
  overlaps,
  prepDays,
  prepWhen,
  slotPassed,
  spanOf,
  windowBounds,
  type ManualPrepCheck,
  type Span,
} from "@/lib/interview-pick";
import { useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";

const INPUT =
  "h-9 rounded-md border border-border bg-card px-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

type PrepPick = { kind: "option"; start: string; end: string } | { kind: "manual" } | { kind: "none" };
/** „Inna godzina…” — dzień i godzina z pól (czas przeglądarki). */
type ManualTime = { day: string; time: string };

function newRequestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * „Umów rozmowę i prepy” (20.10.2026, PR 2 uproszczenia cyklu): rekruter po
 * jednym telefonie do kandydata wybiera termin od klienta i od razu godziny
 * obu prepów — Prep 1 z wolnych okien w kalendarzu Delivery Leada, Prep 2
 * ze swojego. Jeden przycisk wybiera termin i wysyła oba zaproszenia Teams.
 * Do tej pory: „Wyślij do DL”, potem dwa razy osobne „Zaplanuj prep” z
 * godziną zgadywaną bez kalendarza i ustaleniami z DL na Teams.
 */
export function PickInterviewDialog({
  open,
  onOpenChange,
  pair,
  request,
  onInvalidate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pair: PairInfo | null;
  request: SlotRequest | null;
  onInvalidate: () => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const currentUserId = useAuthStore((st) => st.user?.id ?? null);
  const [index, setIndex] = useState<number | null>(null);
  const [windowTime, setWindowTime] = useState("");
  const [candFrom, setCandFrom] = useState("");
  const [candTo, setCandTo] = useState("");
  const [picks, setPicks] = useState<Record<number, PrepPick | undefined>>({});
  const [manual, setManual] = useState<Record<number, ManualTime | undefined>>({});
  const [error, setError] = useState<string | null>(null);
  const requestIds = useRef<Record<number, string>>({});

  useEffect(() => {
    if (!open) return;
    const only =
      request?.slots.length === 1 && !slotPassed(request.slots[0], request.duration_minutes) ? 0 : null;
    setIndex(only);
    setWindowTime(only != null && request ? (windowBounds(request.slots[0], request.duration_minutes)?.from ?? "") : "");
    setCandFrom("");
    setCandTo("");
    setPicks({});
    setManual({});
    setError(null);
    requestIds.current = { 1: newRequestId(), 2: newRequestId() };
  }, [open, request]);

  const duration = request?.duration_minutes ?? 60;
  const slot = request && index != null ? request.slots[index] : null;
  const start = slot ? interviewStart(slot, windowTime, duration) : null;
  const windowError = candidateWindowError(candFrom, candTo);

  const params =
    pair && start && !windowError
      ? {
          candidateId: pair.candidate_id,
          jobId: pair.job_id,
          interviewStart: start,
          candidateFrom: candFrom || null,
          candidateTo: candTo || null,
        }
      : null;
  const suggestions = useQuery({
    queryKey: params ? prepSuggestionsQueryKey(params) : ["interview-cycle", "preps", "suggestions", "off"],
    queryFn: () => prepMeetingsApi.suggestions(params!),
    enabled: open && params != null,
    staleTime: 60_000,
  });

  // Nowe podpowiedzi = polecana godzina zaznaczona od razu; wybór ręczny
  // rekrutera zostaje, dopóki ta godzina jest na liście.
  useEffect(() => {
    if (!suggestions.data) return;
    setPicks((prev) => {
      const next: Record<number, PrepPick | undefined> = {};
      for (const p of suggestions.data.preps) {
        const kept = prev[p.prep_no];
        if (kept?.kind === "none" || kept?.kind === "manual") next[p.prep_no] = kept;
        else if (kept?.kind === "option" && p.options.some((o) => o.start === kept.start)) next[p.prep_no] = kept;
        else next[p.prep_no] = p.options[0] ? { kind: "option", ...p.options[0] } : undefined;
      }
      return next;
    });
  }, [suggestions.data]);

  // Godzina prepu: podpowiedź albo „Inna godzina…”, już zaplanowany prep też
  // się liczy (drugi prep nie może na niego wpaść).
  const spans = useMemo(() => {
    const out: Record<number, Span | null> = {};
    for (const p of suggestions.data?.preps ?? []) {
      const pick = picks[p.prep_no];
      const typed = manual[p.prep_no];
      const manualAt = pick?.kind === "manual" && typed ? manualStart(typed.day, typed.time) : null;
      out[p.prep_no] = p.scheduled_start
        ? spanOf(p.scheduled_start, p.minutes)
        : pick?.kind === "option"
          ? { start: pick.start, end: pick.end }
          : manualAt
            ? spanOf(manualAt, p.minutes)
            : null;
    }
    return out;
  }, [suggestions.data, picks, manual]);

  const otherOf = (prepNo: number): (Span & { prepNo: number }) | null => {
    const no = prepNo === 1 ? 2 : 1;
    const span = spans[no];
    // Pierwszeństwo ma Prep 1: przy Prepie 1 liczy się tylko już zaplanowany Prep 2.
    if (!span) return null;
    if (prepNo === 1 && !suggestions.data?.preps.find((p) => p.prep_no === 2)?.scheduled_start) return null;
    return { ...span, prepNo: no };
  };

  const checks = useMemo(() => {
    const out: Record<number, ManualPrepCheck | null> = {};
    for (const p of suggestions.data?.preps ?? []) {
      const span = spans[p.prep_no];
      out[p.prep_no] =
        picks[p.prep_no]?.kind === "manual" && span && start
          ? checkManualPrep({
              prepNo: p.prep_no,
              start: span.start,
              minutes: p.minutes,
              interviewStart: start,
              busy: p.calendar === "ok" ? (p.busy ?? []) : null,
              organizerName: p.organizer?.name ?? "Prowadzący",
              other: otherOf(p.prep_no),
            })
          : null;
    }
    return out;
    // otherOf czyta tylko spans i suggestions.data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestions.data, picks, spans, start]);

  // Dwa prepy nie mogą wypaść o tej samej godzinie: podpowiedź Prepu 2, która
  // nachodzi na Prep 1, przeskakuje na pierwszą wolną godzinę (albo „później”).
  const prep1Span = spans[1] ?? null;
  useEffect(() => {
    const p2 = picks[2];
    if (!prep1Span || p2?.kind !== "option" || !overlaps(prep1Span, p2)) return;
    const prep2 = suggestions.data?.preps.find((p) => p.prep_no === 2);
    const free = prep2?.options.find((o) => !overlaps(o, prep1Span));
    setPicks((prev) => ({ ...prev, 2: free ? { kind: "option", ...free } : { kind: "none" } }));
  }, [picks, suggestions.data, prep1Span]);

  const prepsEnabled = suggestions.data?.enabled ?? false;
  const openPrep = (p: { scheduled_start: string | null; organizer: unknown }) => !p.scheduled_start && p.organizer != null;
  const toInvite = useMemo(
    () =>
      (suggestions.data?.preps ?? []).filter((p) => {
        if (!openPrep(p)) return false;
        const kind = picks[p.prep_no]?.kind;
        if (kind === "option") return true;
        return kind === "manual" && spans[p.prep_no] != null && (checks[p.prep_no]?.blocks.length ?? 0) === 0;
      }),
    [suggestions.data, picks, spans, checks],
  );
  // „Inna godzina…” bez godziny albo z blokadą — główny przycisk czeka.
  const manualPending = (suggestions.data?.preps ?? []).some(
    (p) =>
      openPrep(p) &&
      picks[p.prep_no]?.kind === "manual" &&
      (spans[p.prep_no] == null || (checks[p.prep_no]?.blocks.length ?? 0) > 0),
  );

  const submit = useMutation({
    mutationFn: async (withPreps: boolean) => {
      if (!request || index == null || !start) throw new Error("no-slot");
      const chosen = await interviewCycleApi.chooseSlot(request.id, index, slot && isWindow(slot) ? start : null);
      const failed: string[] = [];
      if (withPreps && pair) {
        for (const p of toInvite) {
          const span = spans[p.prep_no];
          if (!span || !p.organizer) continue;
          try {
            await prepMeetingsApi.create({
              candidate_id: pair.candidate_id,
              job_id: pair.job_id,
              prep_no: p.prep_no,
              organizer_user_id: p.organizer.id,
              start: span.start,
              end: span.end,
              // Planujący za kogoś jest na liście zaproszonych (D3, 17.10.2026).
              attendee_user_ids:
                currentUserId != null && currentUserId !== p.organizer.id ? [currentUserId] : [],
              client_request_id: requestIds.current[p.prep_no],
              // Ostrzeżenie „ma wtedy zajęte” było na ekranie — zapis świadomy.
              accept_busy: checks[p.prep_no]?.busy != null,
            });
          } catch (err) {
            failed.push(`Prep ${p.prep_no}: ${apiErrorMessage(err, "nie powstał")}`);
          }
        }
      }
      return {
        failed,
        invited: withPreps ? toInvite.length - failed.length : 0,
        // 0487: wybór od razu wpisuje rozmowę do kalendarza (chyba że to możliwe przełożenie).
        inCalendar: chosen?.status === "confirmed",
        outlookFailed: chosen?.outlook === "failed",
      };
    },
    onSuccess: ({ failed, invited, inCalendar, outlookFailed }) => {
      onInvalidate();
      qc.invalidateQueries({ queryKey: ["interview-cycle", "preps"] });
      const head = inCalendar
        ? "Rozmowa jest w kalendarzu — DL potwierdzi ją klientowi."
        : "Termin wysłany do DL — potwierdzi go u klienta.";
      if (outlookFailed) {
        toast.showError(
          `${head} Blokady nie udało się dodać do Outlooka rekrutera — rozmowa jest tylko w NEXUSIE.`,
        );
      } else if (failed.length) {
        toast.showError(`${head} ${failed.join(" ")} Zaplanuj go z panelu osoby.`);
      } else {
        toast.showSuccess(invited > 0 ? `${head} Zaproszenia na prepy wysłane (${invited}).` : head);
      }
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać wyboru.")),
  });

  const canSubmit = index != null && start != null && !submit.isPending;
  const primaryLabel =
    prepsEnabled && (toInvite.length > 0 || manualPending)
      ? `Wybierz termin i zaproś na prepy (${toInvite.length})`
      : // 0487: wybór od razu wpisuje rozmowę do kalendarza — to samo słowo co dymek po zapisie.
        "Wpisz do kalendarza";

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Umów rozmowę i prepy"
      description="Po telefonie do kandydata: termin u klienta i godziny obu prepów w jednym kroku."
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground"
          >
            Anuluj
          </button>
          {prepsEnabled && (toInvite.length > 0 || manualPending) ? (
            <button
              type="button"
              disabled={!canSubmit}
              onClick={() => {
                setError(null);
                submit.mutate(false);
              }}
              className="h-9 rounded-md border border-border bg-card px-4 text-sm font-semibold hover:bg-muted disabled:opacity-50"
            >
              Tylko termin
            </button>
          ) : null}
          <button
            type="button"
            disabled={!canSubmit || (prepsEnabled && manualPending)}
            onClick={() => {
              setError(null);
              submit.mutate(true);
            }}
            className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {primaryLabel}
          </button>
        </>
      }
    >
      {pair && request ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm">
            <div>
              <div className="font-semibold">{candidateLabel(pair)}</div>
              <div className="text-xs text-muted-foreground">{pairContext(pair)}</div>
            </div>
            {pair.candidate_phone ? (
              <a href={`tel:${pair.candidate_phone}`} className="text-xs font-semibold text-primary hover:underline">
                {pair.candidate_phone}
              </a>
            ) : null}
          </div>

          <fieldset className="space-y-2">
            <legend className="mb-1 text-xs font-semibold text-muted-foreground">Termin u klienta</legend>
            {request.slots.map((s, i) => {
              const bounds = windowBounds(s, duration);
              const selected = index === i;
              const passed = slotPassed(s, duration);
              return (
                <div
                  key={`${s.start}-${i}`}
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm",
                    selected ? "border-primary bg-primary/5" : "border-border",
                    passed && "opacity-60",
                  )}
                >
                  <label className={cn("flex items-center gap-2", passed ? "cursor-not-allowed" : "cursor-pointer")}>
                    <input
                      type="radio"
                      name="pick-slot"
                      checked={selected}
                      disabled={passed}
                      onChange={() => {
                        setIndex(i);
                        setWindowTime(bounds?.from ?? "");
                      }}
                      className="h-4 w-4"
                    />
                    <span className="font-semibold">
                      {bounds
                        ? `${formatSlot({ start: s.start, end: null })} · okno ${bounds.from}–${hhmm(s.window_end as string)}`
                        : formatSlot(s)}
                    </span>
                    {passed ? <span className="text-xs text-muted-foreground">· termin minął</span> : null}
                  </label>
                  {bounds && selected ? (
                    <label className="mt-2 flex items-center gap-2 pl-6 text-xs text-muted-foreground">
                      Godzina z kandydatem
                      <input
                        type="time"
                        value={windowTime}
                        min={bounds.from}
                        max={bounds.to}
                        step={900}
                        onChange={(e) => setWindowTime(e.target.value)}
                        className={INPUT}
                      />
                      {start == null ? (
                        <span className="text-destructive">
                          Między {bounds.from} a {bounds.to}.
                        </span>
                      ) : null}
                    </label>
                  ) : null}
                </div>
              );
            })}
            {request.note ? (
              <p className="whitespace-pre-line text-xs text-muted-foreground">Notatka DL: {request.note}</p>
            ) : null}
          </fieldset>

          <fieldset className="space-y-2">
            <legend className="mb-1 text-xs font-semibold text-muted-foreground">
              Kiedy kandydat może na prepy? (opcjonalnie)
            </legend>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <label className="flex items-center gap-1.5">
                od
                <input type="time" value={candFrom} onChange={(e) => setCandFrom(e.target.value)} className={INPUT} />
              </label>
              <label className="flex items-center gap-1.5">
                do
                <input type="time" value={candTo} onChange={(e) => setCandTo(e.target.value)} className={INPUT} />
              </label>
              <span className="text-xs text-muted-foreground">
                {windowError ?? "Puste = godziny pracy (8–18)."}
              </span>
            </div>
          </fieldset>

          {start == null ? (
            <p className="text-xs text-muted-foreground">Wybierz termin, a podpowiemy godziny prepów.</p>
          ) : suggestions.isPending && params ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> Sprawdzam kalendarze…
            </p>
          ) : suggestions.isError ? (
            <p role="alert" className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
              {apiErrorMessage(suggestions.error, "Nie udało się podpowiedzieć godzin prepów.")} Prepy zaplanujesz
              z panelu osoby.
            </p>
          ) : suggestions.isSuccess && !prepsEnabled ? (
            <p className="text-xs text-muted-foreground">
              Planowanie prepów w Teams jest wyłączone — zaplanujesz je osobno.
            </p>
          ) : suggestions.isSuccess ? (
            <div className="space-y-3">
              {suggestions.data.preps.map((p) => (
                <PrepPicker
                  key={p.prep_no}
                  prep={p}
                  interviewStart={start}
                  // Pierwszeństwo ma Prep 1 — wyłączamy tylko godziny Prepu 2.
                  other={otherOf(p.prep_no)}
                  pick={picks[p.prep_no]}
                  manual={manual[p.prep_no]}
                  span={spans[p.prep_no] ?? null}
                  check={checks[p.prep_no] ?? null}
                  onPick={(next) => {
                    if (next.kind === "manual" && !manual[p.prep_no]) {
                      const days = prepDays(start);
                      const suggested = p.options[0] ? localDay(new Date(p.options[0].start)) : null;
                      const day =
                        days.find((d) => d.value === suggested)?.value ??
                        days[Math.max(0, days.length - 2)]?.value ??
                        "";
                      setManual((prev) => ({ ...prev, [p.prep_no]: { day, time: "" } }));
                    }
                    setPicks((prev) => ({ ...prev, [p.prep_no]: next }));
                  }}
                  onManual={(next) => setManual((prev) => ({ ...prev, [p.prep_no]: next }))}
                />
              ))}
            </div>
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

function PrepPicker({
  prep,
  interviewStart,
  other,
  pick,
  manual,
  span,
  check,
  onPick,
  onManual,
}: {
  prep: PrepSuggestion;
  interviewStart: string;
  /** Drugi prep tej osoby — godziny, które na niego nachodzą, są wyłączone. */
  other: (Span & { prepNo: number }) | null;
  pick: PrepPick | undefined;
  manual: ManualTime | undefined;
  /** Godzina tego prepu (podpowiedź albo wpisana). */
  span: Span | null;
  check: ManualPrepCheck | null;
  onPick: (pick: PrepPick) => void;
  onManual: (next: ManualTime) => void;
}) {
  const who = prep.organizer?.name ?? "brak prowadzącego";
  const lead = prep.prep_no === 1 ? "prowadzi Delivery Lead" : "prowadzi rekruter";
  const isManual = pick?.kind === "manual";
  const chip = (on: boolean) =>
    cn(
      "h-9 rounded-md border px-3 text-sm disabled:cursor-not-allowed disabled:opacity-40",
      on ? "border-primary bg-primary/10 font-semibold text-primary" : "border-border hover:bg-muted",
    );
  return (
    <div className={cn("rounded-lg border p-3", isManual ? "border-primary" : "border-border")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm">
          <span className="font-semibold">Prep {prep.prep_no}</span>
          <span className="text-muted-foreground">
            {" "}
            · {lead}: {who} · Teams {prep.minutes} min
          </span>
        </div>
        {prep.calendar === "ok" ? (
          <span className="rounded-full bg-success-muted px-2 py-0.5 text-xs text-success-muted-foreground">
            kalendarz sprawdzony
          </span>
        ) : prep.calendar === "unavailable" ? (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            kalendarz niedostępny — godziny bez sprawdzenia
          </span>
        ) : null}
      </div>
      {prep.scheduled_start ? (
        <p className="mt-2 text-xs text-muted-foreground">Już zaplanowany: {prepWhen(prep.scheduled_start)}.</p>
      ) : !prep.organizer ? (
        <p className="mt-2 text-xs text-muted-foreground">Rekrutacja nie ma prowadzącego — zaplanuj prep z panelu osoby.</p>
      ) : (
        <>
          {prep.options.length === 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Brak wolnej godziny przed rozmową w godzinach kandydata — wpisz inną godzinę albo zaplanuj później.
            </p>
          ) : null}
          <div role="radiogroup" aria-label={`Godzina Prepu ${prep.prep_no}`} className="mt-2 flex flex-wrap gap-2">
            {prep.options.map((o, i) => {
              const on = pick?.kind === "option" && pick.start === o.start;
              const clash = other != null && overlaps(o, other);
              return (
                <button
                  key={o.start}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  disabled={clash}
                  title={clash ? "W tym czasie jest drugi prep" : undefined}
                  onClick={() => onPick({ kind: "option", start: o.start, end: o.end })}
                  className={chip(on)}
                >
                  {prepWhen(o.start)}
                  {i === 0 ? " · polecany" : ""}
                </button>
              );
            })}
            <button
              type="button"
              role="radio"
              aria-checked={isManual}
              onClick={() => onPick({ kind: "manual" })}
              className={cn(chip(isManual), !isManual && "border-dashed border-primary text-primary")}
            >
              Inna godzina…
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={pick?.kind === "none"}
              onClick={() => onPick({ kind: "none" })}
              className={cn(chip(pick?.kind === "none"), pick?.kind !== "none" && "text-muted-foreground")}
            >
              Zaplanuję później
            </button>
          </div>
          {isManual && manual ? (
            <ManualPrepTime
              prep={prep}
              interviewStart={interviewStart}
              other={other}
              manual={manual}
              span={span}
              check={check}
              onManual={onManual}
            />
          ) : null}
        </>
      )}
      {prep.prep_no === 2 ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Kandydat nie znajdzie czasu na Prep 2? „Pomiń Prep 2” w panelu osoby — jak dotąd: rozmowa dziś albo w
          następny dzień roboczy, Prep 1 za kandydatem, powód i telefon przed rozmową.
        </p>
      ) : null}
    </div>
  );
}

/**
 * „Inna godzina…” (22.10.2026): dzień, godzina i pasek dnia prowadzącego
 * z jego zajętością. Zajęte = ostrzeżenie z najbliższymi wolnymi startami,
 * po rozmowie albo na drugim prepie = blokada.
 */
function ManualPrepTime({
  prep,
  interviewStart,
  other,
  manual,
  span,
  check,
  onManual,
}: {
  prep: PrepSuggestion;
  interviewStart: string;
  other: (Span & { prepNo: number }) | null;
  manual: ManualTime;
  span: Span | null;
  check: ManualPrepCheck | null;
  onManual: (next: ManualTime) => void;
}) {
  const days = prepDays(interviewStart);
  const busy = prep.calendar === "ok" ? (prep.busy ?? []) : null;
  const strip = busy ? dayStrip(manual.day, busy, span) : null;
  const who = prep.organizer?.name ?? "prowadzącego";
  const nearest =
    busy && check?.busy && span
      ? nearestFreeStarts({
          day: manual.day,
          around: span.start,
          minutes: prep.minutes,
          interviewStart,
          busy,
          other,
        })
      : [];
  const id = `prep-${prep.prep_no}-manual`;
  return (
    <div className="mt-3 space-y-3 rounded-lg bg-muted/40 p-3" data-testid={id}>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1.5">
          Dzień
          <select
            value={manual.day}
            onChange={(e) => onManual({ ...manual, day: e.target.value })}
            className={INPUT}
          >
            {days.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5">
          Godzina
          <input
            type="time"
            step={900}
            value={manual.time}
            onChange={(e) => onManual({ ...manual, time: e.target.value })}
            className={cn(INPUT, check?.busy && "border-warning")}
          />
        </label>
        <span className="text-xs text-muted-foreground">
          {span ? `do ${hhmm(span.end)} · ${prep.minutes} min` : "Wpisz godzinę prepu."}
        </span>
      </div>

      {strip ? (
        <div>
          <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-semibold">Kalendarz: {who}</span>
            <span className="flex items-center gap-3 text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <span aria-hidden="true" className="h-2.5 w-3 rounded-sm bg-muted-foreground/40" />
                zajęte
              </span>
              <span className="inline-flex items-center gap-1">
                <span aria-hidden="true" className="h-2.5 w-3 rounded-sm bg-primary" />
                ten prep
              </span>
            </span>
          </div>
          <div
            role="img"
            aria-label={`Zajętość: ${who}, ${manual.day}`}
            className="relative h-7 overflow-hidden rounded border border-border bg-card"
          >
            {strip.busy.map((b, i) => (
              <span
                key={i}
                className="absolute inset-y-0.5 rounded-sm bg-muted-foreground/40"
                style={{ left: `${b.left}%`, width: `${b.width}%` }}
              />
            ))}
            {strip.chosen ? (
              <span
                className={cn(
                  "absolute inset-y-0.5 rounded-sm",
                  check?.busy || check?.blocks.length ? "bg-warning ring-2 ring-warning-muted-foreground" : "bg-primary",
                )}
                style={{ left: `${strip.chosen.left}%`, width: `${strip.chosen.width}%` }}
              />
            ) : null}
          </div>
          <div className="relative mt-1 h-4 text-[11px] text-muted-foreground">
            {strip.ticks.map((t, i) => (
              <span
                key={t.label}
                className="absolute"
                style={{
                  left: `${t.left}%`,
                  transform: i === 0 ? "none" : i === strip.ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)",
                }}
              >
                {t.label}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {check?.blocks.length ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {check.blocks.join(" ")}
        </p>
      ) : null}
      {check?.warnings.length ? (
        <div role="status" className="space-y-2 rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          <p>{check.warnings.join(" ")}</p>
          {nearest.length ? (
            <p className="flex flex-wrap items-center gap-2">
              Najbliżej wolne tego dnia:
              {nearest.map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => onManual({ ...manual, time: hhmm(n) })}
                  className="h-7 rounded-md border border-border bg-card px-2 text-xs font-semibold text-foreground hover:bg-muted"
                >
                  {hhmm(n)}
                </button>
              ))}
            </p>
          ) : null}
        </div>
      ) : null}
      {span && check && !check.blocks.length && !check.warnings.length && busy ? (
        <p className="rounded-md bg-success-muted px-3 py-2 text-xs text-success-muted-foreground">
          {who} ma wtedy wolne. Zaproszenie Teams pójdzie tak samo jak przy polecanej godzinie.
        </p>
      ) : null}
      {span && !busy ? (
        <p className="text-xs text-muted-foreground">
          Kalendarza osoby {who} nie widać — nie sprawdzimy, czy ma wtedy wolne.
        </p>
      ) : null}
    </div>
  );
}
