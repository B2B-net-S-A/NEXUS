"use client";

import { useEffect, useMemo, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { FileDropZone } from "@/components/ds/FileDropZone";
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
import { assigneeLabel, useCproAssigneeOptions } from "@/lib/api/boardTasks";
import type { EmploymentType } from "@/lib/api/hr";
import {
  enterablePeople,
  useAttachLeaveProof,
  useEnterOnBehalf,
  useLeavePreview,
  useOnBehalfPeople,
  useSubmitLeave,
  useSubstitutes,
  type LeaveInput,
  type LeaveType,
} from "@/lib/api/hr-leave";
import { employmentTerms, reportsAbsence } from "@/lib/hr-employment-terms";
import { useDebounced } from "@/lib/use-debounced";
import { warsawToday } from "@/lib/warsaw-date";
import { useAuthStore } from "@/store/auth";

import {
  FULL_DAY,
  LEAVE_TYPE_LABELS,
  NO_SUBSTITUTE,
  cproSubstituteMissing,
  formatRange,
  leaveInputFrom,
  leaveToast,
  submitLabel,
  submittedToast,
  validRange,
} from "./leave-format";
import { PreviewPanel } from "./LeavePreviewPanel";
import { PROOF_ACCEPT, PROOF_MAX_BYTES, proofHint } from "./leave-proofs";

const ALL_TYPES = Object.keys(LEAVE_TYPE_LABELS) as LeaveType[];
const CONTRACTOR = new Set(["b2b", "zlecenie"]);

export interface LeaveRequestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `self` — własny wniosek; `on_behalf` — wpis za pracownika (przełożony, Kadry). */
  mode: "self" | "on_behalf";
  /** Rodzaje dozwolone dla osoby (z salda); B2B i zlecenie widzą tylko urlop. */
  allowedTypes?: LeaveType[];
  /** Forma osoby (z salda) — słowa okna, zanim przyjdzie podgląd (D4, D5). */
  employmentType?: EmploymentType;
  /** `on_behalf` z kartoteki („Dodaj za tę osobę”): osoba ustalona, bez wyboru. */
  personUserId?: number;
}

/**
 * Okno nieobecności z podziałem płatne/bezpłatne i ostrzeżeniami na żywo.
 * Umowa o pracę: wniosek do akceptacji przełożonego. B2B i zlecenie (D5):
 * zgłoszenie — termin wchodzi od razu, koordynator dostaje informację.
 * Własny wniosek może mieć załącznik (akt, zaświadczenie) — idzie zaraz po
 * zapisie wniosku; gdy nie przejdzie, wniosek zostaje i plik dołącza się
 * z tabeli wniosków.
 */
