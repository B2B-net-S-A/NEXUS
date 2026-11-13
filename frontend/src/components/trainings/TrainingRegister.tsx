"use client";

import Link from "next/link";
import { FileDown, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PendingSignature, TrainerApplication, TrainingRow } from "@/lib/api/trainings";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { ToneBadge, TrainingStatusBadge } from "./TrainingStatus";
import { formatAmount } from "./training-model";

function paymentCell(row: TrainingRow): React.ReactNode {
  if (row.trainer_kind === "employee") {
    return <span className="text-xs text-muted-foreground">nie dotyczy</span>;
  }
  if (row.paid_at) return <ToneBadge tone="success">zapłacone</ToneBadge>;
  if (row.invoice_ready_at) return <ToneBadge tone="warning">faktura, termin 14 dni</ToneBadge>;
  return <span className="text-xs text-muted-foreground">—</span>;
}

function libraryCell(row: TrainingRow): React.ReactNode {
  if (row.published_at) return <ToneBadge tone="success">w bibliotece</ToneBadge>;
  if (row.can_publish) return <ToneBadge tone="info">do opublikowania</ToneBadge>;
  if (row.status === "signed" && row.trainer_kind === "consultant") {
    return <span className="text-xs text-muted-foreground">czeka na zapłatę</span>;
  }
  return <span className="text-xs text-muted-foreground">—</span>;
}

/** Rejestr „Organizuję”: kwoty tylko tam, gdzie serwer je zwrócił. */
export function TrainingRegister({ rows }: { rows: TrainingRow[] }) {
  const withAmounts = rows.some((row) => row.total !== null);
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="sticky left-0 bg-card px-4 py-2 font-medium">Szkolenie</th>
            <th className="px-3 py-2 font-medium">Trener</th>
            <th className="px-3 py-2 font-medium">Stan</th>
            {withAmounts ? <th className="px-3 py-2 text-right font-medium">Netto</th> : null}
            <th className="px-3 py-2 font-medium">Zapłata</th>
            <th className="px-3 py-2 font-medium">Biblioteka</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-border/60 last:border-0 hover:bg-muted/40">
              <td className="sticky left-0 max-w-[22rem] bg-card px-4 py-2">
                <Link href={`/trainings/${row.id}`} className="font-medium text-primary hover:underline">
                  {row.title}
                </Link>
                <span className="block text-xs text-muted-foreground">
                  {row.session_date ? formatIsoDatePl(row.session_date) : "termin do ustalenia"}
                </span>
              </td>
              <td className="px-3 py-2">
                {row.trainer_name || "—"}
                <span className="block text-xs text-muted-foreground">
                  {row.trainer_kind === "consultant" ? "konsultant B2B" : "pracownik"}
                </span>
              </td>
              <td className="px-3 py-2">
                <TrainingStatusBadge status={row.status} label={row.status_label} />
              </td>
              {withAmounts ? (
                <td className="px-3 py-2 text-right tabular-nums">
                  {row.total !== null ? formatAmount(Number(row.total)) : "—"}
                </td>
              ) : null}
              <td className="px-3 py-2">{paymentCell(row)}</td>
              <td className="px-3 py-2">{libraryCell(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ApplicationsProps {
  applications: TrainerApplication[];
  onDownloadSample: (application: TrainerApplication) => void;
}

/** Zgłoszenia trenerów z panelu konsultanta; „Zamów szkolenie” otwiera zamówienie z trenerem. */
export function TrainerApplications({ applications, onDownloadSample }: ApplicationsProps) {
  return (
    <ul className="space-y-3">
      {applications.map((application) => (
        <li key={application.id} className="rounded-lg border border-border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="font-medium text-foreground">{application.trainer_name || "—"}</p>
              <p className="text-xs text-muted-foreground">
                {application.email ?? "bez adresu"} · zgłoszenie {formatDateTimePl(application.sent_at)}
              </p>
            </div>
            <Link
              href={`/trainings/new?application=${application.id}`}
              className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              Zamów szkolenie
            </Link>
          </div>
          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            {application.proposal_title ? (
              <div>
                <dt className="text-xs text-muted-foreground">Propozycja</dt>
                <dd>
                  {application.proposal_title}
                  {application.proposal_hours ? ` · ${application.proposal_hours}` : ""}
                </dd>
              </div>
            ) : null}
            {application.topics.length > 0 ? (
              <div>
                <dt className="text-xs text-muted-foreground">Tematy</dt>
                <dd>{application.topics.join(", ")}</dd>
              </div>
            ) : null}
            {application.audience ? (
              <div>
                <dt className="text-xs text-muted-foreground">Dla kogo</dt>
                <dd>{application.audience}</dd>
              </div>
            ) : null}
            {application.availability ? (
              <div>
                <dt className="text-xs text-muted-foreground">Dostępność</dt>
                <dd>{application.availability}</dd>
              </div>
            ) : null}
            {application.experience ? (
              <div className="sm:col-span-2">
                <dt className="text-xs text-muted-foreground">Doświadczenie</dt>
                <dd className="whitespace-pre-line">{application.experience}</dd>
              </div>
            ) : null}
            {application.materials ? (
              <div className="sm:col-span-2">
                <dt className="text-xs text-muted-foreground">Materiały</dt>
                <dd className="whitespace-pre-line break-words">{application.materials}</dd>
              </div>
            ) : null}
          </dl>
          {application.sample_name ? (
            <button
              type="button"
              className="mt-2 text-sm text-primary hover:underline"
              onClick={() => onDownloadSample(application)}
            >
              Próbka materiałów: {application.sample_name}
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

interface PendingSignaturesProps {
  items: PendingSignature[];
  onDownload: (item: PendingSignature) => void;
  onSign: (item: PendingSignature, file: File) => Promise<boolean>;
  busy?: boolean;
}

/**
 * Umowy podpisane przez trenera, które czekają na podpis reprezentanta B2B
 * Network. Reprezentant nie musi widzieć karty (kwoty), więc pobiera i wgrywa tutaj.
 */
export function PendingSignatures({ items, onDownload, onSign, busy }: PendingSignaturesProps) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border bg-card">
      {items.map((item) => (
        <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
          <div className="min-w-0">
            <p className="font-medium text-foreground">{item.title}</p>
            <p className="text-xs text-muted-foreground">
              {item.number || "bez numeru"} · {item.trainer_name || "trener"} · trener podpisał{" "}
              {formatDateTimePl(item.trainer_signed_at)}
            </p>
          </div>
          <span className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => onDownload(item)}>
              <FileDown className="h-3.5 w-3.5" aria-hidden /> Pobierz do podpisu
            </Button>
            <label
              className={cn(
                "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90 focus-within:ring-2 focus-within:ring-ring",
                busy && "pointer-events-none opacity-50",
              )}
            >
              <Upload className="h-3.5 w-3.5" aria-hidden /> Wgraj podpisany PDF
              <input
                type="file"
                accept="application/pdf,.pdf"
                className="sr-only"
                disabled={busy}
                onChange={async (event) => {
                  const file = event.target.files?.[0];
                  if (file) await onSign(item, file);
                  event.target.value = "";
                }}
              />
            </label>
          </span>
        </li>
      ))}
    </ul>
  );
}
