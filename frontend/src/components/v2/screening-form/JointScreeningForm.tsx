"use client";

/**
 * Formularz screeningu pod kilka rekrutacji w jednej rozmowie (14.10.2026,
 * decyzje Artura D3–D4, makiety B2–B3).
 *
 * Jeden stan formularza (`lib/joint-screening.ts`), zapis osobno do każdej
 * pary tą samą trasą co pojedynczy formularz (`PUT /api/screening-form`,
 * `buildSavePayload` z jej stanu) — wersje, odcisk stanu, blokada 12 h i 409
 * działają per para. „Zapisz i przekaż dalej” przenosi do „Zweryfikowany”
 * w każdej rekrutacji osobno (`usePipelineMoveCore`, wersja procesu z wyniku
 * zapisu tej pary) i mówi w karcie wyniku, gdzie się udało. Para z trafionym
 * deal-breakerem nie przechodzi sama: „Przekaż mimo to” albo jej karta.
 *
 * Notatka z rozmowy: odczyt dla każdej rekrutacji osobno, tylko puste pola;
 * notatkę zakłada zapis kotwicy, kolejne pary wskazują ją `note_id`.
 *
 * Świadomie poza trybem wspólnym (zostają w pojedynczym formularzu):
 * „Użyj tej odpowiedzi” z wcześniejszych rozmów, „Pomiń brakujące”,
 * „Ułóż w zdanie”.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { FormProvider, useForm, type UseFormReturn } from "react-hook-form";
import { AlertTriangle, Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { FIT_OPTIONS } from "@/components/v2/screening/ScreeningForm";
import { NoteFillBar, type NoteFillSummary } from "@/components/v2/screening-form/NoteFillBar";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { apiErrorMessage } from "@/lib/api-error";
import { recommendationCardsApi, type NoteProposal } from "@/lib/api/recommendationCards";
import {
  refreshScreeningFormDependents,
  screeningFormApi,
  screeningFormQueryKey,
  useScreeningQuestionGroups,
  type JointContextPair,
  type ScreeningFormState,
} from "@/lib/api/screeningForm";
import {
  CLIENT_KEY,
  SHARED_ASSESSMENT_KEYS,
  SHARED_TERMS_KEYS,
  budgetVerdict,
  clientKey,
  completeGroups,
  dealBreakerHit,
  forwardBlockers,
  hitKey,
  jobKey,
  jointDefaults,
  noteFillPatches,
  projectPair,
  questionOf,
  type JointDirty,
  type JointGroup,
  type JointPair,
  type JointValues,
} from "@/lib/joint-screening";
import { invalidateAfterPipelineMove } from "@/lib/pipeline-move-invalidation";
import { VERIFIED_STAGE } from "@/lib/pipeline-flow";
import {
  buildSavePayload,
  editableCardKeys,
  formDefaultsFromState,
  formFieldLabel,
  rateFromValues,
  type NoteImport,
} from "@/lib/screening-form";
import { cn } from "@/lib/utils";

export interface JointScreeningFormProps {
  candidateId: number;
  candidateName: string;
  anchor: {
    jobId: number;
    title: string;
    clientId: number | null;
    clientName: string | null;
    budgetHourly: number | null;
    verifiedStageDefId: number | null;
  };
  others: JointContextPair[];
  onMoved?: () => void;
  /** Kotwica przeszła na „Zweryfikowany” — po zamknięciu karty wyniku. */
  onForwarded?: () => void;
}

type ResultKind = "saved" | "unchanged" | "moved" | "save_failed" | "move_refused" | "deal_breaker" | "no_stage";

interface PairResult {
  jobId: number;
  title: string;
  kind: ResultKind;
  message?: string;
  /** Do „Przekaż mimo to”. */
  retry?: { expectedStateVersion: number; acknowledgeEligibility: boolean; rate: ReturnType<typeof rateFromValues> };
}

