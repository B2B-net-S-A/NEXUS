"use client";

import { Plus, Trash2 } from "lucide-react";

import {
  MAX_FUNDAMENTALS,
  MAX_READINESS,
  type FundamentalGroup,
  type Preparation,
} from "@/lib/api/prepReviewConfig";
import { cn } from "@/lib/utils";

/**
 * Ustawienia → Ocena prepów → „Przygotowanie” (F1, decyzje Artura 24.11.2026):
 * fundamenty, które rekruter przechodzi z każdym kandydatem przed prepem
 * z Delivery Leadem, i lista „kandydat po przygotowaniu umie”. Wyjątki klienta
 * (np. umowa o pracę) stoją w jego karcie, nie tutaj.
 */

export type PreparationChange = (change: (preparation: Preparation) => void) => void;

interface EditorProps {
  preparation: Preparation;
  canEdit: boolean;
  onChange: PreparationChange;
}

const fieldClass =
  "min-h-10 rounded-md border border-border bg-card px-2 text-sm text-foreground disabled:opacity-60";

const STOP_HINT = "Gdy się nie zgadza, rekruter kończy rozmowę i od razu daje znać DL-owi.";

function StopBadge() {
  return (
    <span
      title={STOP_HINT}
      className="rounded bg-destructive-muted px-1.5 py-0.5 text-[11px] font-semibold text-destructive-muted-foreground"
    >
      warunek stop
    </span>
  );
}

/** Numer punktu ciągły przez wszystkie grupy (1–18), jak w materiale dla rekruterów. */
function firstNumbers(groups: FundamentalGroup[]): number[] {
  let next = 1;
  return groups.map((g) => {
    const first = next;
    next += g.items.length;
    return first;
  });
}

export function FundamentalsEditor({ preparation, canEdit, onChange }: EditorProps) {
  const firsts = firstNumbers(preparation.groups);
  return (
    <div className="flex flex-col gap-4">
      {preparation.groups.map((group, g) =>
        !canEdit && group.items.length === 0 ? null : (
          <div key={g} className="flex flex-col gap-1">
            {canEdit ? (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  aria-label={`Grupa ${g + 1}: nazwa`}
                  value={group.title}
                  maxLength={80}
                  onChange={(e) => onChange((p) => void (p.groups[g].title = e.target.value))}
                  className={cn(fieldClass, "w-0 min-w-[12rem] flex-1 font-semibold")}
                />
                <input
                  aria-label={`Grupa ${g + 1}: wskazówka`}
                  placeholder="Wskazówka dla rekrutera (opcjonalnie)"
                  value={group.hint}
                  maxLength={200}
                  onChange={(e) => onChange((p) => void (p.groups[g].hint = e.target.value))}
                  className={cn(fieldClass, "w-0 min-w-[12rem] flex-[2]")}
                />
              </div>
            ) : (
              <div className="flex flex-wrap items-baseline gap-x-3">
                <h3 className="text-sm font-semibold text-foreground">{group.title}</h3>
                {group.hint ? (
                  <span className="text-xs text-muted-foreground">{group.hint}</span>
                ) : null}
              </div>
            )}
            <ol className="flex flex-col divide-y divide-border">
              {group.items.map((item, i) => {
                const n = firsts[g] + i;
                return canEdit ? (
                  <li key={i} className="flex flex-col gap-2 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="w-6 shrink-0 text-sm tabular-nums text-muted-foreground">
                        {n}.
                      </span>
                      <input
                        aria-label={`Punkt ${n}: nazwa`}
                        value={item.label}
                        maxLength={80}
                        onChange={(e) =>
                          onChange((p) => void (p.groups[g].items[i].label = e.target.value))
                        }
                        className={cn(fieldClass, "w-0 min-w-[12rem] flex-1 font-semibold")}
                      />
                      <label className="flex min-h-10 items-center gap-2 text-sm" title={STOP_HINT}>
                        <input
                          type="checkbox"
                          checked={item.stop}
                          onChange={(e) =>
                            onChange((p) => void (p.groups[g].items[i].stop = e.target.checked))
                          }
                        />
                        warunek stop
                      </label>
                      <button
                        type="button"
                        aria-label={`Usuń punkt ${n}`}
                        onClick={() => onChange((p) => void p.groups[g].items.splice(i, 1))}
                        className="flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </button>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2 sm:pl-8">
                      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                        Co mówisz albo o co pytasz
                        <textarea
                          rows={3}
                          maxLength={400}
                          value={item.says}
                          onChange={(e) =>
                            onChange((p) => void (p.groups[g].items[i].says = e.target.value))
                          }
                          className="rounded-md border border-border bg-card p-2 text-sm text-foreground"
                        />
                      </label>
                      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                        Zaliczone, gdy
                        <textarea
                          rows={3}
                          maxLength={240}
                          value={item.passed_when}
                          onChange={(e) =>
                            onChange(
                              (p) => void (p.groups[g].items[i].passed_when = e.target.value),
                            )
                          }
                          className="rounded-md border border-border bg-card p-2 text-sm text-foreground"
                        />
                      </label>
                    </div>
                  </li>
                ) : (
                  <li key={i} className="flex gap-2 py-2 text-sm">
                    <span className="w-6 shrink-0 tabular-nums text-muted-foreground">{n}.</span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-foreground">{item.label}</span>
                        {item.stop ? <StopBadge /> : null}
                      </div>
                      {item.says ? <p className="text-foreground">{item.says}</p> : null}
                      {item.passed_when ? (
                        <p className="text-muted-foreground">
                          <span className="font-semibold">Zaliczone, gdy:</span> {item.passed_when}
                        </p>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ol>
            {canEdit && group.items.length < MAX_FUNDAMENTALS ? (
              <button
                type="button"
                onClick={() =>
                  onChange(
                    (p) =>
                      void p.groups[g].items.push({
                        label: "",
                        says: "",
                        passed_when: "",
                        stop: false,
                      }),
                  )
                }
                className="inline-flex min-h-10 items-center gap-1 self-start text-sm font-semibold text-primary hover:underline"
              >
                <Plus className="h-4 w-4" aria-hidden /> Dodaj punkt
              </button>
            ) : null}
          </div>
        ),
      )}
    </div>
  );
}

export function ReadinessEditor({ preparation, canEdit, onChange }: EditorProps) {
  if (!canEdit) {
    return (
      <ul className="list-disc space-y-0.5 pl-5 text-sm text-foreground">
        {preparation.readiness.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-2">
        {preparation.readiness.map((r, i) => (
          <li key={i} className="flex items-center gap-2">
            <input
              aria-label={`Kandydat umie ${i + 1}`}
              value={r}
              maxLength={160}
              onChange={(e) => onChange((p) => void (p.readiness[i] = e.target.value))}
              className={cn(fieldClass, "w-0 min-w-[12rem] flex-1")}
            />
            <button
              type="button"
              aria-label={`Usuń „kandydat umie” ${i + 1}`}
              onClick={() => onChange((p) => void p.readiness.splice(i, 1))}
              className="flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </button>
          </li>
        ))}
      </ul>
      {preparation.readiness.length < MAX_READINESS ? (
        <button
          type="button"
          onClick={() => onChange((p) => void p.readiness.push(""))}
          className="inline-flex min-h-10 items-center gap-1 self-start text-sm font-semibold text-primary hover:underline"
        >
          <Plus className="h-4 w-4" aria-hidden /> Dodaj
        </button>
      ) : null}
    </div>
  );
}
