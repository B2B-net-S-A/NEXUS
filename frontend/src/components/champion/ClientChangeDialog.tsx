"use client";

/**
 * „Klient coś zmienił” (23.11.2026, makiety https://claude.ai/artifact/8LzfUqcUmrivAN2RRz6V8F,
 * wariant A + Jarvis). DL wkleja mail albo opisuje zmianę, serwer oddaje
 * listę zmian z cytatem, DL odznacza albo poprawia i zapisuje jednym ruchem.
 *
 * Zapis to ten sam zapis profilu co „Zapisz” (wersja w „Zmiany”, karta
 * „Co się zmieniło” dla rekruterów) ze zdaniem DL w wersji od razu. Krytycznych
 * okno nie ustawia — te DL wybiera w edytorze wierszy.
 */

import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { Loader2, Sparkles } from "lucide-react";

import { useOptionalToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  LEVEL_LABEL_PL,
  groupChanges,
  lateGapCount,
  useApplyClientChange,
  useProposeClientChange,
  wordDiff,
  type ClientChange,
  type ClientChangeGap,
  type ClientChangeLevel,
  type ClientChangeProposal,
} from "@/lib/champion-client-change";
import { countPl, pluralPl } from "@/lib/plural-pl";
import { useWordCounts } from "@/lib/requirement-rows-api";
import { cn } from "@/lib/utils";

const TEXT_MIN = 10;

export interface ClientChangeDialogProps {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Treść od Jarvisa — okno od razu prosi o propozycję. */
  initialText?: string | null;
}

function Op({
  tone,
  children,
}: {
  tone: "add" | "del" | "mod";
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 rounded-md px-1.5 py-px text-[11px] font-semibold",
        tone === "add" && "bg-success/10 text-success",
        tone === "del" && "bg-destructive/10 text-destructive",
        tone === "mod" && "bg-warning/15 text-foreground",
      )}
    >
      {children}
    </span>
  );
}

function Word({
  children,
  strike = false,
}: {
  children: ReactNode;
  strike?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full bg-primary/10 px-2 py-px text-xs font-medium text-primary",
        strike && "line-through opacity-75",
      )}
    >
      {children}
    </span>
  );
}

function Diff({ before, after }: { before: string; after: string }) {
  return (
    <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground">
      {wordDiff(before, after).map((part, i) =>
        part.kind === "same" ? (
          <span key={i}>{part.text}</span>
        ) : part.kind === "add" ? (
          <ins
            key={i}
            className="rounded-sm bg-success/10 text-success no-underline"
          >
            {part.text}
          </ins>
        ) : (
          <del
            key={i}
            className="rounded-sm bg-destructive/10 text-destructive"
          >
            {part.text}
          </del>
        ),
      )}
    </p>
  );
}

function LevelSelect({
  value,
  onChange,
  label,
}: {
  value: ClientChangeLevel;
  onChange: (level: ClientChangeLevel) => void;
  label: string;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value as ClientChangeLevel)}
      className="h-6 rounded-md border border-border bg-card px-1.5 text-xs text-foreground"
    >
      <option value="must">{LEVEL_LABEL_PL.must}</option>
      <option value="nice">{LEVEL_LABEL_PL.nice}</option>
    </select>
  );
}

/** Główny tekst zmiany, który DL może poprawić w miejscu. */
function editableText(change: ClientChange): string | null {
  switch (change.op) {
    case "row_add":
      return change.word;
    case "notes_append":
      return change.text;
    case "talk_add":
      return change.name;
    case "question_add":
      return change.question;
    case "question_edit":
      return (
        change.after.question ??
        change.after.ideal_answer ??
        change.after.deal_breaker ??
        null
      );
    case "text_edit":
      return change.after;
    default:
      return null;
  }
}

function withText(change: ClientChange, text: string): ClientChange {
  switch (change.op) {
    case "row_add":
      return { ...change, word: text };
    case "notes_append":
      return { ...change, text };
    case "talk_add":
      return { ...change, name: text };
    case "question_add":
      return { ...change, question: text };
    case "question_edit": {
      const key =
        change.after.question !== undefined
          ? "question"
          : change.after.ideal_answer !== undefined
            ? "ideal_answer"
            : "deal_breaker";
      return { ...change, after: { ...change.after, [key]: text } };
    }
    case "text_edit":
      return { ...change, after: text };
    default:
      return change;
  }
}