const RESULT_TONE: Record<ResultKind, "ok" | "bad" | "info"> = {
  saved: "ok",
  unchanged: "info",
  moved: "ok",
  save_failed: "bad",
  move_refused: "bad",
  deal_breaker: "bad",
  no_stage: "info",
};

function pluralQuestions(n: number): string {
  if (n === 1) return "1 pytanie";
  const last = n % 10;
  const teen = n % 100 >= 12 && n % 100 <= 14;
  return `${n} ${last >= 2 && last <= 4 && !teen ? "pytania" : "pytań"}`;
}

export function JointScreeningForm(props: JointScreeningFormProps) {
  const { candidateId, anchor, others } = props;
  const jobIds = useMemo(() => [anchor.jobId, ...others.map((p) => p.job_id)], [anchor.jobId, others]);
  const states = useQueries({
    queries: jobIds.map((jobId) => ({
      queryKey: screeningFormQueryKey(jobId, candidateId),
      queryFn: ({ signal }: { signal: AbortSignal }) => screeningFormApi.get(candidateId, jobId, signal),
      staleTime: 15_000,
    })),
  });
  const groupsQuery = useScreeningQuestionGroups(jobIds);
  const ready = states.every((q) => q.data) && groupsQuery.data;
  if (states.some((q) => q.isError) || groupsQuery.isError) {
    return (
      <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-xs text-destructive-muted-foreground">
        Nie udało się wczytać formularzy wszystkich rekrutacji. Odznacz rekrutację albo spróbuj ponownie.
      </p>
    );
  }
  if (!ready) return <Skeleton className="h-64 w-full rounded-xl" />;
  const pairs: JointPair[] = jobIds.map((jobId, i) => {
    const other = others.find((p) => p.job_id === jobId);
    return {
      jobId,
      title: other?.title ?? anchor.title,
      clientId: other ? other.client_id : anchor.clientId,
      clientName: other?.client_name ?? anchor.clientName,
      budgetHourly: other ? other.budget_hourly : anchor.budgetHourly,
      verifiedStageDefId: other ? other.verified_stage_def_id : anchor.verifiedStageDefId,
      anchor: !other,
      state: states[i].data as ScreeningFormState,
    };
  });
  return (
    <JointFormBody
      key={jobIds.join(",")}
      {...props}
      pairs={pairs}
      groups={completeGroups(pairs, groupsQuery.data!.groups)}
    />
  );
}

