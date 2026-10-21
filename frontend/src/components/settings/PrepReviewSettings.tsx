"use client";

import { useEffect, useMemo, useState } from "react";
import { History, Plus, RotateCcw, Trash2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ANSWER_GRADES,
  CRITERION_HINTS,
  CRITERION_LABELS,
  GRADE_LABELS,
  MAX_TOPICS,
  PREP1_CRITERIA,
  PREP2_CRITERIA,
  configProblems,
  previewScore,
  usePrepReviewConfig,
  usePublishPrepReviewConfig,
  weightSum,
  type AnswerGradeKey,
  type PrepReviewConfig,
  type PreviewLevel,
} from "@/lib/api/prepReviewConfig";
import { cn } from "@/lib/utils";
import { isForbiddenError } from "@/lib/view-state";

/**
 * Ustawienia → Rekrutacja → Ocena prepów (0505, makiety 1h38jS5LMc1673CENvUejR,
 * plansza 5). Head of Recruitment i admin publikują nową wersję; rekruter
 * i Delivery Lead widzą to samo bez edycji. Zmiana działa od następnej oceny.
 */

type PrepTab = "prep1" | "prep2";

const LEVEL_LABEL: Record<PreviewLevel, string> = { good: "Dobry", ok: "OK", weak: "Słaby" };
const LEVEL_CLASS: Record<PreviewLevel, string> = {
  good: "bg-success-muted text-success-muted-foreground",
  ok: "bg-muted text-foreground",
  weak: "bg-destructive/10 text-destructive",
};
const GRADE_CLASS: Record<AnswerGradeKey, string> = {
  strong: "bg-success-muted text-success-muted-foreground",
  general: "bg-warning-muted text-warning-muted-foreground",
  weak: "bg-destructive/10 text-destructive",
  missing: "bg-muted text-foreground",
};

// Przykładowy prep do podglądu wag (te same liczby co na makiecie, plansze 3 i 4).
const EXAMPLE_SCORES: Record<PrepTab, Record<string, number>> = {
  prep1: { topics: 80, must_answers: 70, client_questions: 67, talk_share: 100 },
  prep2: { prep1_followup: 100, topics: 100, client_questions: 83, talk_share: 90 },
};

const fieldClass =
  "min-h-10 rounded-md border border-border bg-card px-2 text-sm text-foreground disabled:opacity-60";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {children}
    </section>
  );
}