export function LeaveRequestDialog({
  open,
  onOpenChange,
  mode,
  allowedTypes,
  employmentType,
  personUserId,
}: LeaveRequestDialogProps) {
  const onBehalf = mode === "on_behalf";
  const { showToast } = useToast();
  const people = useOnBehalfPeople(open && onBehalf);
  const enterable = enterablePeople(people.data);
  const submitOwn = useSubmitLeave();
  const submitFor = useEnterOnBehalf();
  const attachProof = useAttachLeaveProof();

  const today = warsawToday();
  const fixedPerson = personUserId === undefined ? "" : String(personUserId);
  const [personId, setPersonId] = useState(fixedPerson);
  const [leaveType, setLeaveType] = useState<LeaveType>("vacation");
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const [halfDay, setHalfDay] = useState<string>(FULL_DAY);
  const [substitute, setSubstitute] = useState(NO_SUBSTITUTE);
  const [cproSubstitute, setCproSubstitute] = useState(NO_SUBSTITUTE);
  const [note, setNote] = useState("");
  const [oofInternal, setOofInternal] = useState("");
  const [oofExternal, setOofExternal] = useState("");
  const [showOof, setShowOof] = useState(false);
  const [forward, setForward] = useState(false);
  const [proofFile, setProofFile] = useState<File | null>(null);
  const [proofError, setProofError] = useState<string | null>(null);
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
  const rangeOk = validRange(start, end);
  const range = useDebounced(rangeOk ? { start, end } : null, 300);
  // Okno jest zamontowane na stałe w „Urlopach” — zamknięte nie pyta serwera.
  const substitutes = useSubstitutes(
    !open || (onBehalf && !subjectId) ? null : range,
    subjectId,
  );
  const substituteId = substitute === NO_SUBSTITUTE ? null : Number(substitute);

  const values = {
    leaveType,
    start,
    end,
    halfDay,
    substitute,
    cproSubstitute,
    note,
    forward,
    oofInternal,
    oofExternal,
  };
  const input: LeaveInput | null =
    !onBehalf || subjectId ? leaveInputFrom(values, "preview") : null;
  const debouncedInput = useDebounced(input, 350);
  const preview = useLeavePreview(open ? debouncedInput : null, subjectId);
  const shown = preview.data;
  const stale = JSON.stringify(input) !== JSON.stringify(debouncedInput);
  // Forma osoby: za kogoś — z listy osób; własna — z salda albo z podglądu.
  const form: EmploymentType | undefined = onBehalf
    ? person?.employment_type
    : (employmentType ?? shown?.employment_type);
  const words = employmentTerms(form);
  const report = reportsAbsence(form);
  // Osoba od Cpro (podgląd z serwera) wskazuje, kto wrzuca do Cpro w tym czasie.
  const cproSender = shown?.cpro_sender === true;
  const me = useAuthStore((state) => state.user);
  const cproOptions = useCproAssigneeOptions(open && cproSender);
  const subjectUserId = onBehalf ? subjectId : (me?.id ?? null);
  const cproMissing = cproSubstituteMissing(values, shown?.cpro_sender, onBehalf);

  const reset = () => {
    setPersonId(fixedPerson);
    setLeaveType("vacation");
    setStart(today);
    setEnd(today);
    setHalfDay(FULL_DAY);
    setSubstitute(NO_SUBSTITUTE);
    setCproSubstitute(NO_SUBSTITUTE);
    setNote("");
    setOofInternal("");
    setOofExternal("");
    setShowOof(false);
    setForward(false);
    setProofFile(null);
    setProofError(null);
    setError(null);
  };

  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const pending = submitOwn.isPending || submitFor.isPending || attachProof.isPending;
  const blocked =
    !input ||
    stale ||
    preview.isFetching ||
    !shown ||
    shown.blocking_reason !== null ||
    cproMissing;

  const submit = () => {
    const payload = leaveInputFrom(values, mode);
    if (!input || !payload) return;
    setError(null);
    const onError = (err: unknown) =>
      setError(apiErrorMessage(err, "Nie udało się zapisać wniosku."));
    if (onBehalf && subjectId) {
      submitFor.mutate(
        { ...payload, user_id: subjectId },
        {
          onSuccess: (saved) => {
            showToast(...leaveToast("Nieobecność wpisana", saved));
            close(false);
          },
          onError,
        },
      );
      return;
    }
    submitOwn.mutate(payload, {
      onSuccess: (row) => {
        if (!proofFile) {
          showToast(...leaveToast(submittedToast(row), row));
          close(false);
          return;
        }
        attachProof.mutate(
          { id: row.id, file: proofFile },
          {
            onSuccess: (saved) => {
              showToast(...leaveToast(`${submittedToast(saved)} z załącznikiem`, saved));
              close(false);
            },
            onError: (err) => {
              showToast(
                `${submittedToast(row)}, ale bez załącznika: ${apiErrorMessage(
                  err,
                  "plik nie przeszedł",
                )} Dołącz go w tabeli wniosków.`,
                "error",
              );
              close(false);
            },
          },
        );
      },
      onError,
    });
  };

  const saveLabel = submitLabel({ onBehalf, form, autoApproved: shown?.auto_approved });

  return (
    <AppModal
      open={open}
      onOpenChange={close}
      size="xl"
      title={onBehalf ? "Wpisz nieobecność za konsultanta/kontraktora" : words.dialog_title}
      description={
        onBehalf
          ? "Wpis jest od razu zatwierdzony. Zgodę na przekierowanie poczty daje tylko sama osoba."
          : report
            ? `Zgłoszenie, nie wniosek — ${words.coordinator}${shown ? ` (${shown.approver})` : ""} dostaje informację.`
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
            {pending ? "Zapisywanie…" : saveLabel}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_300px]">
        <div className="grid content-start gap-4">
          {onBehalf ? (
            <FormField
              label="Osoba"
              htmlFor="leave-person"
              error={
                people.isError
                  ? apiErrorMessage(people.error, "Nie udało się wczytać listy osób.")
                  : undefined
              }
              description={
                people.isSuccess && enterable.length === 0
                  ? "Nie masz osób, którym wpisujesz nieobecność. Osoby na B2B i zleceniu zgłaszają nieobecność same — za nie wpisują Kadry."
                  : undefined
              }
            >
              <Select
                value={personId}
                disabled={fixedPerson !== ""}
                onValueChange={(value) => {
                  setPersonId(value);
                  setSubstitute(NO_SUBSTITUTE);
                  setCproSubstitute(NO_SUBSTITUTE);
                }}
              >
                <SelectTrigger id="leave-person">
                  <SelectValue placeholder="Wybierz osobę" />
                </SelectTrigger>
                <SelectContent>
                  {enterable.map((row) => (
                    <SelectItem key={row.user_id} value={String(row.user_id)}>
                      {row.name}
                      {row.department ? ` · ${row.department}` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          ) : null}
          {/* B2B i zlecenie mają jeden rodzaj — bez wyboru i bez słowa „urlop” (D4). */}
          {report ? null : (
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
          )}
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
            label={report ? "Kto przejmie bieżące sprawy" : "Zastępca"}
            htmlFor="leave-substitute"
            description="Najpierw osoby z Twojego działu, które są dostępne przez cały okres."
          >
            <Select value={substitute} onValueChange={setSubstitute}>
              <SelectTrigger id="leave-substitute">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_SUBSTITUTE}>Bez zastępcy</SelectItem>
                {(substitutes.data ?? []).map((row) => (
                  <SelectItem key={row.user_id} value={String(row.user_id)}>
                    {row.name}
                    {row.suggested ? " · proponowany" : row.department ? ` · ${row.department}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {cproSender ? (
            <FormField
              label="Kto wrzuca do Cpro"
              htmlFor="leave-cpro-substitute"
              description={
                cproOptions.isError
                  ? undefined
                  : "Wrzucasz kandydatów Nordei do Cpro. W dni nieobecności kolejka i powiadomienia trafią do tej osoby, potem wrócą do Ciebie."
              }
              error={
                cproOptions.isError
                  ? apiErrorMessage(cproOptions.error, "Nie udało się wczytać zespołu rekrutacji.")
                  : undefined
              }
            >
              <Select value={cproSubstitute} onValueChange={setCproSubstitute}>
                <SelectTrigger id="leave-cpro-substitute">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_SUBSTITUTE}>
                    {cproOptions.isLoading ? "Wczytywanie…" : "Wybierz osobę"}
                  </SelectItem>
                  {(cproOptions.data ?? [])
                    .filter((option) => option.id !== subjectUserId)
                    .map((option) => (
                      <SelectItem key={option.id} value={String(option.id)}>
                        {assigneeLabel(option)}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </FormField>
          ) : null}
          <FormField label="Notatka" htmlFor="leave-note">
            <Textarea
              id="leave-note"
              rows={2}
              maxLength={2000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </FormField>
          {!onBehalf && !report ? (
            <FormField
              label="Załącznik (opcjonalnie)"
              htmlFor="leave-proof"
              description="Trafi do Twoich dokumentów. Plik widzisz Ty i Kadry — przełożony widzi tylko, że jest."
            >
              <FileDropZone
                inputId="leave-proof"
                file={proofFile}
                onPick={(file) => {
                  setProofFile(file);
                  setProofError(null);
                }}
                accept={PROOF_ACCEPT}
                maxBytes={PROOF_MAX_BYTES}
                label={proofFile ? "Zmień plik" : "Dołącz dokument"}
                hint={proofHint(leaveType) ?? "PDF, JPG albo PNG do 5 MB"}
                error={proofError}
                onError={setProofError}
              />
            </FormField>
          ) : null}
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
                    Przekierowuj kopię poczty do zastępcy na czas{" "}
                    {form === "b2b" ? "przerwy" : "nieobecności"}. Reguła zniknie sama po
                    ostatnim dniu.
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
          form={form}
        />
      </div>
    </AppModal>
  );
}
