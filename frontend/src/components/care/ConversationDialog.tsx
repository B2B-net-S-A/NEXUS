"use client";

import { useId, useMemo, useState, type ReactNode } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CHANNEL_LABELS,
  HIRING_SOURCE_LABELS,
  useAddConversation,
  useClientState,
  useConsultantCard,
  type CareChannel,
  type CarePlanItem,
  type ConversationResult,
  type HiringSource,
} from "@/lib/api/care";
import { useHrConfig } from "@/lib/api/hr";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import { cadenceLabel } from "./cadence-format";
import { CareGapQuestions } from "./CareGapQuestions";
import { CasesToOpenSection } from "./conversation/CasesToOpenSection";
import { ClientStateSection } from "./conversation/ClientStateSection";
import {
  buildConversationPayload,
  caseTitleProblem,
  emptyClientState,
  emptyTalk,
  saveSummary,
  suggestFollowUp,
  validateConversation,
  type CaseDraft,
  type GapAnswerForm,
  type TalkForm,
} from "./conversation/conversation-form";

interface ConversationDialogProps {
  contractId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Punkt planu, który ta rozmowa zamyka (z „Zapisz” przy punkcie albo z
   * tablicy). Bez etykiety okno bierze ją z planu w karcie konsultanta.
   */
  planItem?: { id: CarePlanItem["id"]; label?: string | null } | null;
  /** Klient kontraktu — bez niego okno bierze go z karty konsultanta. */
  clientId?: number | null;
}

const CHANNELS = Object.keys(CHANNEL_LABELS) as CareChannel[];
const SOURCES = Object.keys(HIRING_SOURCE_LABELS) as HiringSource[];

function ScoreButtons({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (value: number | null) => void;
}) {
  const option = (score: number | null, label: string, wide = false) => (
    <button
      key={label}
      type="button"
      role="radio"
      aria-checked={value === score}
      aria-label={score == null ? "Bez oceny" : `${score} z 5`}
      onClick={() => onChange(score)}
      className={cn(
        "inline-flex h-8 items-center justify-center rounded-md border text-sm tabular-nums transition-colors",
        wide ? "px-2.5 text-xs" : "w-9",
        value === score
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-card text-foreground hover:bg-muted",
      )}
    >
      {label}
    </button>
  );
  return (
    <div role="radiogroup" aria-label="Jak mu się pracuje" className="flex flex-wrap gap-1">
      {[1, 2, 3, 4, 5].map((score) => option(score, String(score)))}
      {option(null, "bez oceny", true)}
    </div>
  );
}

