"use client";

/**
 * „Umów telefon” (decyzja Artura 03.11.2026): kandydat prosi o kontakt później,
 * rekruter wybiera termin, NEXUS przypomina 15 minut przed.
 *
 * Doc osoby pokazuje blok w miejscu, a rozwinięty panel, gdzie przycisk stoi
 * obok „Nie odebrał”, w dymku. Formularz jest jeden, także w oknie na pulpicie.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Loader2 } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { apiErrorMessage } from "@/lib/api-error";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import {
  MAX_NOTE_LENGTH,
  callPresets,
  callWhen,
  savedMessage,
  screeningCallsApi,
  warsawInstant,
  type BookedCallSummary,
} from "@/lib/screening-call";
import { cn } from "@/lib/utils";
import { getUserRoles, useAuthStore } from "@/store/auth";

const OVERRIDE_ROLES = ["admin", "delivery_lead", "head_of_recruitment"];
const CUSTOM = "custom";

function useRefreshAfterCall(jobId: number): () => void {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
    void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
  };
}

export interface ScreeningCallFormProps {
  candidateId: number;
  jobId: number;
  call?: BookedCallSummary | null;
  onDone: () => void;
  className?: string;
}

export function ScreeningCallForm({
  candidateId,
  jobId,
  call,
  onDone,
  className,
}: ScreeningCallFormProps) {
  const { showSuccess, showError } = useToast();
  const refresh = useRefreshAfterCall(jobId);
  const baseId = useId();
  const presets = useMemo(() => callPresets(), []);
  // Przekładanie zaczyna się bez wyboru: pierwszy podpowiedziany termin bywa
  // tym samym albo wcześniejszym.
  const [choice, setChoice] = useState<string | null>(call ? null : (presets[0]?.iso ?? CUSTOM));
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [note, setNote] = useState(call?.note ?? "");
  // Stały na czas otwarcia: powtórzone wysłanie nie zakłada drugiego wpisu w Outlooku.
  const [requestId] = useState(() => crypto.randomUUID());

  const start =
    choice === CUSTOM
      ? date && time
        ? warsawInstant(date, time)
        : null
      : choice
        ? new Date(choice)
        : null;
  const mutation = useMutation({
    mutationFn: (iso: string) => {
      const cleanNote = note.trim() || null;
      return call
        ? screeningCallsApi.reschedule(call.event_id, { start: iso, note: cleanNote })
        : screeningCallsApi.book({
            candidate_id: candidateId,
            job_id: jobId,
            start: iso,
            note: cleanNote,
            client_request_id: requestId,
          });
    },
    onSuccess: (saved) => {
      showSuccess(savedMessage(saved));
      refresh();
      onDone();
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się umówić telefonu.")),
  });

  return (
    <form
      data-testid="screening-call-form"
      className={cn("space-y-2 text-xs", className)}
      onSubmit={(e) => {
        e.preventDefault();
        if (start) mutation.mutate(start.toISOString());
      }}
    >
      <p className="text-sm font-semibold text-foreground">Kiedy zadzwonić?</p>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Termin telefonu">
        {presets.map((preset) => (
          <button
            key={preset.iso}
            type="button"
            aria-pressed={choice === preset.iso}
            onClick={() => setChoice(preset.iso)}
            className={cn(
              "rounded-full border px-2.5 py-1 font-medium",
              choice === preset.iso
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-foreground hover:bg-muted",
            )}
          >
            {preset.label}
          </button>
        ))}
        <button
          type="button"
          aria-pressed={choice === CUSTOM}
          onClick={() => setChoice(CUSTOM)}
          className={cn(
            "rounded-full border border-dashed px-2.5 py-1 font-medium",
            choice === CUSTOM
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:bg-muted",
          )}
        >
          Inny termin
        </button>
      </div>
      {choice === CUSTOM ? (
        <div className="flex flex-wrap gap-1.5">
          <label htmlFor={`${baseId}-date`} className="sr-only">
            Data telefonu
          </label>
          <input
            id={`${baseId}-date`}
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="h-8 w-0 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs"
          />
          <label htmlFor={`${baseId}-time`} className="sr-only">
            Godzina telefonu
          </label>
          <input
            id={`${baseId}-time`}
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            className="h-8 w-[104px] rounded-md border border-border bg-background px-2 text-xs"
          />
        </div>
      ) : null}
      <label htmlFor={`${baseId}-note`} className="sr-only">
        Co powiedział kandydat
      </label>
      <input
        id={`${baseId}-note`}
        value={note}
        maxLength={MAX_NOTE_LENGTH}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Co powiedział kandydat? (opcjonalnie)"
        className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs"
      />
      <p className="text-muted-foreground">
        Przypomnę 15 minut przed. Osoba zostaje przy Tobie do terminu, najdłużej 7 dni.
      </p>
      <div className="flex justify-end gap-1.5">
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
        <Button type="submit" size="sm" disabled={!start || mutation.isPending}>
          {mutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          {call ? "Przełóż" : "Umów"}
        </Button>
      </div>
    </form>
  );
}

function SavedCall({
  call,
  jobId,
  onEdit,
}: {
  call: BookedCallSummary;
  jobId: number;
  onEdit: () => void;
}) {
  const { showSuccess, showError } = useToast();
  const refresh = useRefreshAfterCall(jobId);
  const user = useAuthStore((s) => s.user);
  const canManage =
    user != null &&
    (call.owner_id === user.id || getUserRoles(user).some((r) => OVERRIDE_ROLES.includes(r)));
  const cancel = useMutation({
    mutationFn: () => screeningCallsApi.cancel(call.event_id),
    onSuccess: () => {
      showSuccess("Telefon odwołany.");
      refresh();
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się odwołać telefonu.")),
  });
  return (
    <div
      data-testid="screening-call-saved"
      className="flex w-full flex-wrap items-center gap-x-2 gap-y-1 text-xs"
    >
      <CalendarClock className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
      <span className="font-semibold text-foreground">Telefon {callWhen(call.start_time)}</span>
      {call.owner_id !== user?.id && call.owner_name ? (
        <span className="text-muted-foreground">· {call.owner_name}</span>
      ) : null}
      {call.in_outlook ? <span className="text-muted-foreground">· w Outlooku</span> : null}
      {call.note ? (
        <span className="w-full min-w-0 break-words text-muted-foreground">„{call.note}”</span>
      ) : null}
      {canManage ? (
        <span className="ml-auto flex gap-2 font-medium text-primary">
          <button type="button" className="hover:underline" onClick={onEdit}>
            Przełóż
          </button>
          <button
            type="button"
            className="hover:underline disabled:opacity-50"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            Odwołaj
          </button>
        </span>
      ) : null}
    </div>
  );
}

export interface ScreeningCallControlProps {
  candidateId: number;
  jobId: number;
  call?: BookedCallSummary | null;
  /** Rozwinięty panel: przycisk w wierszu z „Nie odebrał”, treść w dymku. */
  popover?: boolean;
}

