"use client";

/**
 * Karta propozycji AI dla zaznaczonego fragmentu CV (Edytor CV 2, PR 3).
 *
 * Pokazuje „było / będzie”, źródło rozwinięcia i decyzję rekrutera. Tekst
 * propozycji i cytatów to TEKST (`**x**` → pogrubienie w React), nic nie
 * trafia na stronę jako HTML. Plakietka „Zgodne ze źródłem” pojawia się tylko
 * wtedy, gdy serwer znalazł zacytowane zdanie w oryginalnym CV albo notatkach
 * i każde słowo propozycji stoi we fragmencie albo w cytacie (`verified`).
 */

import { useId, useState } from "react";
import { BadgeCheck, Loader2, RefreshCw, Sparkles, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { CvAiResponse } from "@/lib/api/cvEditorAi";
import { parseBoldMarkup } from "@/lib/cv-qc";

export interface CvAiProposalCardProps {
  title: string;
  state: "loading" | "proposal" | "message";
  /** Zaznaczony tekst sprzed propozycji. */
  before: string;
  response: CvAiResponse | null;
  message: string | null;
  canRetry: boolean;
  busy: boolean;
  /** CV po polsku, a propozycja to tłumaczenie na angielski. */
  mixedLanguage?: boolean;
  onAccept: () => void;
  onAgain: () => void;
  onRefine: (instruction: string) => void;
  onReject: () => void;
  /** „Pokaż w oryginale” — brak, gdy edytor nie ma panelu źródeł. */
  onShowSource?: (quote: string) => void;
}

const INSTRUCTION_MAX = 300;

/** Znacznik korzenia karty: Escape w jej wnętrzu odrzuca propozycję, nie zamyka edytora. */
export const CV_AI_CARD_ATTR = "data-cv-ai-card";

/** Tekst z pogrubieniem `**x**` jako zwykłe węzły tekstu — nigdy jako HTML. */
export function Marked({ text }: { text: string }) {
  return (
    <>
      {parseBoldMarkup(text).map((run, index) =>
        run.b ? (
          <strong key={index} className="font-semibold">
            {run.t}
          </strong>
        ) : (
          <span key={index}>{run.t}</span>
        ),
      )}
    </>
  );
}

export function CvAiProposalCard({
  title,
  state,
  before,
  response,
  message,
  canRetry,
  busy,
  mixedLanguage = false,
  onAccept,
  onAgain,
  onRefine,
  onReject,
  onShowSource,
}: CvAiProposalCardProps) {
  const [refining, setRefining] = useState(false);
  const [instruction, setInstruction] = useState("");
  const fieldId = useId();
  const proposed = state === "proposal" ? response?.proposed_text : null;

  return (
    <section
      role="dialog"
      aria-label="Propozycja AI"
      // Po tym znaczniku okno edytora poznaje, że Escape należy do karty
      // (Radix słucha na `document`, więc samo `stopPropagation` nie wystarcza).
      {...{ [CV_AI_CARD_ATTR]: "" }}
      className="space-y-2 rounded-lg border border-primary/40 bg-card p-3 text-sm shadow-lg"
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.stopPropagation();
        event.preventDefault();
        onReject();
      }}
    >
      <header className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4 flex-none text-primary" aria-hidden />
        <h3 className="min-w-0 flex-1 text-sm font-semibold">{title}</h3>
        {proposed && response?.verified ? (
          <Badge variant="success" size="sm">
            <BadgeCheck className="size-3" aria-hidden />
            Zgodne ze źródłem
          </Badge>
        ) : null}
        <Button size="icon-sm" variant="ghost" aria-label="Zamknij propozycję" disabled={busy} onClick={onReject}>
          <X className="size-4" aria-hidden />
        </Button>
      </header>

      {state === "loading" ? (
        <p role="status" className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          AI przygotowuje propozycję…
        </p>
      ) : null}

      {state === "message" ? (
        <p role="status" className="text-muted-foreground">
          {message}
        </p>
      ) : null}

      {proposed ? (
        <>
          <dl className="space-y-1.5">
            <div>
              <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Było</dt>
              <dd className="text-muted-foreground [overflow-wrap:anywhere]">
                <Marked text={before} />
              </dd>
            </div>
            <div>
              <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Będzie</dt>
              <dd className="rounded-md bg-success-muted px-2 py-1.5 text-foreground [overflow-wrap:anywhere]">
                <Marked text={proposed} />
              </dd>
            </div>
          </dl>
          {response?.sources.map((source, index) => (
            <p key={index} className="border-l-2 border-border pl-2 text-xs text-muted-foreground">
              Źródło: {source.kind === "notes" ? "notatka rekrutera" : "oryginalne CV"} — <q className="italic">{source.quote}</q>
              {source.kind === "original" && onShowSource ? (
                <>
                  {" "}
                  <button
                    type="button"
                    className="font-medium text-primary hover:underline"
                    onClick={() => onShowSource(source.quote)}
                  >
                    Pokaż w oryginale
                  </button>
                </>
              ) : null}
            </p>
          ))}
          {response?.message ? <p className="text-xs text-warning-muted-foreground">{response.message}</p> : null}
          {response?.cautions.length ? (
            <p className="text-xs text-warning-muted-foreground">
              Sprawdź nazwy, których nie było w zaznaczonym tekście: {response.cautions.join(", ")}.
            </p>
          ) : null}
          {mixedLanguage ? (
            <p className="text-xs text-muted-foreground">
              To CV jest po polsku — etykiety szablonu i klauzula zgody zostają po polsku.
            </p>
          ) : null}
        </>
      ) : null}

      {refining && proposed ? (
        <form
          className="space-y-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            if (!instruction.trim()) return;
            onRefine(instruction);
            setRefining(false);
            setInstruction("");
          }}
        >
          <label htmlFor={fieldId} className="block text-xs font-medium">
            Co zmienić w tej propozycji?
          </label>
          <input
            id={fieldId}
            autoFocus
            maxLength={INSTRUCTION_MAX}
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="np. krócej, bez żargonu"
            className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" size="sm" disabled={!instruction.trim()}>
              Wyślij
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setRefining(false)}>
              Anuluj
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {proposed ? (
            <>
              <Button size="sm" disabled={busy} onClick={onAccept}>
                {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
                Przyjmij
              </Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => setRefining(true)}>
                Doprecyzuj
              </Button>
            </>
          ) : null}
          {proposed || (state === "message" && canRetry) ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={onAgain}>
              <RefreshCw className="size-3.5" aria-hidden />
              Jeszcze raz
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" disabled={busy} onClick={onReject}>
            {state === "loading" ? "Anuluj" : proposed ? "Odrzuć" : "Zamknij"}
          </Button>
        </div>
      )}
    </section>
  );
}