function Signal({
  id,
  label,
  hint,
  checked,
  onChange,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  children?: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="flex items-center justify-between gap-2 text-sm text-foreground">
        <span>
          {label}
          {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
        </span>
        <Switch id={id} checked={checked} onCheckedChange={onChange} />
      </label>
      {checked && children ? <div className="pl-0.5">{children}</div> : null}
    </div>
  );
}

/** Toast po zapisie — co poza rozmową naprawdę się stało. */
export function savedToast(result: Partial<ConversationResult> | undefined): string {
  const parts = ["Rozmowa zapisana"];
  if (result?.tech_card_id) parts.push("stan u klienta zaktualizowany");
  const cases = result?.case_ids?.length ?? 0;
  if (cases) parts.push(cases === 1 ? "założona 1 sprawa" : `założone sprawy: ${cases}`);
  if (result?.demand_notified) parts.push("Delivery Lead dostał sygnał popytu");
  const text = parts.join(" · ");
  return result?.manager_kept
    ? `${text}. Menedżera nie zmieniono — kontrakt ma innego, a zmienia go Delivery Lead albo administrator.`
    : text;
}

/**
 * Okno „Rozmowa” (decyzja 4 z 22.10.2026): po lewej dzisiejsza rozmowa —
 * data, forma, „Jak mu się pracuje” 1–5, notatka, sygnały jako przełączniki,
 * następny kontakt podpowiedziany z rytmu; po prawej „Co u klienta” (ostatni
 * stan: „bez zmian” / „zmień”), pytania z mapy klienta i „Coś do
 * załatwienia?”. Stopka mówi, co się zapisze. Bez danych o zdrowiu i bez
 * stawek — te mają swoje miejsca.
 */
export function ConversationDialog({
  contractId,
  open,
  onOpenChange,
  planItem,
  clientId,
}: ConversationDialogProps) {
  const { showToast } = useToast();
  const ids = {
    date: useId(),
    note: useId(),
    risk: useId(),
    change: useId(),
    end: useId(),
    endOn: useId(),
    hiring: useId(),
    hiringNote: useId(),
    follow: useId(),
  };
  const today = warsawToday();
  const save = useAddConversation(contractId);
  const card = useConsultantCard(contractId, open);
  const clientState = useClientState(contractId, open);
  const hr = useHrConfig(open);
  const [talk, setTalk] = useState<TalkForm>(() => emptyTalk(today));
  const [stateForm, setStateForm] = useState(emptyClientState);
  const [answers, setAnswers] = useState<Record<string, GapAnswerForm>>({});
  const [cases, setCases] = useState<CaseDraft[]>([]);
  const [error, setError] = useState<string | null>(null);

  const resolvedClientId = clientId ?? card.data?.client_id ?? null;
  const questions = useMemo(() => clientState.data?.questions ?? [], [clientState.data]);
  const knownTechnologies = clientState.data?.state?.technologies.length ?? 0;
  const casesOpen = Boolean(hr.data?.open_modules.cases);
  const input = {
    talk,
    clientState: stateForm,
    questions,
    answers,
    cases: casesOpen ? cases : [],
    planItemId: planItem?.id ?? null,
    knownTechnologies,
  };
  const payload = buildConversationPayload(input);
  const cadence = card.data?.cadence ?? null;
  const suggestion = suggestFollowUp(cadence?.level, talk.occurredOn);
  const set = (patch: Partial<TalkForm>) => setTalk((current) => ({ ...current, ...patch }));
  // Okno rozmowy otwiera tylko zapisujący opiekę — tej samej bramki pilnuje `/api/care/case-assignees`.
  const canPickAssignee = true;
  // Obsługa Spraw (uprawnienie „Sprawy” albo admin) — pełna lista osób i obszar „Negocjacje”.
  const caseHandler = Boolean(hr.data?.me.is_admin || hr.data?.me.cases);
  const caseTitleBlocked = casesOpen && cases.some((draft) => caseTitleProblem(draft) !== null);
  const name = card.data?.candidate_name;
  const planLabel = planItem
    ? (planItem.label ?? card.data?.plan.find((item) => item.id === planItem.id)?.label ?? "punkt planu")
    : null;

  const submit = () => {
    setError(null);
    const problem = validateConversation(input, today);
    if (problem) {
      setError(problem);
      return;
    }
    save.mutate(payload, {
      onSuccess: (result) => {
        showToast(savedToast(result), "success");
        onOpenChange(false);
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać rozmowy.")),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="2xl" aria-describedby={ids.date + "-desc"} data-help="hr.care.conversation">
        <DialogHeader>
          <DialogTitle>{name ? `Rozmowa · ${name}` : "Rozmowa z konsultantem"}</DialogTitle>
          <DialogDescription id={ids.date + "-desc"}>
            {[
              card.data?.client_name,
              planLabel ? `Zamyka punkt planu: ${planLabel}` : null,
              "Bez danych o zdrowiu i bez stawek.",
            ]
              .filter(Boolean)
              .join(" · ")}
          </DialogDescription>
        </DialogHeader>
        <div className="relative min-h-0 flex-1 overflow-y-auto px-6 py-4">
          <div className="grid gap-x-6 gap-y-5 lg:grid-cols-2">
            <div className="space-y-4" aria-label="Dzisiejsza rozmowa" role="group">
              <div className="grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)]">
                <FormField label="Data" htmlFor={ids.date} required>
                  <Input
                    id={ids.date}
                    type="date"
                    value={talk.occurredOn}
                    max={today}
                    onChange={(event) => set({ occurredOn: event.target.value })}
                  />
                </FormField>
                <div className="space-y-1.5">
                  <span className="text-sm font-medium text-foreground">Forma</span>
                  <SegmentedRadio
                    label="Forma rozmowy"
                    size="md"
                    value={talk.channel}
                    onChange={(channel) => set({ channel })}
                    options={CHANNELS.map((value) => ({ value, label: CHANNEL_LABELS[value] }))}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <span className="text-sm font-medium text-foreground">Jak mu się pracuje</span>
                <ScoreButtons value={talk.satisfaction} onChange={(satisfaction) => set({ satisfaction })} />
              </div>
              <FormField label="Notatka" htmlFor={ids.note}>
                <Textarea
                  id={ids.note}
                  rows={4}
                  maxLength={4000}
                  value={talk.note}
                  placeholder="Co słychać w projekcie, czego potrzebuje, co obiecaliśmy."
                  onChange={(event) => set({ note: event.target.value })}
                />
              </FormField>
              <fieldset className="space-y-2.5 rounded-md border border-border/60 p-3">
                <legend className="px-1 text-xs font-medium text-muted-foreground">Sygnały</legend>
                <Signal
                  id={ids.risk}
                  label="Ryzyko odejścia"
                  checked={talk.attritionRisk}
                  onChange={(attritionRisk) => set({ attritionRisk })}
                />
                <Signal
                  id={ids.change}
                  label="Chce zmiany projektu"
                  checked={talk.wantsChange}
                  onChange={(wantsChange) => set({ wantsChange })}
                />
                <Signal
                  id={ids.end}
                  label="Projekt się kończy"
                  checked={talk.projectEnd}
                  onChange={(projectEnd) => set({ projectEnd })}
                >
                  <Input
                    id={ids.endOn}
                    aria-label="Kiedy kończy się projekt"
                    type="date"
                    value={talk.projectEndOn}
                    onChange={(event) => set({ projectEndOn: event.target.value })}
                  />
                </Signal>
                <Signal
                  id={ids.hiring}
                  label="Klient zatrudnia"
                  hint="Karta „Popyt do sprawdzenia” trafi do Delivery Leada klienta."
                  checked={talk.clientHiring}
                  onChange={(clientHiring) => set({ clientHiring })}
                >
                  <div className="space-y-1.5">
                    <Input
                      id={ids.hiringNote}
                      aria-label="Kogo szuka klient"
                      value={talk.hiringNote}
                      maxLength={500}
                      placeholder="np. Java, 2× QA do zespołu płatności"
                      onChange={(event) => set({ hiringNote: event.target.value })}
                    />
                    <SegmentedRadio
                      label="Skąd to wiadomo"
                      size="sm"
                      value={talk.hiringSource}
                      onChange={(hiringSource) => set({ hiringSource })}
                      options={SOURCES.map((value) => ({ value, label: HIRING_SOURCE_LABELS[value] }))}
                    />
                  </div>
                </Signal>
                <p className="text-xs text-muted-foreground">
                  Ryzyko i chęć zmiany trafiają do „Do przepięcia” — na tablicy jako karta „Decyzja”.
                </p>
              </fieldset>
              <FormField
                label="Następny kontakt"
                htmlFor={ids.follow}
                description={
                  cadence
                    ? `Rytm: ${cadenceLabel(cadence.level)}${suggestion ? "" : " — bez stałego terminu"}.`
                    : "Przypomnienie przyjdzie do opiekuna w tym dniu."
                }
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    id={ids.follow}
                    type="date"
                    className="w-44"
                    value={talk.followUp}
                    min={talk.occurredOn}
                    onChange={(event) => set({ followUp: event.target.value })}
                  />
                  {suggestion && suggestion !== talk.followUp ? (
                    <Button size="sm" variant="ghost" onClick={() => set({ followUp: suggestion })}>
                      Podpowiedź: {formatDayMonthPl(suggestion)}
                    </Button>
                  ) : null}
                </div>
              </FormField>
            </div>
            <div className="space-y-5">
              <ClientStateSection
                knownTechnologies={knownTechnologies}
                clientId={resolvedClientId}
                view={clientState.data}
                loading={clientState.isLoading}
                failed={clientState.isError}
                form={stateForm}
                onChange={setStateForm}
              />
              <CareGapQuestions
                clientId={resolvedClientId}
                questions={questions}
                answers={answers}
                onChange={(key, answer) => setAnswers((current) => ({ ...current, [key]: answer }))}
              />
              {casesOpen ? (
                <CasesToOpenSection
                  drafts={cases}
                  onChange={setCases}
                  canPickAssignee={canPickAssignee}
                  handler={caseHandler}
                />
              ) : null}
            </div>
          </div>
        </div>
        <DialogFooter className="items-center sm:justify-between">
          <div className="min-w-0 text-xs text-muted-foreground" aria-live="polite">
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : (
              <p>{saveSummary(payload)}</p>
            )}
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Anuluj
            </Button>
            <Button onClick={submit} loading={save.isPending} disabled={caseTitleBlocked}>
              Zapisz rozmowę
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