export function ScreeningCallControl({
  candidateId,
  jobId,
  call,
  popover = false,
}: ScreeningCallControlProps) {
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState(false);

  if (popover) {
    return (
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setEditing(false);
        }}
      >
        <PopoverTrigger asChild>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="shrink-0"
            data-tour="screening-call.book"
          >
            <CalendarClock className="h-3.5 w-3.5" aria-hidden />
            {call ? `Telefon ${callWhen(call.start_time)}` : "Umów telefon"}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[340px] p-3">
          {call && !editing ? (
            <SavedCall call={call} jobId={jobId} onEdit={() => setEditing(true)} />
          ) : (
            <ScreeningCallForm
              candidateId={candidateId}
              jobId={jobId}
              call={call}
              onDone={() => {
                setEditing(false);
                setOpen(false);
              }}
            />
          )}
        </PopoverContent>
      </Popover>
    );
  }

  if (editing) {
    return (
      <ScreeningCallForm
        candidateId={candidateId}
        jobId={jobId}
        call={call}
        onDone={() => setEditing(false)}
        className="w-full rounded-lg border border-border bg-card p-3"
      />
    );
  }
  if (call) {
    return (
      <div className="w-full rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
        <SavedCall call={call} jobId={jobId} onEdit={() => setEditing(true)} />
      </div>
    );
  }
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      data-tour="screening-call.book"
      onClick={() => setEditing(true)}
    >
      <CalendarClock className="h-3.5 w-3.5" aria-hidden /> Umów telefon
    </Button>
  );
}
