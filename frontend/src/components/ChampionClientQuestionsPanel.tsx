"use client";

import { useState } from "react";
import { Plus } from "lucide-react";

import { AllClientQuestions } from "@/components/AllClientQuestions";
import { WorkspaceModeTabs } from "@/components/ds/WorkspaceModeTabs";
import {
  useClientQuestionArchive,
  useClientQuestionPool,
} from "@/lib/api/interviewCycle";

/** Porównanie „to samo pytanie”: bez wielkości liter, białych znaków i punktorów. */
export function normalizeQuestion(text: string): string {
  return text
    .replace(/^[\s•\-*–·]+/, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** Linie pola „Historyczne pytania klienta” jako znormalizowany zbiór. */
function historicalSet(historical: string): Set<string> {
  return new Set(
    historical
      .split("\n")
      .map(normalizeQuestion)
      .filter(Boolean),
  );
}

interface RowActions {
  inScreening: Set<string>;
  inHistorical: Set<string>;
  canEdit: boolean;
  onAddScreening: (text: string) => void;
  onAddHistorical: (text: string) => void;
}

function QuestionRow({
  text,
  testId,
  matched,
  actions,
}: {
  text: string;
  testId: string;
  matched?: string[];
  actions: RowActions;
}) {
  const key = normalizeQuestion(text);
  const hasScreening = actions.inScreening.has(key);
  const hasHistorical = actions.inHistorical.has(key);
  return (
    <li className="rounded-md border border-border bg-card px-2.5 py-2" data-testid={testId}>
      <p className="text-xs text-foreground">{text}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
        {matched && matched.length > 0 ? (
          <span className="text-[11px] text-muted-foreground">
            pasuje: {matched.join(", ")}
          </span>
        ) : null}
        {hasScreening || hasHistorical ? (
          <span className="text-[11px] text-muted-foreground">już w profilu</span>
        ) : null}
        {actions.canEdit && !hasScreening ? (
          <button
            type="button"
            onClick={() => actions.onAddScreening(text)}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
          >
            <Plus className="h-3 w-3" aria-hidden />
            Dodaj do pytań screeningowych
          </button>
        ) : null}
        {actions.canEdit && !hasHistorical ? (
          <button
            type="button"
            onClick={() => actions.onAddHistorical(text)}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
          >
            <Plus className="h-3 w-3" aria-hidden />
            Dodaj do historycznych pytań
          </button>
        ) : null}
      </div>
    </li>
  );
}

/**
 * Archiwum rozmów (Excel rekruterów sprzed NEXUSA, 0383): tylko pytania
 * o technologie tej roli. Zwinięte i pobierane dopiero po rozwinięciu — to
 * materiał pomocniczy, nie „co klient pytał ostatnio”.
 */
function ArchiveSection({ jobId, actions }: { jobId: number; actions: RowActions }) {
  const [open, setOpen] = useState(false);
  const query = useClientQuestionArchive(jobId, open);
  const questions = Array.isArray(query.data) ? query.data : [];
  return (
    <div className="mt-3 border-t border-border pt-2" data-testid="champion-client-archive">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="text-xs font-semibold text-foreground hover:underline"
      >
        {open ? "▾" : "▸"} Z archiwum rozmów (podobne role)
        {query.isSuccess ? ` (${questions.length})` : ""}
      </button>
      {!open ? null : (
        <>
          <p className="mt-0.5 mb-2 text-[11px] text-muted-foreground">
            Pytania tego klienta zapisane przez rekruterów przed NEXUSEM — tylko
            o technologie z wymagań tej rekrutacji.
          </p>
          {query.isPending ? (
            <p className="text-xs text-muted-foreground">Wczytuję archiwum…</p>
          ) : query.isError ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-destructive">
              Nie udało się wczytać archiwum — pytania mogą istnieć.
              <button type="button" onClick={() => query.refetch()} className="font-medium underline">
                Ponów
              </button>
            </div>
          ) : questions.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Brak pytań z archiwum o technologie tej roli.
            </p>
          ) : (
            <ul className="space-y-2">
              {questions.map((q) => (
                <QuestionRow
                  key={q.id}
                  text={q.text}
                  matched={q.matched}
                  testId={`champion-archive-question-${q.id}`}
                  actions={actions}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

type QuestionsTab = "job" | "client";

function JobQuestions({ jobId, actions }: { jobId: number; actions: RowActions }) {
  const query = useClientQuestionPool("job", jobId);
  const questions = Array.isArray(query.data) ? query.data : [];
  if (query.isPending) {
    return <p className="text-xs text-muted-foreground">Wczytuję pytania klienta…</p>;
  }
  if (query.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-destructive">
        Nie udało się wczytać pytań klienta — lista może istnieć.
        <button
          type="button"
          onClick={() => query.refetch()}
          className="font-medium underline"
        >
          Ponów
        </button>
      </div>
    );
  }
  if (questions.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Jeszcze nic — pytania pojawią się po pierwszym telefonie do kandydata po
        rozmowie w tej rekrutacji. Pytania z innych rekrutacji tego klienta są
        w zakładce „Wszystkie pytania klienta”.
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {questions.map((q) => (
        <QuestionRow
          key={q.id}
          text={q.text}
          testId={`champion-client-question-${q.id}`}
          actions={actions}
        />
      ))}
    </ul>
  );
}

/**
 * „Pytania klienta z rozmów”: domyślnie tylko pytania zadane na rozmowach w tej
 * rekrutacji (zgłoszenie 02.11.2026: przy PM-ie stały pytania z Javy), a pełna
 * lista klienta i archiwum w drugiej zakładce. Delivery Lead dopisuje je do
 * pytań screeningowych albo do historycznych pytań klienta w profilu Championa.
 *
 * Panel edytuje WYŁĄCZNIE szkic edytora (`onAddScreening`/`onAddHistorical`) —
 * zapis zostaje zwykłym „Zapisz” profilu. Awaria odczytu jest komunikatem,
 * nie pustą listą: pustka czytałaby się jak „klient nigdy o nic nie pytał”.
 */
export function ChampionClientQuestionsPanel({
  jobId,
  screeningQuestions,
  historicalQuestions,
  canEdit,
  onAddScreening,
  onAddHistorical,
}: {
  jobId: number;
  screeningQuestions: string[];
  historicalQuestions: string;
  canEdit: boolean;
  onAddScreening: (text: string) => void;
  onAddHistorical: (text: string) => void;
}) {
  const [tab, setTab] = useState<QuestionsTab>("job");
  const jobQuery = useClientQuestionPool("job", jobId);
  const jobCount = Array.isArray(jobQuery.data) ? jobQuery.data.length : 0;
  const actions: RowActions = {
    inScreening: new Set(screeningQuestions.map(normalizeQuestion).filter(Boolean)),
    inHistorical: historicalSet(historicalQuestions),
    canEdit,
    onAddScreening,
    onAddHistorical,
  };

  return (
    <section
      className="rounded-lg border border-border bg-muted/40 p-3"
      data-testid="champion-client-questions"
      aria-labelledby="champion-client-questions-heading"
    >
      <h4
        id="champion-client-questions-heading"
        className="mb-1 text-xs font-semibold text-foreground"
      >
        Pytania klienta z rozmów
      </h4>
      <div data-tour="jobs.client-questions.scope">
        <WorkspaceModeTabs<QuestionsTab>
          label="Zakres pytań klienta"
          value={tab}
          onChange={setTab}
          modes={[
            { value: "job", label: "Z tej rekrutacji", count: jobCount },
            { value: "client", label: "Wszystkie pytania klienta" },
          ]}
        />
      </div>
      {tab === "job" ? (
        <>
          <p className="mt-2 mb-2 text-[11px] text-muted-foreground">
            Zebrane w telefonach do kandydatów po rozmowach w tej rekrutacji.
          </p>
          <JobQuestions jobId={jobId} actions={actions} />
        </>
      ) : (
        <>
          <p className="mt-2 mb-2 text-[11px] text-muted-foreground">
            Pytania z rozmów we wszystkich rekrutacjach tego klienta.
          </p>
          <AllClientQuestions
            jobId={jobId}
            renderQuestion={(q, group) => (
              <QuestionRow
                key={q.id}
                text={q.text}
                testId={`champion-all-question-${group.jobId ?? "none"}-${q.id}`}
                actions={actions}
              />
            )}
          />
          <ArchiveSection jobId={jobId} actions={actions} />
        </>
      )}
    </section>
  );
}
