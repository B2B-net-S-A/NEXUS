"use client";

/**
 * JobSummaryCard — sekcja „Zlecenie" kroku 02 „Zlecenie i Champion" (program
 * „flow w języku C2", PR 5/7).
 *
 * Read-only skrót podstawowych pól zlecenia, nad sześcioma sekcjami Profilu
 * Championa. Świadomie NIE dubluje `EditJobModal` (ten formularz ma ~18 pól:
 * tytuł, klient, Program/Train, typ, status, opis, wymagania, lokalizacja,
 * remote, widełki, budżet PLN/h, priorytet, deadline, rekruter, owner TAC,
 * DL, hiring manager, szablon procesu, kategoria, auto-CC) — pokazuje tylko
 * pola identyfikujące zlecenie (jak w makiecie kroku 02), a „Edytuj" otwiera
 * TEN SAM modal, który już renderuje strona (nie tworzy drugiej instancji).
 */

import { PencilLine } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils";
import { RECRUITMENT_TYPE_LABEL } from "@/lib/recruitment-type";

export interface JobSummaryCardJob {
  title: string;
  client_name?: string | null;
  recruitment_type?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  location?: string | null;
  deadline?: string | null;
}

interface JobSummaryCardProps {
  job: JobSummaryCardJob;
  /** `undefined` chowa przycisk „Edytuj" (RBAC — mirror `canWritePipeline && canUpdateJob`). */
  onEdit?: () => void;
}

// `salary_min/max` to WYNAGRODZENIE Z OFERTY (formularz `EditJobModal`
// podpisuje je „Wynagrodzenie min/max (PLN/mies.)"), nie widełki klienta —
// stawka klienta żyje na kontraktach (`rate_client`). Jednostka za formularzem.
function formatSalaryRange(min?: number | null, max?: number | null): string {
  if (min == null && max == null) return "—";
  const fmt = (n: number) => n.toLocaleString("pl-PL");
  if (min != null && max != null) return `${fmt(min)}–${fmt(max)} PLN/mies.`;
  if (min != null) return `od ${fmt(min)} PLN/mies.`;
  return `do ${fmt(max as number)} PLN/mies.`;
}

export function JobSummaryCard({ job, onEdit }: JobSummaryCardProps) {
  const fields: Array<{ label: string; value: string }> = [
    { label: "Tytuł", value: job.title?.trim() || "—" },
    { label: "Klient", value: job.client_name?.trim() || "—" },
    {
      label: "Typ",
      value: job.recruitment_type
        ? (RECRUITMENT_TYPE_LABEL[job.recruitment_type] ?? job.recruitment_type)
        : "—",
    },
    {
      label: "Wynagrodzenie (z oferty)",
      value: formatSalaryRange(job.salary_min, job.salary_max),
    },
    { label: "Lokalizacja", value: job.location?.trim() || "—" },
    { label: "Deadline", value: formatDate(job.deadline) },
  ];

  return (
    <section
      className="rounded-xl border border-border bg-card p-4"
      data-testid="job-summary-card"
    >
      <header className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
          Zlecenie
        </h3>
        {onEdit ? (
          <Button type="button" variant="outline" size="sm" onClick={onEdit}>
            <PencilLine className="h-3.5 w-3.5" /> Edytuj
          </Button>
        ) : null}
      </header>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {fields.map((field) => (
          <div key={field.label} className="min-w-0">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {field.label}
            </dt>
            <dd className="truncate text-sm text-foreground" title={field.value}>
              {field.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
