"use client";

import { useEffect, useMemo, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useEnterOnBehalf,
  useLeavePreview,
  useOnBehalfPeople,
  useSubmitLeave,
  useSubstitutes,
  type HalfDay,
  type LeaveInput,
  type LeavePreview,
  type LeaveType,
} from "@/lib/api/hr-leave";

import {
  LEAVE_TYPE_LABELS,
  dayLabel,
  daysLabel,
  eventLabel,
  formatRange,
  validRange,
  warsawToday,
} from "./leave-format";

const ALL_TYPES = Object.keys(LEAVE_TYPE_LABELS) as LeaveType[];
const CONTRACTOR = new Set(["b2b", "zlecenie"]);
const NONE = "none";
const FULL_DAY = "full";

/** Opóźnia wartość, żeby podgląd nie pytał serwera przy każdej literze. */
/**
 * Wartość po `delayMs` bez zmian. Porównanie po treści (JSON), nie po
 * referencji: okno buduje `{start, end}` i dane wniosku na nowo w każdym
 * renderze, a porównanie referencji zapętlało rendery i nie dawało podglądowi
 * dogonić formularza („Wyślij do akceptacji” zostawał zablokowany).
 */
export function useDebounced<T>(value: T, delayMs: number): T {
  const key = JSON.stringify(value);
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(
      () => setDebounced(key === undefined ? (undefined as T) : (JSON.parse(key) as T)),
      delayMs,
    );
    return () => clearTimeout(timer);
  }, [key, delayMs]);
  return debounced;
}

export interface LeaveRequestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `self` — własny wniosek; `on_behalf` — wpis za pracownika (przełożony, Kadry). */
  mode: "self" | "on_behalf";
  /** Rodzaje dozwolone dla osoby (z salda); B2B i zlecenie widzą tylko urlop. */
  allowedTypes?: LeaveType[];
}

