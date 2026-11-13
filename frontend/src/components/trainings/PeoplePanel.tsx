"use client";

import { useRef } from "react";
import { Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { TrainingPeople } from "@/lib/api/trainings";

interface PeoplePanelProps {
  people?: TrainingPeople;
  /** Komunikat awarii odczytu — awaria nie może wyglądać jak brak zapisów. */
  error?: string | null;
  loading?: boolean;
  canManage: boolean;
  onImport: (file: File) => Promise<boolean>;
  busy?: boolean;
}

/** Zapisy na szkolenie i obecność z raportu Teams (CSV „Raport obecności”). */
export function PeoplePanel({ people, error = null, loading, canManage, onImport, busy }: PeoplePanelProps) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-3">
      {loading ? <p className="text-sm text-muted-foreground">Ładowanie…</p> : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {people ? (
        <div className="grid gap-4 md:grid-cols-2">
          <section aria-label="Zapisani">
            <h4 className="mb-1 text-xs font-medium text-muted-foreground">
              Zapisani ({people.registrations.length})
            </h4>
            {people.registrations.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nikt się jeszcze nie zapisał.</p>
            ) : (
              <ul className="max-h-60 space-y-1 overflow-y-auto text-sm">
                {people.registrations.map((row, index) => (
                  <li key={`${row.email ?? row.name}-${index}`} className="flex justify-between gap-2">
                    <span className="truncate">{row.name || row.email}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {row.who === "staff" ? "pracownik" : "konsultant"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-label="Obecni">
            <h4 className="mb-1 text-xs font-medium text-muted-foreground">
              Obecni z Teams ({people.attendance.length})
            </h4>
            {people.attendance.length === 0 ? (
              <p className="text-sm text-muted-foreground">Raportu obecności jeszcze nie wgrano.</p>
            ) : (
              <ul className="max-h-60 space-y-1 overflow-y-auto text-sm">
                {people.attendance.map((row, index) => (
                  <li key={`${row.email ?? row.name}-${index}`} className="flex justify-between gap-2">
                    <span className="truncate">
                      {row.name}
                      {row.matched ? null : (
                        <span className="ml-1 text-xs text-muted-foreground">(spoza NEXUSA)</span>
                      )}
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {row.minutes !== null ? `${row.minutes} min` : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      ) : null}
      {canManage ? (
        <div>
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            aria-label="Raport obecności z Teams (CSV)"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (file) await onImport(file);
              event.target.value = "";
            }}
          />
          <Button size="sm" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
            <Upload className="h-3.5 w-3.5" aria-hidden /> Wgraj obecność z Teams (CSV)
          </Button>
          <p className="mt-1 text-xs text-muted-foreground">
            Nowy plik zastępuje poprzedni import obecności.
          </p>
        </div>
      ) : null}
    </div>
  );
}