export function PrepReviewSettings() {
  const query = usePrepReviewConfig();
  const publish = usePublishPrepReviewConfig();
  const [draft, setDraft] = useState<PrepReviewConfig | null>(null);
  const [tab, setTab] = useState<PrepTab>("prep1");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (query.data) setDraft(structuredClone(query.data.config));
  }, [query.data]);

  const problems = useMemo(() => (draft ? configProblems(draft) : []), [draft]);

  if (query.isPending) {
    return <p className="text-sm text-muted-foreground">Ładowanie ustawień…</p>;
  }
  if (query.isError) {
    return (
      <QueryStateNotice
        state={isForbiddenError(query.error) ? "forbidden" : "error"}
        description={
          isForbiddenError(query.error)
            ? "Ustawienia oceny prepów widzą rekruter, Delivery Lead, Head of Recruitment i admin."
            : apiErrorMessage(query.error, "Nie udało się wczytać ustawień oceny prepów.")
        }
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (!draft) return null;

  const state = query.data;
  const canEdit = state.can_edit;
  const rules = draft[tab];
  const criteria: string[] = tab === "prep1" ? PREP1_CRITERIA : PREP2_CRITERIA;
  const sum = weightSum(rules.weights);
  const dirty = JSON.stringify(draft) !== JSON.stringify(state.config);
  const example = previewScore(rules.weights, EXAMPLE_SCORES[tab], draft);

  const update = (change: (next: PrepReviewConfig) => void) => {
    setMessage(null);
    setDraft((current) => {
      if (!current) return current;
      const next = structuredClone(current);
      change(next);
      return next;
    });
  };

  async function onPublish() {
    if (!draft) return;
    setMessage(null);
    try {
      const result = await publish.mutateAsync({ config: draft, reason: reason.trim() || undefined });
      setReason("");
      setMessage(
        result.saved
          ? `Opublikowano wersję ${result.version}. Działa od następnej oceny prepu.`
          : "Bez zmian — te ustawienia już obowiązują.",
      );
    } catch (err) {
      setMessage(apiErrorMessage(err, "Nie udało się opublikować ustawień."));
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-w-0 flex-col gap-4">
        {!canEdit ? (
          <p className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
            Tak liczymy ocenę prepów. Zmienia ją Head of Recruitment albo administrator.
          </p>
        ) : null}

        <div role="tablist" aria-label="Który prep" className="flex gap-1 border-b border-border">
          {(
            [
              ["prep1", "Prep 1 · prowadzi Delivery Lead"],
              ["prep2", "Prep 2 (follow-up) · prowadzi rekruter"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={cn(
                "min-h-11 border-b-2 px-3 text-sm",
                tab === id
                  ? "border-primary font-semibold text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <Section title="1. Z czego składa się ocena">
          <div
            className={cn(
              "text-sm font-semibold",
              sum === 100 ? "text-success-muted-foreground" : "text-destructive",
            )}
          >
            Suma wag: {sum}%{sum === 100 ? "" : " — musi być 100%"}
          </div>
          {criteria.map((key) => {
            const weights = rules.weights as Record<string, number>;
            return (
              <label
                key={key}
                className="grid items-center gap-x-3 gap-y-1 text-sm sm:grid-cols-[minmax(0,260px)_minmax(0,1fr)_48px]"
              >
                <span>
                  <span className="font-semibold text-foreground">
                    {CRITERION_LABELS[key as keyof typeof CRITERION_LABELS]}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {CRITERION_HINTS[key as keyof typeof CRITERION_HINTS]}
                  </span>
                </span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={weights[key]}
                  disabled={!canEdit}
                  onChange={(e) =>
                    update((n) => {
                      (n[tab].weights as Record<string, number>)[key] = Number(e.target.value);
                    })
                  }
                  className="accent-primary"
                />
                <span className="font-semibold tabular-nums">{weights[key]}%</span>
              </label>
            );
          })}
        </Section>

        <Section title="2. Tematy prowadzącego">
          <ul className="flex flex-col gap-2">
            {rules.topics.map((topic, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <input
                  aria-label={`Temat ${i + 1}`}
                  value={topic.label}
                  disabled={!canEdit}
                  maxLength={160}
                  onChange={(e) =>
                    update((n) => {
                      n[tab].topics[i].label = e.target.value;
                    })
                  }
                  className={cn(fieldClass, "w-0 min-w-[12rem] flex-1")}
                />
                <label className="flex min-h-10 items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={topic.required}
                    disabled={!canEdit}
                    onChange={(e) =>
                      update((n) => {
                        n[tab].topics[i].required = e.target.checked;
                      })
                    }
                  />
                  obowiązkowy
                </label>
                {canEdit ? (
                  <button
                    type="button"
                    aria-label={`Usuń temat ${i + 1}`}
                    onClick={() =>
                      update((n) => {
                        n[tab].topics.splice(i, 1);
                      })
                    }
                    className="flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          {canEdit && rules.topics.length < MAX_TOPICS ? (
            <button
              type="button"
              onClick={() =>
                update((n) => {
                  n[tab].topics.push({ label: "", required: true });
                })
              }
              className="inline-flex min-h-10 items-center gap-1 self-start text-sm font-semibold text-primary hover:underline"
            >
              <Plus className="h-4 w-4" aria-hidden /> Dodaj temat
            </button>
          ) : null}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.required_topic_caps_ok}
              disabled={!canEdit}
              onChange={(e) => update((n) => void (n.required_topic_caps_ok = e.target.checked))}
            />
            Pominięty temat obowiązkowy = najwyżej „OK”
          </label>
        </Section>

        <Section title="3. Skala odpowiedzi kandydata">
          <p className="text-sm text-muted-foreground">
            AI przypisuje każdej odpowiedzi jeden stopień według tych opisów.
          </p>
          <div className="flex flex-col gap-2">
            {ANSWER_GRADES.map((grade) => (
              <div key={grade} className="flex flex-wrap items-center gap-2">
                <span
                  className={cn(
                    "w-20 shrink-0 rounded-md px-2 py-1 text-center text-xs font-bold",
                    GRADE_CLASS[grade],
                  )}
                >
                  {GRADE_LABELS[grade]}
                </span>
                <input
                  aria-label={`Opis odpowiedzi: ${GRADE_LABELS[grade]}`}
                  value={draft.answer_scale[grade].description}
                  disabled={!canEdit}
                  maxLength={240}
                  onChange={(e) =>
                    update((n) => void (n.answer_scale[grade].description = e.target.value))
                  }
                  className={cn(fieldClass, "w-0 min-w-[12rem] flex-1")}
                />
                <label className="flex items-center gap-1 text-sm">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    aria-label={`Punkty: ${GRADE_LABELS[grade]}`}
                    value={draft.answer_scale[grade].points}
                    disabled={!canEdit}
                    onChange={(e) =>
                      update((n) => void (n.answer_scale[grade].points = Number(e.target.value)))
                    }
                    className={cn(fieldClass, "w-16")}
                  />
                  pkt
                </label>
              </div>
            ))}
          </div>
          <label className="flex flex-wrap items-center gap-2 text-sm">
            Pytania tego klienta: najwyżej
            <input
              type="number"
              min={0}
              max={20}
              aria-label="Najwięcej pytań klienta"
              value={draft.max_client_questions}
              disabled={!canEdit}
              onChange={(e) => update((n) => void (n.max_client_questions = Number(e.target.value)))}
              className={cn(fieldClass, "w-16")}
            />
            najnowszych, pasujących do technologii roli
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.weak_must_caps_ok}
              disabled={!canEdit}
              onChange={(e) => update((n) => void (n.weak_must_caps_ok = e.target.checked))}
            />
            Słaba odpowiedź na must-have = najwyżej „OK”
          </label>
        </Section>

        <Section title="4. Poziomy i reguły">
          {(
            [
              ["good_threshold", "Dobry od", 50, 100],
              ["weak_threshold", "Słaby poniżej", 10, 90],
            ] as const
          ).map(([key, label, min, max]) => (
            <label
              key={key}
              className="grid items-center gap-3 text-sm sm:grid-cols-[180px_minmax(0,1fr)_48px]"
            >
              {label}
              <input
                type="range"
                min={min}
                max={max}
                step={5}
                value={draft[key]}
                disabled={!canEdit}
                onChange={(e) => update((n) => void (n[key] = Number(e.target.value)))}
                className="accent-primary"
              />
              <span className="font-semibold tabular-nums">{draft[key]}%</span>
            </label>
          ))}
          <div className="flex flex-col gap-2 text-sm">
            <label className="flex flex-wrap items-center gap-2">
              <input
                type="checkbox"
                checked={draft.min_minutes_enabled}
                disabled={!canEdit}
                onChange={(e) => update((n) => void (n.min_minutes_enabled = e.target.checked))}
              />
              Prep krótszy niż
              <input
                type="number"
                min={0}
                max={60}
                aria-label="Minimalna długość prepu w minutach"
                value={draft.min_minutes}
                disabled={!canEdit || !draft.min_minutes_enabled}
                onChange={(e) => update((n) => void (n.min_minutes = Number(e.target.value)))}
                className={cn(fieldClass, "w-16")}
              />
              min = słaby
            </label>
            <label className="flex flex-wrap items-center gap-2">
              <input
                type="checkbox"
                checked={draft.talk_share_enabled}
                disabled={!canEdit}
                onChange={(e) => update((n) => void (n.talk_share_enabled = e.target.checked))}
              />
              Kandydat mówi co najmniej
              <input
                type="number"
                min={10}
                max={90}
                aria-label="Cel udziału kandydata w rozmowie"
                value={draft.talk_share_target}
                disabled={!canEdit || !draft.talk_share_enabled}
                onChange={(e) => update((n) => void (n.talk_share_target = Number(e.target.value)))}
                className={cn(fieldClass, "w-16")}
              />
              % czasu
            </label>
          </div>
        </Section>

        <Section title="5. Co trafia do notatki na Prep 2">
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
            {(
              [
                ["weak_answers", "słabe odpowiedzi"],
                ["general_answers", "ogólne odpowiedzi"],
                ["missing_required_topics", "pominięte tematy obowiązkowe"],
                ["unpracticed_client_questions", "nieprzećwiczone pytania klienta"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="flex min-h-10 items-center gap-2">
                <input
                  type="checkbox"
                  checked={draft.followup[key]}
                  disabled={!canEdit}
                  onChange={(e) => update((n) => void (n.followup[key] = e.target.checked))}
                />
                {label}
              </label>
            ))}
            <label className="flex min-h-10 items-center gap-2">
              najwyżej
              <input
                type="number"
                min={1}
                max={12}
                aria-label="Najwięcej punktów w notatce na Prep 2"
                value={draft.followup.max_items}
                disabled={!canEdit}
                onChange={(e) => update((n) => void (n.followup.max_items = Number(e.target.value)))}
                className={cn(fieldClass, "w-16")}
              />
              punktów
            </label>
          </div>
        </Section>

        <Section title="6. Wskazówki dla AI">
          <label htmlFor="prep-review-ai-hints" className="text-sm text-muted-foreground">
            Na co zwracać uwagę przy podsumowaniu i notatce na Prep 2. Nie zmienia wag ani progów.
          </label>
          <textarea
            id="prep-review-ai-hints"
            rows={3}
            maxLength={1500}
            value={draft.ai_hints}
            disabled={!canEdit}
            onChange={(e) => update((n) => void (n.ai_hints = e.target.value))}
            className="rounded-md border border-border bg-card p-2 text-sm text-foreground disabled:opacity-60"
          />
        </Section>
      </div>

      <aside className="flex flex-col gap-4">
        <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
          <h2 className="text-base font-semibold text-foreground">Podgląd na przykładzie</h2>
          <p className="text-xs text-muted-foreground">
            Przykładowy {tab === "prep1" ? "Prep 1" : "Prep 2"}: wynik każdego kryterium razy waga.
          </p>
          <ul className="flex flex-col text-sm">
            {criteria.map((key) => (
              <li key={key} className="flex justify-between gap-2 border-t border-border py-1.5">
                <span>{CRITERION_LABELS[key as keyof typeof CRITERION_LABELS]}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {EXAMPLE_SCORES[tab][key]}% × {(rules.weights as Record<string, number>)[key]}%
                </span>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between border-t border-border pt-2">
            <span className="text-sm font-semibold">Wynik {example.total}%</span>
            <span className={cn("rounded-md px-2 py-1 text-xs font-bold", LEVEL_CLASS[example.level])}>
              {LEVEL_LABEL[example.level]}
            </span>
          </div>
        </section>

        {canEdit ? (
          <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
            <label htmlFor="prep-review-reason" className="text-sm font-semibold">
              Powód zmiany (do historii)
            </label>
            <input
              id="prep-review-reason"
              value={reason}
              maxLength={500}
              onChange={(e) => setReason(e.target.value)}
              className={fieldClass}
            />
            {problems.length > 0 ? (
              <ul role="alert" className="list-disc pl-5 text-xs text-destructive">
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : null}
            <button
              type="button"
              onClick={() => void onPublish()}
              disabled={!dirty || problems.length > 0 || publish.isPending}
              className="min-h-11 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {publish.isPending ? "Publikuję…" : "Opublikuj"}
            </button>
            <button
              type="button"
              onClick={() => {
                setMessage(null);
                setDraft(structuredClone(state.defaults));
              }}
              className="inline-flex min-h-10 items-center justify-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            >
              <RotateCcw className="h-4 w-4" aria-hidden /> Wstaw ustawienia startowe
            </button>
            {message ? (
              <p role="status" className="text-sm text-foreground">
                {message}
              </p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Zmiana działa od następnej oceny. Każda ocena pamięta, według której wersji powstała.
            </p>
          </section>
        ) : null}

        <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <History className="h-4 w-4 text-muted-foreground" aria-hidden /> Historia zmian
          </h2>
          {state.history.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Obowiązują ustawienia startowe — nikt ich jeszcze nie zmieniał.
            </p>
          ) : (
            <ul className="flex flex-col text-sm">
              {state.history.map((entry) => (
                <li key={entry.version} className="border-t border-border py-2">
                  <div className="font-semibold">
                    Wersja {entry.version} · {formatDate(entry.created_at)}
                    {entry.author ? ` · ${entry.author}` : ""}
                  </div>
                  {entry.reason ? (
                    <div className="text-muted-foreground">„{entry.reason}”</div>
                  ) : null}
                  {entry.changes.length > 0 ? (
                    <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                      {entry.changes.map((c) => (
                        <li key={c}>{c}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  );
}
