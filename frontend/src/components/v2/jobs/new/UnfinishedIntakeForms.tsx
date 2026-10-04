"use client";

/**
 * „Masz N niedokończonych formularzy” — krok 1 strony `/jobs/new`
 * (04.10.2026). Rekrutacja nie jest już szkicem: praca, której nie da się
 * jeszcze opublikować, czeka na koncie autora. Usunięcie potwierdza się
 * w wierszu (bez natywnego `confirm`, który zamraża automatyzację przeglądarki).
 */

import { useState } from "react";
import { FileClock, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  expiresInDays,
  type IntakeFormListItem,
} from "@/lib/api/jobIntakeForms";
import { formatDateTimePl } from "@/lib/date-pl";

function formsHeadline(count: number): string {
  if (count === 1) return "Masz 1 niedokończony formularz";
  const lastTwo = count % 100;
  const last = count % 10;
  const few = last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14);
  return `Masz ${count} ${few ? "niedokończone formularze" : "niedokończonych formularzy"}`;
}

function daysPhrase(days: number): string {
  if (days === 0) return "usunie się sam dziś";
  if (days === 1) return "usunie się sam jutro";
  return `usunie się sam za ${days} dni`;
}

interface Props {
  items: IntakeFormListItem[];
  /** Wiersz, który właśnie się wczytuje albo kasuje. */
  busyId: number | null;
  onResume: (id: number) => void;
  onDelete: (id: number) => void;
}

export function UnfinishedIntakeForms({ items, busyId, onResume, onDelete }: Props) {
  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  if (items.length === 0) return null;
  return (
    <section
      aria-labelledby="unfinished-intake-forms-title"
      data-testid="unfinished-intake-forms"
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 sm:p-5"
    >
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <FileClock className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <h2
            id="unfinished-intake-forms-title"
            className="text-sm font-semibold text-foreground"
          >
            {formsHeadline(items.length)}
          </h2>
          <p className="text-xs text-muted-foreground">
            Rekrutacja powstaje dopiero kompletna. Do tego czasu formularz czeka tutaj,
            widzisz go tylko Ty.
          </p>
        </div>
      </div>
      <ul className="flex flex-col divide-y divide-border">
        {items.map((item) => {
          const days = expiresInDays(item.expires_at);
          const confirming = confirmingId === item.id;
          const busy = busyId === item.id;
          return (
            <li
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-2.5"
            >
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm font-medium text-foreground">
                  {item.label}
                  {item.client_name ? (
                    <span className="font-normal text-muted-foreground"> · {item.client_name}</span>
                  ) : null}
                </span>
                <span className="text-xs text-muted-foreground">
                  Zapisany {formatDateTimePl(item.updated_at)}
                  {item.missing_count != null && item.missing_count > 0
                    ? `, brakuje ${item.missing_count}`
                    : null}
                  {days != null ? ` · ${daysPhrase(days)}` : null}
                </span>
              </div>
              {confirming ? (
                <div className="flex items-center gap-2" role="group" aria-label="Potwierdź usunięcie">
                  <span className="text-xs text-foreground">Usunąć formularz?</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    loading={busy}
                    onClick={() => onDelete(item.id)}
                  >
                    Usuń
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => setConfirmingId(null)}
                  >
                    Anuluj
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    loading={busy}
                    disabled={busyId != null && !busy}
                    onClick={() => onResume(item.id)}
                  >
                    Dokończ
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="quiet"
                    disabled={busyId != null}
                    aria-label={`Usuń formularz: ${item.label}`}
                    onClick={() => setConfirmingId(item.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    Usuń
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
