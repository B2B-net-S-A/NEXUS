"use client";

/**
 * „Odrzuceni przez AI (N)” — zwinięta lista na górze kolumny „Nowi” (0404).
 *
 * Zgłoszenie z linku rekrutacji trafia do „Nowi” dopiero po przeglądzie AI.
 * Osoba, którą AI i kod uznały za niepasującą, zostaje w bazie i tutaj:
 * z powodem po polsku, cytatem z jej CV i przyciskiem „Dodaj mimo to”.
 * Zgłoszenia, których nie udało się ocenić, też tu stoją — AI nie może
 * nikogo zgubić.
 *
 * `ScreenedOutList` jest czysto prezentacyjny (harness
 * `/preview/job-board-screening` renderuje go bez sieci), a
 * `ScreenedOutSection` dociąga dane i zapisuje „Dodaj mimo to”.
 */

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, UserPlus } from "lucide-react";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  mustSummary,
  sourceLabel,
  type ScreenedOutItem,
  useAddScreenedOut,
  useScreenedOut,
} from "@/lib/api/applicationScreenings";

export type ScreenedOutState =
  | { kind: "loading" }
  | { kind: "error"; onRetry: () => void }
  | { kind: "list"; total: number; items: ScreenedOutItem[] };

function fullName(item: ScreenedOutItem): string {
  return [item.name, item.lastname].filter(Boolean).join(" ").trim() || "Kandydat";
}

function appliedOn(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" });
}

export function ScreenedOutList({
  state,
  readOnly,
  addingId = null,
  onAdd,
  defaultOpen = false,
}: {
  state: ScreenedOutState;
  readOnly: boolean;
  addingId?: number | null;
  onAdd?: (item: ScreenedOutItem) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  if (state.kind === "loading") return null;
  if (state.kind === "error") {
    return (
      <p className="px-1 text-xs text-destructive" role="alert" data-testid="screened-out-error">
        Nie wczytano listy odrzuconych przez AI.{" "}
        <button type="button" className="underline" onClick={state.onRetry}>
          Ponów
        </button>
      </p>
    );
  }
  if (state.total === 0) return null;

  const hidden = state.total - state.items.length;
  return (
    <div className="rounded-md border border-border bg-muted/40" data-testid="screened-out">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        )}
        <span className="min-w-0 flex-1">
          Odrzuceni przez AI{" "}
          <span className="tabular-nums" data-testid="screened-out-count">
            ({state.total})
          </span>
        </span>
      </button>
      {open ? (
        <ul className="space-y-1.5 px-2 pb-2">
          {state.items.map((item) => {
            const name = fullName(item);
            const must = mustSummary(item);
            const source = sourceLabel(item.source);
            const meta = [appliedOn(item.applied_at), source, must].filter(Boolean).join(" · ");
            return (
              <li
                key={item.id}
                className="rounded-md border border-border bg-card px-2 py-1.5 text-xs"
                data-testid="screened-out-item"
              >
                <div className="flex items-start justify-between gap-2">
                  <Link
                    href={`/candidates/${item.candidate_id}`}
                    className="min-w-0 truncate font-medium text-foreground hover:text-primary hover:underline"
                  >
                    {name}
                  </Link>
                  {!readOnly && onAdd ? (
                    <button
                      type="button"
                      onClick={() => onAdd(item)}
                      disabled={addingId != null}
                      aria-label={`Dodaj mimo to: ${name}`}
                      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-1.5 py-0.5 text-[11px] font-medium hover:bg-primary/10 hover:text-primary disabled:opacity-50 pointer-coarse:min-h-9 pointer-coarse:px-3"
                    >
                      <UserPlus className="h-3 w-3" aria-hidden="true" />
                      {addingId === item.id ? "Dodaję…" : "Dodaj mimo to"}
                    </button>
                  ) : null}
                </div>
                {meta ? <p className="mt-0.5 text-[11px] text-muted-foreground">{meta}</p> : null}
                {item.reasons.length ? (
                  <ul className="mt-1 space-y-1">
                    {item.reasons.map((reason, index) => (
                      <li key={index} className="text-[11px] leading-snug text-foreground">
                        {reason.text}
                        {reason.quote ? (
                          <span className="mt-0.5 block text-muted-foreground" title="Cytat z CV">
                            „{reason.quote}”
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            );
          })}
          {hidden > 0 ? (
            <li className="px-1 text-[11px] text-muted-foreground">
              Pokazano {state.items.length} z {state.total} — najnowsze.
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

export function ScreenedOutSection({ jobId, readOnly }: { jobId: number; readOnly: boolean }) {
  const toast = useToast();
  const query = useScreenedOut(jobId);
  const add = useAddScreenedOut(jobId);
  const [addingId, setAddingId] = useState<number | null>(null);

  const state: ScreenedOutState = query.isSuccess
    ? { kind: "list", total: query.data.total, items: query.data.items }
    : query.isError
      ? { kind: "error", onRetry: () => void query.refetch() }
      : { kind: "loading" };

  return (
    <ScreenedOutList
      state={state}
      readOnly={readOnly}
      addingId={addingId}
      onAdd={(item) => {
        setAddingId(item.id);
        add.mutate(item.id, {
          onSuccess: () => toast.showSuccess(`Dodano do „Nowi”: ${fullName(item)}`),
          onError: (error) =>
            toast.showError(apiErrorMessage(error, "Nie udało się dodać tej osoby do rekrutacji")),
          onSettled: () => setAddingId(null),
        });
      }}
    />
  );
}