function ChangeBody({
  change,
  people,
  onLevel,
}: {
  change: ClientChange;
  people: Record<string, number | null | undefined>;
  onLevel: (level: ClientChangeLevel) => void;
}) {
  switch (change.op) {
    case "row_add": {
      const n = people[change.word];
      return (
        <div className="flex flex-wrap items-center gap-2">
          <Op tone="add">Dodaj</Op>
          <Word>{change.word}</Word>
          <LevelSelect
            value={change.level}
            onChange={onLevel}
            label={`Poziom: ${change.word}`}
          />
          <span className="text-xs text-muted-foreground">
            {n === undefined
              ? "liczę osoby w bazie…"
              : n === null
                ? "nie policzono osób w bazie"
                : `W bazie: ${n.toLocaleString("pl-PL")} ${pluralPl(n, "osoba", "osoby", "osób")}`}
          </span>
        </div>
      );
    }
    case "row_remove":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <Op tone="del">Usuń</Op>
          <Word strike>{change.word}</Word>
          <span className="text-xs text-muted-foreground">
            było: {LEVEL_LABEL_PL[change.before]}
          </span>
        </div>
      );
    case "row_level":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <Op tone="mod">Zmień poziom</Op>
          <Word>{change.word}</Word>
          <span className="text-xs text-muted-foreground">
            {LEVEL_LABEL_PL[change.before]} →
          </span>
          <LevelSelect
            value={change.level}
            onChange={onLevel}
            label={`Poziom: ${change.word}`}
          />
        </div>
      );
    case "notes_append":
      return (
        <p className="text-[13px]">
          <Op tone="add">Dopisz</Op>{" "}
          <ins className="rounded-sm bg-success/10 text-success no-underline">
            {change.text}
          </ins>
        </p>
      );
    case "talk_add":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <Op tone="add">Dodaj</Op>
          <span className="text-[13px]">{change.name}</span>
          <LevelSelect
            value={change.level}
            onChange={onLevel}
            label={`Poziom: ${change.name}`}
          />
        </div>
      );
    case "question_add":
      return (
        <div className="space-y-0.5 text-[13px]">
          <p className="whitespace-pre-wrap">
            <Op tone="add">Nowe pytanie</Op> {change.question}
          </p>
          {change.ideal_answer ? (
            <p className="text-xs text-muted-foreground">
              Idealnie: {change.ideal_answer}
            </p>
          ) : null}
          {change.deal_breaker ? (
            <p className="text-xs text-muted-foreground">
              Odpada, gdy: {change.deal_breaker}
            </p>
          ) : null}
        </div>
      );
    case "question_remove":
      return (
        <p className="whitespace-pre-wrap text-[13px]">
          <Op tone="del">Usuń pytanie</Op>{" "}
          <del className="text-muted-foreground">{change.before}</del>
        </p>
      );
    case "question_edit":
      return (
        <div className="space-y-1">
          <Op tone="mod">Zmień pytanie</Op>
          {(["question", "ideal_answer", "deal_breaker"] as const).map((key) =>
            change.after[key] !== undefined ? (
              <Diff
                key={key}
                before={change.before[key] ?? ""}
                after={change.after[key] ?? ""}
              />
            ) : null,
          )}
        </div>
      );
    case "text_edit":
      return (
        <div className="space-y-1">
          <Op tone="mod">Zmień</Op>
          <Diff before={change.before} after={change.after} />
        </div>
      );
  }
}

function GapsBox({ gaps }: { gaps: ClientChangeGap[] }) {
  if (gaps.length === 0) return null;
  return (
    <div className="space-y-2 rounded-lg border border-border bg-card px-3 py-2.5">
      <p className="text-[13px] font-semibold">
        Osoby w procesie ({gaps[0].open_total} otwartych)
      </p>
      {gaps.map((gap) => {
        const total =
          gap.missing.before_screening +
          gap.missing.after_screening +
          gap.missing.at_client;
        return (
          <p key={gap.word} className="text-[13px]">
            <span className="font-semibold tabular-nums">{total}</span> bez
            słowa „{gap.word}” w CV: {gap.missing.before_screening} przed
            screeningiem, {gap.missing.after_screening} po screeningu,{" "}
            {gap.missing.at_client} u klienta.
          </p>
        );
      })}
      <p className="text-xs text-muted-foreground">
        Na kartach osób nowe wymaganie pojawi się w „Sprawdzone w CV” jako brak
        potwierdzenia.
      </p>
    </div>
  );
}