/** Okno wniosku o nieobecność z podziałem płatne/bezpłatne i ostrzeżeniami na żywo. */
export function LeaveRequestDialog({
  open,
  onOpenChange,
  mode,
  allowedTypes,
}: LeaveRequestDialogProps) {
  const onBehalf = mode === "on_behalf";
  const { showToast } = useToast();
  const people = useOnBehalfPeople(open && onBehalf);
  const submitOwn = useSubmitLeave();
  const submitFor = useEnterOnBehalf();

  const today = warsawToday();
  const [personId, setPersonId] = useState("");
  const [leaveType, setLeaveType] = useState<LeaveType>("vacation");
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const [halfDay, setHalfDay] = useState<string>(FULL_DAY);
  const [substitute, setSubstitute] = useState(NONE);
  const [note, setNote] = useState("");
  const [oofInternal, setOofInternal] = useState("");
  const [oofExternal, setOofExternal] = useState("");
  const [showOof, setShowOof] = useState(false);
  const [forward, setForward] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const person = people.data?.find((row) => String(row.user_id) === personId) ?? null;
  const subjectId = onBehalf ? (person?.user_id ?? null) : null;
  const types = useMemo(() => {
    if (onBehalf) {
      return person && CONTRACTOR.has(person.employment_type) ? ["vacation" as const] : ALL_TYPES;
    }
    return allowedTypes && allowedTypes.length > 0 ? allowedTypes : ALL_TYPES;
  }, [onBehalf, person, allowedTypes]);

  useEffect(() => {
    if (!types.includes(leaveType)) setLeaveType(types[0]);
  }, [types, leaveType]);

  const singleDay = start === end;
  const half: HalfDay | null = singleDay && halfDay !== FULL_DAY ? (halfDay as HalfDay) : null;
  const rangeOk = validRange(start, end);
  const range = useDebounced(rangeOk ? { start, end } : null, 300);
  // Okno jest zamontowane na stałe w „Urlopach” — zamknięte nie pyta serwera.
  const substitutes = useSubstitutes(
    !open || (onBehalf && !subjectId) ? null : range,
    subjectId,
  );
  const substituteId = substitute === NONE ? null : Number(substitute);

  const input: LeaveInput | null =
    rangeOk && (!onBehalf || subjectId)
      ? {
          leave_type: leaveType,
          start_date: start,
          end_date: end,
          half_day: half,
          substitute_user_id: substituteId,
        }
      : null;
  const debouncedInput = useDebounced(input, 350);
  const preview = useLeavePreview(open ? debouncedInput : null, subjectId);
  const shown = preview.data;
  const stale = JSON.stringify(input) !== JSON.stringify(debouncedInput);

  const reset = () => {
    setPersonId("");
    setLeaveType("vacation");
    setStart(today);
    setEnd(today);
    setHalfDay(FULL_DAY);
    setSubstitute(NONE);
    setNote("");
    setOofInternal("");
    setOofExternal("");
    setShowOof(false);
    setForward(false);
    setError(null);
  };

  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const pending = submitOwn.isPending || submitFor.isPending;
  const blocked =
    !input || stale || preview.isFetching || !shown || shown.blocking_reason !== null;

  const submit = () => {
    if (!input) return;
    setError(null);
    const onError = (err: unknown) =>
      setError(apiErrorMessage(err, "Nie udało się zapisać wniosku."));
    const base = { ...input, note: note.trim() || null };
    if (onBehalf && subjectId) {
      submitFor.mutate(
        { ...base, user_id: subjectId },
        {
          onSuccess: () => {
            showToast("Nieobecność wpisana", "success");
            close(false);
          },
          onError,
        },
      );
      return;
    }
    submitOwn.mutate(
      {
        ...base,
        forward_mail_consent: Boolean(substituteId) && forward,
        oof_internal_message: oofInternal.trim() || null,
        oof_external_message: oofExternal.trim() || null,
      },
      {
        onSuccess: (row) => {
          showToast(
            row.status === "approved" ? "Nieobecność zgłoszona" : "Wniosek wysłany do akceptacji",
            "success",
          );
          close(false);
        },
        onError,
      },
    );
  };

  const submitLabel = onBehalf
    ? "Wpisz nieobecność"
    : shown?.auto_approved
      ? "Zgłoś nieobecność"
      : "Wyślij do akceptacji";

  return (
    <AppModal
      open={open}
      onOpenChange={close}
      size="xl"
      title={onBehalf ? "Wpisz nieobecność za pracownika" : "Wniosek o nieobecność"}
      description={
        onBehalf
          ? "Wpis jest od razu zatwierdzony. Zgodę na przekierowanie poczty daje tylko sama osoba."
          : shown && !shown.auto_approved
            ? `Akceptuje: ${shown.approver}`
            : undefined
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={blocked || pending}>
            {pending ? "Zapisywanie…" : submitLabel}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_300px]">
        <div className="grid content-start gap-4">
          {onBehalf ? (
            <FormField label="Osoba" htmlFor="leave-person">
              <Select
                value={personId}
                onValueChange={(value) => {
                  setPersonId(value);
                  setSubstitute(NONE);
                }}
              >
                <SelectTrigger id="leave-person">
                  <SelectValue placeholder="Wybierz osobę" />
                </SelectTrigger>
                <SelectContent>
                  {(people.data ?? []).map((row) => (
                    <SelectItem key={row.user_id} value={String(row.user_id)}>
                      {row.name}
                      {row.department ? ` · ${row.department}` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          ) : null}
          <FormField label="Rodzaj" htmlFor="leave-type">
            <Select value={leaveType} onValueChange={(value) => setLeaveType(value as LeaveType)}>
              <SelectTrigger id="leave-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {types.map((type) => (
                  <SelectItem key={type} value={type}>
                    {LEAVE_TYPE_LABELS[type]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <div className="grid gap-3 sm:grid-cols-3">
            <FormField label="Od" htmlFor="leave-start">
              <Input
                id="leave-start"
                type="date"
                value={start}
                onChange={(event) => {
                  setStart(event.target.value);
                  if (event.target.value > end) setEnd(event.target.value);
                }}
              />
            </FormField>
            <FormField label="Do" htmlFor="leave-end">
              <Input
                id="leave-end"
                type="date"
                value={end}
                min={start}
                onChange={(event) => setEnd(event.target.value)}
              />
            </FormField>
            <FormField label="Wymiar" htmlFor="leave-half">
              <Select value={singleDay ? halfDay : FULL_DAY} onValueChange={setHalfDay} disabled={!singleDay}>
                <SelectTrigger id="leave-half">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={FULL_DAY}>Cały dzień</SelectItem>
                  <SelectItem value="morning">Pół dnia (rano)</SelectItem>
                  <SelectItem value="afternoon">Pół dnia (po południu)</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
          </div>
          <FormField
            label="Zastępca"
            htmlFor="leave-substitute"
            description="Najpierw osoby z Twojego działu, które są w pracy przez cały okres."
          >
            <Select value={substitute} onValueChange={setSubstitute}>
              <SelectTrigger id="leave-substitute">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Bez zastępcy</SelectItem>
                {(substitutes.data ?? []).map((row) => (
                  <SelectItem key={row.user_id} value={String(row.user_id)}>
                    {row.name}
                    {row.suggested ? " · proponowany" : row.department ? ` · ${row.department}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Notatka" htmlFor="leave-note">
            <Textarea
              id="leave-note"
              rows={2}
              maxLength={2000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </FormField>
          {!onBehalf ? (
            <>
              {showOof ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <FormField label="Autoodpowiedź dla firmy" htmlFor="leave-oof-in">
                    <Textarea
                      id="leave-oof-in"
                      rows={3}
                      maxLength={4000}
                      value={oofInternal}
                      onChange={(event) => setOofInternal(event.target.value)}
                    />
                  </FormField>
                  <FormField label="Autoodpowiedź na zewnątrz" htmlFor="leave-oof-out">
                    <Textarea
                      id="leave-oof-out"
                      rows={3}
                      maxLength={4000}
                      value={oofExternal}
                      onChange={(event) => setOofExternal(event.target.value)}
                    />
                  </FormField>
                </div>
              ) : (
                <button
                  type="button"
                  className="justify-self-start text-sm text-primary hover:underline"
                  onClick={() => setShowOof(true)}
                >
                  Własny tekst autoodpowiedzi w Outlooku
                </button>
              )}
              {substituteId ? (
                <label className="flex items-start gap-2 text-sm text-foreground">
                  <Checkbox
                    checked={forward}
                    onCheckedChange={(value) => setForward(value === true)}
                    className="mt-0.5"
                  />
                  <span>
                    Przekierowuj kopię poczty do zastępcy na czas nieobecności. Reguła
                    zniknie sama po ostatnim dniu.
                  </span>
                </label>
              ) : null}
            </>
          ) : null}
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
        <PreviewPanel
          preview={shown}
          loading={Boolean(input) && (preview.isLoading || stale)}
          failed={preview.isError}
          waitingForPerson={onBehalf && !subjectId}
          onBehalf={onBehalf}
          range={rangeOk ? formatRange(start, end) : null}
        />
      </div>
    </AppModal>
  );
}

interface PreviewPanelProps {
  preview: LeavePreview | undefined;
  loading: boolean;
  failed: boolean;
  waitingForPerson: boolean;
  onBehalf: boolean;
  range: string | null;
}

/** „Co wypada w tym czasie” — dni, pula, praca w NEXUSIE, nieobecni z działu. */
export function PreviewPanel({
  preview,
  loading,
  failed,
  waitingForPerson,
  onBehalf,
  range,
}: PreviewPanelProps) {
  const box = "grid content-start gap-3 rounded-lg border border-border bg-muted/40 p-4 text-sm";
  if (waitingForPerson) {
    return <div className={box}>Wybierz osobę, żeby policzyć dni i pulę.</div>;
  }
  if (!range) {
    return <div className={box}>Podaj daty, żeby policzyć dni robocze.</div>;
  }
  if (failed && !preview) {
    return <div className={box}>Nie udało się policzyć dni — spróbuj zmienić daty.</div>;
  }
  if (!preview) {
    return <div className={box}>Liczę dni robocze…</div>;
  }
  return (
    <div className={box} aria-busy={loading}>
      <div className="flex items-baseline justify-between gap-2">
        <b className="text-foreground">Co wypada w tym czasie</b>
        <span className="text-[11px] text-muted-foreground">{range}</span>
      </div>
      {preview.blocking_reason ? (
        <p role="alert" className="rounded-md bg-destructive-muted p-2 text-destructive-muted-foreground">
          {preview.blocking_reason}
        </p>
      ) : null}
      <p className="text-foreground">
        <b className="tabular-nums">{daysLabel(preview.days_total)} roboczych</b>
        {preview.return_on ? (
          <span className="text-muted-foreground"> · powrót {dayLabel(preview.return_on)}</span>
        ) : null}
      </p>
      {preview.years.map((split) => (
        <p key={split.year} className="text-muted-foreground">
          {split.has_pool && split.remaining_before !== null ? (
            <>
              Pula {split.year}: zostało{" "}
              <span className="tabular-nums text-foreground">
                {daysLabel(split.remaining_before)}
              </span>
              {Number(split.paid) > 0 ? (
                <>
                  {" "}→ po wniosku{" "}
                  <span className="tabular-nums text-foreground">
                    {daysLabel(split.remaining_after ?? "0")}
                  </span>
                </>
              ) : null}
            </>
          ) : (
            <>Rok {split.year}: bez puli</>
          )}
          {Number(split.unpaid) > 0 ? (
            <span className="block text-warning-muted-foreground">
              Bezpłatnie: {daysLabel(split.unpaid)}
            </span>
          ) : null}
        </p>
      ))}
      {preview.work.total > 0 ? (
        <div>
          <b className="text-foreground">{onBehalf ? "W tym czasie ta osoba ma" : "W tym czasie masz"}</b>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">
            {preview.work.by_kind.map((kind) => (
              <li key={kind.kind}>
                {kind.label}: <span className="tabular-nums text-foreground">{kind.count}</span>
              </li>
            ))}
          </ul>
          <ul className="mt-1 space-y-0.5 text-[12px] text-muted-foreground">
            {preview.work.items.slice(0, 4).map((item) => (
              <li key={`${item.starts_at}-${item.kind}`} className="truncate">
                {eventLabel(item.starts_at)} · {item.title ?? item.label}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[12px] text-muted-foreground">Przejmie je zastępca.</p>
        </div>
      ) : null}
      {preview.department_absent.length > 0 ? (
        <div>
          <b className="text-foreground">Z działu też nieobecni</b>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">
            {preview.department_absent.map((row) => (
              <li key={row.user_id}>
                {row.name} · {formatRange(row.start_date, row.end_date)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {preview.substitute_absent ? (
        <p className="text-warning-muted-foreground">
          Wybrany zastępca też jest nieobecny w części tego okresu.
        </p>
      ) : null}
      {preview.auto_approved ? (
        <p className="text-muted-foreground">
          {onBehalf
            ? "Wpis jest od razu zatwierdzony; osoba dostanie powiadomienie."
            : "Zwolnienie zatwierdza się od razu — przełożony i Kadry dostaną powiadomienie."}
        </p>
      ) : null}
    </div>
  );
}
