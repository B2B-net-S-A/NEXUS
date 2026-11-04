/**
 * Nazwa rekrutacji w oknach wyboru („Przypisz do rekrutacji”, `JobPicker`,
 * „Pasuje też do”) — tak jak w nagłówku rekrutacji: numer u klienta i tytuł
 * dla rekrutera. Zgłoszenie 16.10.2026: okno pokazywało nazwę od klienta
 * („AI Engineer (ZOB-2984)”), a rekrutacja nazywa się „Senior AI Engineer ·
 * Java, LLM · 5+ lat”.
 *
 * Numer jest tu etykietą, nie przyciskiem kopiowania jak `ClientReferenceChip`:
 * wiersz wyboru bywa sam przyciskiem, a klik w wiersz wybiera rekrutację.
 * Nazwa od klienta i wszystkie numery stoją w dymku.
 */
import {
  clientReferenceParts,
  jobClientTitle,
  jobDisplayTitle,
  type JobNames,
} from "@/lib/job-names";
import { cn } from "@/lib/utils";

/** Numer u klienta jako etykieta; kilka numerów = pierwszy i „+N”. */
export function ClientReferenceTag({
  reference,
  className,
}: {
  reference: string | null | undefined;
  className?: string;
}) {
  const parts = clientReferenceParts(reference);
  if (parts.length === 0) return null;
  return (
    <span
      data-testid="client-reference-tag"
      className={cn(
        "inline-flex h-5 max-w-[11rem] shrink-0 items-center gap-1 rounded-md border border-border bg-muted px-1.5 text-xs font-semibold tabular-nums text-foreground",
        className,
      )}
    >
      <span className="min-w-0 truncate">{parts[0]}</span>
      {parts.length > 1 ? (
        <span className="shrink-0 font-medium text-muted-foreground">+{parts.length - 1}</span>
      ) : null}
    </span>
  );
}

export function jobPickTooltip(job: JobNames): string {
  const clientTitle = jobClientTitle(job);
  const references = clientReferenceParts(job.client_reference);
  return [
    jobDisplayTitle(job),
    clientTitle ? `Nazwa u klienta: ${clientTitle}` : null,
    references.length > 0 ? `Numer u klienta: ${references.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join("\n");
}

export function JobPickName({ job, className }: { job: JobNames; className?: string }) {
  return (
    <span
      data-testid="job-pick-name"
      title={jobPickTooltip(job)}
      className={cn("flex min-w-0 items-center gap-1.5", className)}
    >
      <ClientReferenceTag reference={job.client_reference} />
      <span className="min-w-0 truncate font-medium text-foreground">{jobDisplayTitle(job)}</span>
    </span>
  );
}