function JointFormBody({
  candidateId,
  candidateName,
  pairs,
  groups,
  onMoved,
  onForwarded,
}: JointScreeningFormProps & { pairs: JointPair[]; groups: JointGroup[] }) {
  const queryClient = useQueryClient();
  const anchor = pairs.find((p) => p.anchor) ?? pairs[0];
  const methods = useForm<JointValues>({ defaultValues: jointDefaults(pairs, groups) });
  const moveCore = usePipelineMoveCore({ jobId: anchor.jobId });
  const [busy, setBusy] = useState<"save" | "forward" | null>(null);
  const [blockers, setBlockers] = useState<Array<{ title: string; items: string[] }>>([]);
  const [results, setResults] = useState<PairResult[] | null>(null);
  const [tab, setTab] = useState(anchor.jobId);
  const [note, setNote] = useState<NoteImport | null>(null);
  const [noteSummary, setNoteSummary] = useState<NoteFillSummary | null>(null);

  // Notatka z rozmowy: odczyt kotwicy przyszedł z paska, pozostałe rekrutacje
  // czytamy tym samym tekstem (każda ma własne pytania i wzór pól).
  const onNoteProposal = async (proposal: NoteProposal, source: NoteImport) => {
    const text = proposal.text || source.text;
    const reads = await Promise.allSettled(
      pairs
        .filter((p) => !p.anchor)
        .map(async (p) => ({ pair: p, proposal: await recommendationCardsApi.readNote(candidateId, p.jobId, text) })),
    );
    let filled = 0;
    const apply = (pair: JointPair, read: NoteProposal) => {
      for (const [path, value] of noteFillPatches(methods.getValues(), pair, groups, read)) {
        methods.setValue(path as "answers", value as never, { shouldDirty: true });
        filled += 1;
      }
    };
    apply(anchor, proposal);
    for (const r of reads) if (r.status === "fulfilled") apply(r.value.pair, r.value.proposal);
    setNote({ ...source, text });
    setNoteSummary({ filled, offers: 0, sourceName: source.source_name ?? null });
  };
  const undoNote = () => {
    methods.reset(jointDefaults(pairs, groups));
    setNote(null);
    setNoteSummary(null);
  };

  const shared = groups.filter((g) => g.members.length > 1);
  const ownByJob = pairs.map((p) => ({
    pair: p,
    groups: groups.filter((g) => g.members.length === 1 && g.members[0].jobId === p.jobId),
  }));
  const totalQuestions = groups.reduce((n, g) => n + g.members.length, 0);

  const latest = (pair: JointPair): ScreeningFormState =>
    queryClient.getQueryData<ScreeningFormState>(screeningFormQueryKey(pair.jobId, candidateId)) ?? pair.state;

  const move = async (pair: JointPair, expectedStateVersion: number, acknowledgeEligibility: boolean, rate: ReturnType<typeof rateFromValues>) => {
    if (pair.verifiedStageDefId == null) return { kind: "no_stage" as const, message: "Ta rekrutacja nie ma etapu „Zweryfikowany” w szablonie — przesuń kartę na jej Tablicy." };
    const outcome = await moveCore.send(
      {
        candidate_id: candidateId,
        job_id: pair.jobId,
        stage: VERIFIED_STAGE,
        stage_def_id: pair.verifiedStageDefId,
        expected_state_version: expectedStateVersion,
        ...(rate && latest(pair).can_edit_rate
          ? { expected_rate_value: rate.amount, expected_rate_unit: rate.unit, expected_rate_currency: rate.currency }
          : {}),
        ...(acknowledgeEligibility ? { acknowledge_eligibility: true } : {}),
      },
      { silent: true, candidateName, eligibilitySubject: pair.title },
    );
    if (!pair.anchor) invalidateAfterPipelineMove(queryClient, pair.jobId, candidateId);
    if (outcome.ok) return { kind: "moved" as const };
    return {
      kind: "move_refused" as const,
      message: outcome.refusal.message,
      eligibility: outcome.refusal.kind === "eligibility",
    };
  };

  const run = async (forward: boolean) => {
    const values = methods.getValues();
    const dirty = methods.formState.dirtyFields as JointDirty;
    const plans = [...pairs]
      .sort((a, b) => Number(b.anchor) - Number(a.anchor))
      .map((pair) => ({ pair, projected: projectPair(values, pair, groups, dirty) }));
    if (forward) {
      const missing = plans
        .map(({ pair, projected }) => ({ title: pair.title, items: forwardBlockers(pair, projected) }))
        .filter((b) => b.items.length > 0);
      setBlockers(missing);
      if (missing.length > 0) return;
    }
    setBusy(forward ? "forward" : "save");
    const out: PairResult[] = [];
    // Jedna notatka na rozmowę: zakłada ją pierwszy zapis, następne ją wskazują.
    let noteImport: NoteImport | null = note;
    try {
      for (const { pair, projected } of plans) {
        const state = latest(pair);
        const plan = buildSavePayload(state, projected, { noteImport });
        let version = state.process_state_version;
        if (plan.hasChanges) {
          try {
            const saved = await screeningFormApi.save(plan.payload);
            refreshScreeningFormDependents(queryClient, saved);
            version = saved.process_state_version;
            if (noteImport && noteImport.note_id == null && saved.note_id != null) {
              noteImport = { ...noteImport, note_id: saved.note_id };
            }
          } catch (error) {
            out.push({ jobId: pair.jobId, title: pair.title, kind: "save_failed", message: apiErrorMessage(error, "Nie udało się zapisać.") });
            continue;
          }
        }
        if (!forward) {
          out.push({ jobId: pair.jobId, title: pair.title, kind: plan.hasChanges ? "saved" : "unchanged" });
          continue;
        }
        const rate = rateFromValues(projected);
        if (dealBreakerHit(pair, projected)) {
          out.push({
            jobId: pair.jobId,
            title: pair.title,
            kind: "deal_breaker",
            message: "odpowiedź narusza deal-breaker tej rekrutacji",
            retry: { expectedStateVersion: version, acknowledgeEligibility: false, rate },
          });
          continue;
        }
        const moved = await move(pair, version, false, rate);
        out.push({
          jobId: pair.jobId,
          title: pair.title,
          kind: moved.kind,
          message: "message" in moved ? moved.message : undefined,
          retry: moved.kind === "move_refused" && moved.eligibility ? { expectedStateVersion: version, acknowledgeEligibility: true, rate } : undefined,
        });
      }
    } finally {
      setBusy(null);
      onMoved?.();
    }
    if (out.every((r) => r.kind !== "save_failed")) {
      setNote(null);
      setNoteSummary(null);
    }
    setResults(out);
  };

  const forwardAnyway = async (result: PairResult) => {
    const pair = pairs.find((p) => p.jobId === result.jobId);
    if (!pair || !result.retry) return;
    const moved = await move(pair, latest(pair).process_state_version, result.retry.acknowledgeEligibility, result.retry.rate);
    setResults((prev) =>
      (prev ?? []).map((r) =>
        r.jobId === result.jobId ? { ...r, kind: moved.kind, message: "message" in moved ? moved.message : undefined, retry: undefined } : r,
      ),
    );
    onMoved?.();
  };

  const closeResults = () => {
    const anchorMoved = results?.some((r) => r.jobId === anchor.jobId && r.kind === "moved");
    setResults(null);
    if (anchorMoved) onForwarded?.();
  };

  return (
    <FormProvider {...methods}>
      <form
        data-testid="joint-screening-form"
        data-help="jobs.person.screening-form"
        className="space-y-5"
        onSubmit={(e) => e.preventDefault()}
      >
        {anchor.state.assist_enabled ? (
          <NoteFillBar
            candidateId={candidateId}
            jobId={anchor.jobId}
            applied={noteSummary}
            onProposal={(proposal, source) => void onNoteProposal(proposal, source)}
            onUndo={undoNote}
            disabled={busy != null}
          />
        ) : null}
        <TermsSection methods={methods} pairs={pairs} />
        <QuestionsSection
          methods={methods}
          pairs={pairs}
          shared={shared}
          ownByJob={ownByJob}
          asked={groups.length}
          total={totalQuestions}
        />
        <AssessmentSection methods={methods} pairs={pairs} tab={tab} onTab={setTab} />

        {blockers.length > 0 ? (
          <div role="alert" className="rounded-lg border border-warning/40 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
            <p className="font-semibold">Zanim przekażesz dalej, uzupełnij:</p>
            <ul className="mt-1 list-disc pl-4">
              {blockers.map((b) => (
                <li key={b.title}>
                  {b.title}: {b.items.join(", ")}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {results ? (
          <ResultCard results={results} candidateId={candidateId} anchorJobId={anchor.jobId} onForwardAnyway={forwardAnyway} onClose={closeResults} />
        ) : null}

        <div className="sticky bottom-0 -mx-1 space-y-2 border-t border-border bg-background px-1 pt-3 pb-1">
          <div className="flex items-center justify-end gap-2">
            <span className="mr-auto text-xs text-muted-foreground">
              {pairs.length} rekrutacje · {pluralQuestions(groups.length)} w rozmowie
            </span>
            <Button type="button" variant="outline" size="sm" disabled={busy != null} onClick={() => void run(false)}>
              {busy === "save" ? "Zapisuję…" : `Zapisz w ${pairs.length}`}
            </Button>
          </div>
          <div className="flex justify-end">
            <Button type="button" disabled={busy != null} onClick={() => void run(true)}>
              {busy === "forward" ? "Przekazuję…" : `Zapisz i przekaż dalej w ${pairs.length} → Zweryfikowany`}
            </Button>
          </div>
        </div>
        {moveCore.dialogs}
      </form>
    </FormProvider>
  );
}

// ── Warunki ─────────────────────────────────────────────────────────────────

function TermsSection({ methods, pairs }: { methods: UseFormReturn<JointValues>; pairs: JointPair[] }) {
  const sameRate = methods.watch("shared.same_rate");
  const anchor = pairs.find((p) => p.anchor) ?? pairs[0];
  const sharedKeys = SHARED_TERMS_KEYS.filter((key) => methods.getValues(`shared.card.${key}`) !== undefined);
  const clients = new Map<string, JointPair>();
  for (const pair of pairs) {
    if (editableCardKeys(pair.state).includes(CLIENT_KEY) && !clients.has(clientKey(pair.clientId))) {
      clients.set(clientKey(pair.clientId), pair);
    }
  }
  const canEditRate = pairs.some((p) => p.state.can_edit_rate);
  return (
    <section aria-labelledby="joint-terms" className="space-y-3">
      <div>
        <h3 id="joint-terms" className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Warunki · wspólne dla {pairs.length} rekrutacji
        </h3>
        <p className="text-xs text-muted-foreground">Wpisujesz raz — zapis trafia do każdej zaznaczonej rekrutacji.</p>
      </div>

      {canEditRate ? (
        <div className="space-y-2 rounded-lg border border-border p-3">
          <p className="text-sm font-medium text-foreground">Stawka kandydata</p>
          {sameRate ? (
            <RateInputs methods={methods} prefix="shared" />
          ) : (
            pairs.map((pair) => (
              <div key={pair.jobId}>
                <p className="mb-1 text-xs font-semibold text-muted-foreground">{pair.title}</p>
                <RateInputs methods={methods} prefix={`jobs.${jobKey(pair.jobId)}`} />
              </div>
            ))
          )}
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" {...methods.register("shared.same_rate")} />
            Ta sama stawka we wszystkich rekrutacjach
          </label>
          <ul className="space-y-1">
            {pairs.map((pair) => {
              const values = sameRate ? methods.watch("shared") : methods.watch(`jobs.${jobKey(pair.jobId)}`);
              const verdict = budgetVerdict(rateFromValues(values), pair.budgetHourly);
              return (
                <li
                  key={pair.jobId}
                  className={cn(
                    "rounded-md px-2 py-1 text-xs font-medium",
                    verdict.tone === "ok" && "bg-success-muted text-success-muted-foreground",
                    verdict.tone === "over" && "bg-warning-muted text-warning-muted-foreground",
                    verdict.tone === "unknown" && "bg-muted text-muted-foreground",
                  )}
                >
                  {pair.title}: {verdict.label}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      <div className="grid gap-3 @md:grid-cols-2">
        {sharedKeys.map((key) => (
          <SharedField key={key} methods={methods} name={`shared.card.${key}`} label={formFieldLabel(anchor.state, key)} pairs={pairs} cardKey={key} />
        ))}
      </div>
      {[...clients.entries()].map(([key, pair]) => (
        <SharedField
          key={key}
          methods={methods}
          name={`clients.${key}`}
          label={`${formFieldLabel(pair.state, CLIENT_KEY)}${pair.clientName ? ` — ${pair.clientName}` : ""}`}
          pairs={pairs.filter((p) => clientKey(p.clientId) === key)}
          cardKey={CLIENT_KEY}
        />
      ))}
    </section>
  );
}

function RateInputs({ methods, prefix }: { methods: UseFormReturn<JointValues>; prefix: "shared" | `jobs.${string}` }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <Input
        aria-label={prefix === "shared" ? "Stawka — kwota" : `Stawka — kwota (${prefix})`}
        inputMode="decimal"
        {...methods.register(`${prefix}.rate_amount` as "shared.rate_amount")}
      />
      <select
        aria-label="Jednostka stawki"
        className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        {...methods.register(`${prefix}.rate_unit` as "shared.rate_unit")}
      >
        <option value="hourly">PLN / godzinę</option>
        <option value="daily">PLN / dzień</option>
        <option value="monthly">PLN / miesiąc</option>
      </select>
    </div>
  );
}

function SharedField({
  methods,
  name,
  label,
  pairs,
  cardKey,
}: {
  methods: UseFormReturn<JointValues>;
  name: `shared.card.${string}` | `clients.${string}`;
  label: string;
  pairs: JointPair[];
  cardKey: string;
}) {
  const id = `joint-${name.replace(/\./g, "-")}`;
  const value = (methods.watch(name) as string | undefined) ?? "";
  // Pary z inną zapisaną wartością — rekruter widzi, co zostanie, gdy pola nie ruszy.
  const differing = pairs
    .map((pair) => ({ pair, saved: formDefaultsFromState(pair.state).card?.[cardKey] ?? "" }))
    .filter(({ saved }) => saved.trim() && saved.trim() !== value.trim());
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-foreground">
        {label}
      </label>
      <Input id={id} {...methods.register(name)} />
      {differing.map(({ pair, saved }) => (
        <p key={pair.jobId} className="mt-0.5 text-[11px] text-muted-foreground">
          W {pair.title}: {saved}
        </p>
      ))}
    </div>
  );
}

// ── Pytania ─────────────────────────────────────────────────────────────────

function QuestionsSection({
  methods,
  pairs,
  shared,
  ownByJob,
  asked,
  total,
}: {
  methods: UseFormReturn<JointValues>;
  pairs: JointPair[];
  shared: JointGroup[];
  ownByJob: Array<{ pair: JointPair; groups: JointGroup[] }>;
  asked: number;
  total: number;
}) {
  return (
    <section aria-labelledby="joint-questions" className="space-y-3">
      <h3 id="joint-questions" className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        Pytania · {pluralQuestions(asked)}
        {asked < total ? ` zamiast ${total}` : ""}
      </h3>
      {shared.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-foreground">Wspólne · zadajesz raz</p>
          {shared.map((group) => (
            <QuestionCard key={group.key} methods={methods} pairs={pairs} group={group} />
          ))}
        </div>
      ) : null}
      {ownByJob
        .filter(({ groups }) => groups.length > 0)
        .map(({ pair, groups }) => (
          <div key={pair.jobId} className="space-y-2">
            <p className="text-xs font-semibold text-foreground">Tylko {pair.title} · {groups.length}</p>
            {groups.map((group) => (
              <QuestionCard key={group.key} methods={methods} pairs={pairs} group={group} />
            ))}
          </div>
        ))}
      {shared.length === 0 && ownByJob.every(({ groups }) => groups.length === 0) ? (
        <p className="text-xs text-muted-foreground">
          Te rekrutacje nie mają pytań screeningowych — wystarczy „Dlaczego ten kandydat” w ocenie każdej z nich.
        </p>
      ) : null}
    </section>
  );
}

function QuestionCard({ methods, pairs, group }: { methods: UseFormReturn<JointValues>; pairs: JointPair[]; group: JointGroup }) {
  const members = group.members
    .map((m) => {
      const pair = pairs.find((p) => p.jobId === m.jobId);
      const question = pair ? questionOf(pair, m.questionId) : undefined;
      return pair && question ? { pair, question, member: m } : null;
    })
    .filter((x): x is NonNullable<typeof x> => x != null);
  if (members.length === 0) return null;
  const [first, ...rest] = members;
  const id = `joint-answer-${group.key}`;
  const anyHit = members.some(({ member }) => methods.watch(`hits.${hitKey(member.jobId, member.questionId)}`));
  return (
    <div className={cn("space-y-2 rounded-lg border bg-background/40 p-3", anyHit ? "border-destructive/40" : "border-border")}>
      <label htmlFor={id} className="block text-sm font-semibold text-foreground">
        {first.question.question}
      </label>
      {rest
        .filter(({ question }) => question.question.trim() !== first.question.question.trim())
        .map(({ pair, question }) => (
          <p key={pair.jobId} className="text-[11px] text-muted-foreground">
            {pair.title} pyta: „{question.question}”
          </p>
        ))}
      {members.some(({ question }) => question.ideal_answer || question.deal_breaker) ? (
        <dl className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-xs">
          {members.map(({ pair, question }) => (
            <MemberHints key={pair.jobId} title={members.length > 1 ? pair.title : null} ideal={question.ideal_answer} dealBreaker={question.deal_breaker} />
          ))}
        </dl>
      ) : null}
      <Textarea id={id} rows={2} placeholder="Jak odpowiedział kandydat?" {...methods.register(`answers.${group.key}`)} />
      {members
        .filter(({ question }) => question.deal_breaker)
        .map(({ pair, member }) => (
          <label key={pair.jobId} className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[hsl(var(--destructive))]"
              {...methods.register(`hits.${hitKey(member.jobId, member.questionId)}`)}
            />
            Odpowiedź narusza deal-breaker{members.length > 1 ? ` — ${pair.title}` : ""}
          </label>
        ))}
    </div>
  );
}

function MemberHints({ title, ideal, dealBreaker }: { title: string | null; ideal?: string | null; dealBreaker?: string | null }) {
  return (
    <>
      {ideal ? (
        <>
          <dt className="text-[11px] text-muted-foreground">Idealnie{title ? ` (${title})` : ""}</dt>
          <dd className="text-foreground">{ideal}</dd>
        </>
      ) : null}
      {dealBreaker ? (
        <>
          <dt className="text-[11px] text-muted-foreground">Odpada, gdy{title ? ` (${title})` : ""}</dt>
          <dd className="text-destructive-muted-foreground">{dealBreaker}</dd>
        </>
      ) : null}
    </>
  );
}

// ── Ocena ───────────────────────────────────────────────────────────────────

function AssessmentSection({
  methods,
  pairs,
  tab,
  onTab,
}: {
  methods: UseFormReturn<JointValues>;
  pairs: JointPair[];
  tab: number;
  onTab: (jobId: number) => void;
}) {
  const active = pairs.find((p) => p.jobId === tab) ?? pairs[0];
  const key = jobKey(active.jobId);
  const ownKeys = Object.keys(methods.getValues(`jobs.${key}.card`) ?? {});
  const sharedAssessment = SHARED_ASSESSMENT_KEYS.filter((k) => methods.getValues(`shared.card.${k}`) !== undefined);
  return (
    <section aria-labelledby="joint-assessment" className="space-y-3">
      <h3 id="joint-assessment" className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        Ocena · osobno dla każdej rekrutacji
      </h3>
      <div role="tablist" aria-label="Ocena dla rekrutacji" className="inline-flex flex-wrap overflow-hidden rounded-md border border-border">
        {pairs.map((pair) => {
          const fit = methods.watch(`jobs.${jobKey(pair.jobId)}.overall_fit`);
          const label = FIT_OPTIONS.find((o) => o.value === fit)?.label;
          return (
            <button
              key={pair.jobId}
              type="button"
              role="tab"
              aria-selected={pair.jobId === active.jobId}
              onClick={() => onTab(pair.jobId)}
              className={cn(
                "px-2.5 py-1 text-xs font-semibold",
                pair.jobId === active.jobId ? "bg-foreground text-background" : "bg-background text-muted-foreground hover:bg-muted",
              )}
            >
              {pair.title}
              {label ? ` · ${label}` : ""}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="space-y-3">
        <fieldset>
          <legend className="mb-1 text-xs font-medium text-foreground">Ogólna ocena dopasowania</legend>
          <div className="grid grid-cols-3 gap-1.5">
            {FIT_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className="flex cursor-pointer items-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-xs font-medium has-[:checked]:border-primary has-[:checked]:bg-primary/5"
              >
                <input type="radio" value={opt.value} className="accent-[hsl(var(--primary))]" {...methods.register(`jobs.${key}.overall_fit`)} />
                {opt.label}
              </label>
            ))}
          </div>
        </fieldset>
        {ownKeys.map((cardKey) => {
          const id = `joint-${key}-${cardKey}`;
          return (
            <div key={cardKey}>
              <label htmlFor={id} className="mb-1 block text-xs font-medium text-foreground">
                {formFieldLabel(active.state, cardKey)}
                <span className="font-normal text-muted-foreground"> · dla {active.title}</span>
              </label>
              <Textarea id={id} rows={2} {...methods.register(`jobs.${key}.card.${cardKey}`)} />
            </div>
          );
        })}
      </div>
      {sharedAssessment.map((cardKey) => (
        <div key={cardKey}>
          <label htmlFor={`joint-shared-${cardKey}`} className="mb-1 block text-xs font-medium text-foreground">
            {formFieldLabel(active.state, cardKey)} <span className="font-normal text-muted-foreground">· wspólne, tylko dla zespołu</span>
          </label>
          <Textarea id={`joint-shared-${cardKey}`} rows={2} {...methods.register(`shared.card.${cardKey}`)} />
        </div>
      ))}
    </section>
  );
}

// ── Wynik ───────────────────────────────────────────────────────────────────

function ResultCard({
  results,
  candidateId,
  anchorJobId,
  onForwardAnyway,
  onClose,
}: {
  results: PairResult[];
  candidateId: number;
  anchorJobId: number;
  onForwardAnyway: (r: PairResult) => void;
  onClose: () => void;
}) {
  const LABEL: Record<ResultKind, string> = {
    saved: "zapisano",
    unchanged: "bez zmian",
    moved: "→ Zweryfikowany",
    save_failed: "nie zapisano",
    move_refused: "zapisano, nie przekazano",
    deal_breaker: "zapisano, nie przekazano",
    no_stage: "zapisano — przesuń na jej Tablicy",
  };
  return (
    <section aria-label="Wynik zapisu" role="status" className="space-y-2 rounded-xl border border-border bg-muted/30 p-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-foreground">Wynik w {results.length} rekrutacjach</p>
        <Button type="button" size="sm" variant="ghost" onClick={onClose} aria-label="Zamknij wynik">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <ul className="space-y-2">
        {results.map((r) => {
          const tone = RESULT_TONE[r.kind];
          return (
            <li key={r.jobId} className="flex gap-2 text-xs" data-testid={`joint-result-${r.jobId}`}>
              {tone === "ok" ? (
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success-muted-foreground" aria-hidden="true" />
              ) : tone === "bad" ? (
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive-muted-foreground" aria-hidden="true" />
              ) : (
                <span className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              )}
              <div className="min-w-0 flex-1">
                <p>
                  <strong>{r.title}</strong> — {LABEL[r.kind]}
                </p>
                {r.message ? <p className="text-muted-foreground">{r.message}</p> : null}
                {r.retry || (r.kind === "deal_breaker" && r.jobId !== anchorJobId) || r.kind === "no_stage" ? (
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {r.retry ? (
                      <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={() => onForwardAnyway(r)}>
                        Przekaż mimo to
                      </Button>
                    ) : null}
                    {r.jobId !== anchorJobId ? (
                      <Link
                        href={`/jobs/${r.jobId}?candidate=${candidateId}`}
                        className="inline-flex h-7 items-center rounded-md border border-border px-2 text-xs font-semibold text-primary hover:bg-muted"
                      >
                        Otwórz jej kartę
                      </Link>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
