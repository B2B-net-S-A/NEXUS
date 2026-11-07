"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Users } from "lucide-react";

import { jobGateErrorText } from "@/lib/job-gate-errors";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { HeadcountEditor, patchJobFields } from "./JobSettingsPanel";

export interface JobHeadcountFactProps {
  jobId: number;
  /** `Job.headcount` — ilu osób szuka klient. */
  headcount: number | null;
  /**
   * Ta sama reguła co wiersz „Liczba osób” w Profilu Championa › Zespół:
   * `useJobTeamPermissions(job).editScope === "full"`. Bez niej sam odczyt.
   */
  canEdit: boolean;
  /** Zamknięta rekrutacja już nie „szuka” — sama liczba. */
  closed?: boolean;
}

/** „Szukamy 1 osoby”, „Szukamy 3 osób” — dopełniacz po „szukamy”. */
export function headcountFactText(headcount: number | null, closed = false): string {
  if (headcount == null) return "Liczba osób: nie podano";
  if (closed) return `Liczba osób: ${headcount}`;
  return `Szukamy ${headcount} ${headcount === 1 ? "osoby" : "osób"}`;
}

/**
 * Przy 1280 px pełne zdanie ścinało nazwę klienta do jednej litery (zrzut
 * ze stagingu 07.11.2026), więc poniżej `2xl` sama liczba za ikoną osób —
 * zdanie zostaje w dymku i dla czytnika ekranu (jak forma zwarta paska).
 */
function FactLabel({ headcount, text }: { headcount: number | null; text: string }) {
  if (headcount == null) return <span>{text}</span>;
  return (
    <>
      <span className="2xl:hidden" aria-hidden="true">
        {headcount}
      </span>
      <span className="hidden 2xl:inline" aria-hidden="true">
        {text}
      </span>
    </>
  );
}

const CHIP_CLASS =
  "inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border px-2.5 text-[13px] font-semibold";

/**
 * Liczba osób w nagłówku rekrutacji, za faktem „Rekruter” (07.11.2026,
 * pytania do Jarvisa: Delivery Lead szukał, gdzie zmienić liczbę wakatów,
 * i dostał dwie różne ścieżki). Edycja w miejscu: to samo pole i ten sam zapis
 * (`PATCH /api/jobs/{id}` z `headcount`) co Profil Championa › Zespół.
 */
export function JobHeadcountFact({
  jobId,
  headcount,
  canEdit,
  closed = false,
}: JobHeadcountFactProps) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const text = headcountFactText(headcount, closed);
  const missing = headcount == null;

  if (!canEdit) {
    return (
      <span
        className={cn(
          CHIP_CLASS,
          "border-primary/20 bg-primary/5",
          missing ? "font-normal text-muted-foreground" : "text-foreground",
        )}
        data-testid="job-header-headcount"
        data-tour="job.headcount"
        title={text}
        aria-label={text}
        role="note"
      >
        <Users className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        <FactLabel headcount={headcount} text={text} />
      </span>
    );
  }

  const save = async (value: number) => {
    setSaving(true);
    setError(null);
    try {
      await patchJobFields(queryClient, jobId, { headcount: value });
      setOpen(false);
    } catch (err) {
      // `handoff_regression` i inne odmowy bramki — zdanie serwera przy polu.
      setError(jobGateErrorText(err, "Nie udało się zapisać liczby osób."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setError(null);
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`${text} — zmień liczbę osób`}
          title={`${text} — kliknij, żeby zmienić`}
          data-testid="job-header-headcount"
          data-tour="job.headcount"
          className={cn(
            CHIP_CLASS,
            "border-primary/20 bg-primary/5 transition-colors hover:border-primary/50",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9",
            missing ? "font-normal text-muted-foreground" : "text-foreground",
          )}
        >
          <Users className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          <FactLabel headcount={headcount} text={text} />
          <Pencil className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        collisionPadding={8}
        data-testid="job-headcount-popover"
        className="w-[min(280px,calc(100vw-2rem))] space-y-2"
      >
        <p className="text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground">
          Liczba osób do zatrudnienia
        </p>
        {/* Nowy edytor przy każdym otwarciu — pole startuje od zapisanej liczby. */}
        {open ? (
          <HeadcountEditor headcount={headcount} saving={saving} onSave={save} />
        ) : null}
        {error ? (
          <p role="alert" className="text-[11px] text-destructive">
            {error}
          </p>
        ) : null}
        <p className="text-[11px] text-muted-foreground">
          To samo pole co Profil Championa › Zespół.
        </p>
      </PopoverContent>
    </Popover>
  );
}
