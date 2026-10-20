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
  hhmm,
  interviewStart,
  isWindow,
  prepWhen,
  windowBounds,
} from "@/lib/interview-pick";
import { useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";

const INPUT =
  "h-9 rounded-md border border-border bg-card px-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

type PrepPick = { kind: "option"; start: string; end: string } | { kind: "none" };

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
  const [error, setError] = useState<string | null>(null);
  const requestIds = useRef<Record<number, string>>({});

  useEffect(() => {
    if (!open) return;
    const only = request?.slots.length === 1 ? 0 : null;
    setIndex(only);
    setWindowTime(only != null && request ? (windowBounds(request.slots[0], request.duration_minutes)?.from ?? "") : "");
    setCandFrom("");
    setCandTo("");
    setPicks({});
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
        if (kept?.kind === "none") next[p.prep_no] = kept;
        else if (kept?.kind === "option" && p.options.some((o) => o.start === kept.start)) next[p.prep_no] = kept;
        else next[p.prep_no] = p.options[0] ? { kind: "option", ...p.options[0] } : undefined;
      }
      return next;
    });
  }, [suggestions.data]);

  const prepsEnabled = suggestions.data?.enabled ?? false;
  const toInvite = useMemo(
    () =>
      (suggestions.data?.preps ?? []).filter(
        (p) => !p.scheduled_start && p.organizer && picks[p.prep_no]?.kind === "option",
      ),
    [suggestions.data, picks],
  );

  const submit = useMutation({
    mutationFn: async (withPreps: boolean) => {
      if (!request || index == null || !start) throw new Error("no-slot");
      await interviewCycleApi.chooseSlot(request.id, index, slot && isWindow(slot) ? start : null);
      const failed: string[] = [];
      if (withPreps && pair) {
        for (const p of toInvite) {
          const pick = picks[p.prep_no];
          if (pick?.kind !== "option" || !p.organizer) continue;
          try {
            await prepMeetingsApi.create({
              candidate_id: pair.candidate_id,
              job_id: pair.job_id,
              prep_no: p.prep_no,
              organizer_user_id: p.organizer.id,
              start: pick.start,
              end: pick.end,
              // Planujący za kogoś jest na liście zaproszonych (D3, 17.10.2026).
              attendee_user_ids:
                currentUserId != null && currentUserId !== p.organizer.id ? [currentUserId] : [],
              client_request_id: requestIds.current[p.prep_no],
            });
          } catch (err) {
            failed.push(`Prep ${p.prep_no}: ${apiErrorMessage(err, "nie powstał")}`);
          }
        }
      }
      return { failed, invited: withPreps ? toInvite.length - failed.length : 0 };
    },
    onSuccess: ({ failed, invited }) => {
      onInvalidate();
      qc.invalidateQueries({ queryKey: ["interview-cycle", "preps"] });
      if (failed.length) {
        toast.showError(`Termin wybrany. ${failed.join(" ")} Zaplanuj go z panelu osoby.`);
      } else {
        toast.showSuccess(
          invited > 0
            ? `Termin wysłany do DL, zaproszenia na prepy wysłane (${invited}).`
            : "Termin wysłany do DL — potwierdzi go u klienta.",
        );
      }
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać wyboru.")),
  });

  const canSubmit = index != null && start != null && !submit.isPending;
  const primaryLabel =
    prepsEnabled && toInvite.length > 0
      ? `Wybierz termin i zaproś na prepy (${toInvite.length})`
      : "Wyślij do DL";

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
          {prepsEnabled && toInvite.length > 0 ? (
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
            disabled={!canSubmit}
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
              return (
                <div
                  key={`${s.start}-${i}`}
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm",
                    selected ? "border-primary bg-primary/5" : "border-border",
                  )}
                >
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="radio"
                      name="pick-slot"
                      checked={selected}
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
                  pick={picks[p.prep_no]}
                  onPick={(next) => setPicks((prev) => ({ ...prev, [p.prep_no]: next }))}
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
  pick,
  onPick,
}: {
  prep: PrepSuggestion;
  pick: PrepPick | undefined;
  onPick: (pick: PrepPick) => void;
}) {
  const who = prep.organizer?.name ?? "brak prowadzącego";
  const lead = prep.prep_no === 1 ? "prowadzi Delivery Lead" : "prowadzi rekruter";
  return (
    <div className="rounded-lg border border-border p-3">
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
      ) : prep.options.length === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Brak wolnej godziny przed rozmową w godzinach kandydata — zaplanuj prep ręcznie z panelu osoby.
        </p>
      ) : (
        <div role="radiogroup" aria-label={`Godzina Prepu ${prep.prep_no}`} className="mt-2 flex flex-wrap gap-2">
          {prep.options.map((o, i) => {
            const on = pick?.kind === "option" && pick.start === o.start;
            return (
              <button
                key={o.start}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => onPick({ kind: "option", start: o.start, end: o.end })}
                className={cn(
                  "h-9 rounded-md border px-3 text-sm",
                  on ? "border-primary bg-primary/10 font-semibold text-primary" : "border-border hover:bg-muted",
                )}
              >
                {prepWhen(o.start)}
                {i === 0 ? " · polecany" : ""}
              </button>
            );
          })}
          <button
            type="button"
            role="radio"
            aria-checked={pick?.kind === "none"}
            onClick={() => onPick({ kind: "none" })}
            className={cn(
              "h-9 rounded-md border px-3 text-sm",
              pick?.kind === "none" ? "border-primary bg-primary/10 font-semibold text-primary" : "border-border text-muted-foreground hover:bg-muted",
            )}
          >
            Zaplanuję później
          </button>
        </div>
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