export function ClientChangeDialog({
  jobId,
  open,
  onOpenChange,
  initialText,
}: ClientChangeDialogProps) {
  const toast = useOptionalToast();
  const propose = useProposeClientChange(jobId);
  const apply = useApplyClientChange(jobId);
  const textId = useId();
  const noteId = useId();
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<ClientChangeProposal | null>(null);
  const [changes, setChanges] = useState<ClientChange[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [notifyGaps, setNotifyGaps] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const run = (value: string) => {
    setError(null);
    propose.mutate(value, {
      onSuccess: (data) => {
        setProposal(data);
        setChanges(data.changes);
        setSelected(new Set(data.changes.map((c) => c.id)));
        setNote(data.note ?? "");
        setEditing(null);
      },
      onError: (err) =>
        setError(apiErrorMessage(err, "Nie udało się przygotować zmian.")),
    });
  };

  // Jarvis („Pokaż i popraw”) przekazuje treść — okno od razu ją czyta.
  useEffect(() => {
    if (!open || !initialText || initialText.trim().length < TEXT_MIN) return;
    setText(initialText);
    run(initialText);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tylko przy otwarciu z treścią
  }, [open, initialText]);

  const reset = () => {
    setProposal(null);
    setChanges([]);
    setSelected(new Set());
    setEditing(null);
    setNote("");
    setError(null);
  };

  const close = (next: boolean) => {
    if (!next) {
      reset();
      setText("");
    }
    onOpenChange(next);
  };

  const addedWords = useMemo(
    () => changes.flatMap((c) => (c.op === "row_add" ? [c.word] : [])),
    [changes],
  );
  const people = useWordCounts(addedWords, open && addedWords.length > 0);
  const groups = groupChanges(changes);
  const chosen = changes.filter((c) => selected.has(c.id));
  const late = proposal ? lateGapCount(proposal.gaps) : 0;

  const update = (id: string, next: ClientChange) =>
    setChanges((all) => all.map((c) => (c.id === id ? next : c)));

  const save = () => {
    if (!proposal || chosen.length === 0) return;
    setError(null);
    apply.mutate(
      {
        changes: chosen,
        note,
        notifyGaps: notifyGaps && late > 0,
        profileHash: proposal.profile_hash,
      },
      {
        onSuccess: (res) => {
          toast?.showSuccess(
            `Zapisano ${countPl(res.applied, "zmianę", "zmiany", "zmian")}` +
              (res.notified > 0
                ? `, dzwonek „dopytaj” dostało ${countPl(res.notified, "osoba", "osoby", "osób")}.`
                : "."),
          );
          close(false);
        },
        onError: (err) => {
          const status = (err as { response?: { status?: number } })?.response?.status;
          if (status === 409) reset();
          setError(
            status === 409
              ? "Ktoś zmienił Profil w międzyczasie. Przygotuj zmiany ponownie."
              : apiErrorMessage(err, "Nie udało się zapisać zmian."),
          );
        },
      },
    );
  };

  const review =
    proposal !== null && proposal.status === "ready" && changes.length > 0;

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        size={review ? "2xl" : "lg"}
        data-testid="client-change-dialog"
      >
        <DialogHeader>
          <DialogTitle>
            {review
              ? `Zmiana od klienta: ${countPl(changes.length, "zmiana", "zmiany", "zmian")} do sprawdzenia`
              : "Co zmienił klient?"}
          </DialogTitle>
          <DialogDescription>
            {review
              ? "Odznacz, czego nie chcesz, albo popraw tekst. Przy każdej zmianie jest zdanie z treści, z którego wynika."
              : "Wklej mail albo opisz zmianę własnymi słowami. AI porówna ją z Profilem i pokaże listę zmian. Nic nie zapisze się bez Twojej zgody."}
          </DialogDescription>
        </DialogHeader>

        {!review ? (
          <DialogBody className="space-y-3">
            <label htmlFor={textId} className="sr-only">
              Treść od klienta
            </label>
            <Textarea
              id={textId}
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={9}
              maxLength={20_000}
              placeholder="np. „Klient dorzuca Pythona jako musi mieć, SAFe już nieważne, u nich będzie zadanie na żywo z SQL.”"
              data-testid="client-change-text"
            />
            {proposal && proposal.status === "failed" ? (
              <p className="text-sm text-destructive" role="alert">
                {proposal.message}
              </p>
            ) : null}
            {proposal && proposal.status === "ready" && changes.length === 0 ? (
              <p className="text-sm text-muted-foreground" role="status">
                {proposal.message}
              </p>
            ) : null}
            {error ? (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            ) : null}
          </DialogBody>
        ) : (
          <DialogBody className="grid min-h-0 gap-4 md:grid-cols-[minmax(0,1fr)_320px]">
            <div className="min-w-0 space-y-3" data-testid="client-change-list">
              {groups.map((group) => (
                <section
                  key={group.key}
                  className="space-y-1.5"
                  aria-label={group.label}
                >
                  <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {group.label}
                  </h3>
                  {group.changes.map((change) => {
                    const on = selected.has(change.id);
                    const editable = editableText(change);
                    return (
                      <div
                        key={change.id}
                        className={cn(
                          "flex items-start gap-2.5 rounded-lg border border-border bg-card px-2.5 py-2",
                          !on && "opacity-60",
                        )}
                      >
                        <Checkbox
                          checked={on}
                          aria-label={`Zastosuj zmianę ${change.id}`}
                          className="mt-0.5"
                          onCheckedChange={(value) =>
                            setSelected((prev) => {
                              const next = new Set(prev);
                              if (value === true) next.add(change.id);
                              else next.delete(change.id);
                              return next;
                            })
                          }
                        />
                        <div className="min-w-0 flex-1 space-y-1">
                          {editing === change.id && editable !== null ? (
                            <Textarea
                              aria-label="Popraw tekst zmiany"
                              value={editable}
                              rows={
                                change.op === "row_add" ||
                                change.op === "talk_add"
                                  ? 1
                                  : 4
                              }
                              onChange={(e) =>
                                update(
                                  change.id,
                                  withText(change, e.target.value),
                                )
                              }
                            />
                          ) : (
                            <ChangeBody
                              change={change}
                              people={people}
                              onLevel={(level) =>
                                update(change.id, {
                                  ...change,
                                  level,
                                } as ClientChange)
                              }
                            />
                          )}
                          {change.quote ? (
                            <p className="text-xs text-muted-foreground">
                              z treści: <q className="italic">{change.quote}</q>
                            </p>
                          ) : null}
                        </div>
                        {editable !== null ? (
                          <button
                            type="button"
                            className="shrink-0 text-xs text-primary hover:underline"
                            onClick={() =>
                              setEditing(
                                editing === change.id ? null : change.id,
                              )
                            }
                          >
                            {editing === change.id ? "Gotowe" : "Popraw"}
                          </button>
                        ) : null}
                      </div>
                    );
                  })}
                </section>
              ))}
              <p className="text-xs text-muted-foreground">
                „Jednym zdaniem” odświeży się samo po zapisie. Krytyczne
                ustawiasz w „Czego szukamy”.
              </p>
            </div>

            <aside className="min-w-0 space-y-3" aria-label="Co to zmienia">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Co to zmienia
              </h3>
              <GapsBox gaps={proposal.gaps} />
              {late > 0 ? (
                <label className="flex items-start gap-2 text-[13px]">
                  <Checkbox
                    checked={notifyGaps}
                    onCheckedChange={(value) => setNotifyGaps(value === true)}
                    className="mt-0.5"
                    aria-label="Dzwonek dopytaj"
                  />
                  <span>
                    Dzwonek „dopytaj” do osób prowadzących{" "}
                    {countPl(late, "kandydata", "kandydatów", "kandydatów")} po
                    screeningu i u klienta
                  </span>
                </label>
              ) : null}
              <div className="space-y-1.5 rounded-lg border border-border bg-card px-3 py-2.5">
                <label htmlFor={noteId} className="text-[13px] font-semibold">
                  Dla rekruterów: na co klient teraz kładzie nacisk
                </label>
                <Textarea
                  id={noteId}
                  value={note}
                  maxLength={600}
                  rows={4}
                  onChange={(e) => setNote(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Napisało AI, możesz zmienić. Trafi na kartę „Co się zmieniło”.
                </p>
              </div>
              {error ? (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              ) : null}
            </aside>
          </DialogBody>
        )}

        <DialogFooter>
          {review ? (
            <>
              <span className="mr-auto text-xs text-muted-foreground">
                Zapis jak „Zapisz” w Profilu: wersja trafi do zakładki „Zmiany”.
              </span>
              <Button
                variant="outline"
                onClick={reset}
                disabled={apply.isPending}
              >
                ← Wróć do treści
              </Button>
              <Button
                onClick={save}
                disabled={chosen.length === 0 || apply.isPending}
                data-testid="client-change-apply"
              >
                {apply.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Zastosuj {countPl(chosen.length, "zmianę", "zmiany", "zmian")}
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={() => close(false)}>
                Anuluj
              </Button>
              <Button
                onClick={() => run(text)}
                disabled={text.trim().length < TEXT_MIN || propose.isPending}
                data-testid="client-change-propose"
              >
                {propose.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Sparkles className="h-4 w-4" aria-hidden />
                )}
                {propose.isPending ? "Czytam treść…" : "Przygotuj zmiany"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
