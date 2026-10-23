"use client";

/**
 * Nazwa rekrutacji, w której osoba już jest, tak jak w nagłówku rekrutacji
 * (zgłoszenie Artura, 16.10.2026): numer u klienta (`ClientReferenceChip`)
 * i tytuł dla rekrutera (`jobDisplayTitle`). Profil, szybki podgląd, lista
 * kandydatów, notatki i oś czasu pokazywały samą nazwę od klienta, więc
 * „AI Engineer (ZOB-2984)” nie dawało się połączyć z „ZOB-2984 Senior AI
 * Engineer · Java, LLM · 5+ lat” z nagłówka.
 *
 * Tylko ekrany wewnętrzne. Do klienta (CV, nazwa pliku, Cpro, maile) idzie
 * dalej `jobs.title` — pole `job_title` odpowiedzi nie zmienia znaczenia.
 */
import Link from "next/link";
import { useToast } from "@/components/Toast";
import { copyTextToClipboard } from "@/lib/clipboard";
import { jobClientTitle, jobDisplayTitle, type JobNames } from "@/lib/job-names";
import { cn } from "@/lib/utils";
import { ClientReferenceChip, copyClientReference } from "./ClientReferenceChip";

/**
 * Toast, gdy jest dostawca; bez niego (harnessy) numer kopiuje się bez
 * komunikatu. Przez `useToast`, nie `useOptionalToast`: makiety
 * `@/components/Toast` w testach ekranów, które montują ten wiersz, mają tylko
 * `useToast`. Hak woła się zawsze, więc kolejność haków się nie zmienia.
 */
export function useToastIfProvided(): ReturnType<typeof useToast> | null {
  try {
    return useToast() ?? null;
  } catch {
    return null;
  }
}

interface JobNameLabelProps {
  job: JobNames;
  /** Tytuł jako link do rekrutacji; numer stoi poza linkiem i tylko kopiuje. */
  href?: string;
  /**
   * Link przykrywa cały wiersz (wołający daje wierszowi `relative`), a numer
   * zostaje nad nim i dalej kopiuje — przycisk w `<a>` byłby niepoprawny.
   */
  stretched?: boolean;
  /** `false` = numer bez kopiowania, gdy cała nazwa stoi w innym przycisku. */
  copyable?: boolean;
  /** Długi tytuł łamie się pod numerem zamiast kończyć się wielokropkiem. */
  wrap?: boolean;
  className?: string;
  titleClassName?: string;
  /** `id` tytułu (np. dla `aria-labelledby` karty). */
  titleId?: string;
  testId?: string;
}

export function JobNameLabel({
  job,
  href,
  stretched = false,
  copyable = true,
  wrap = false,
  className,
  titleClassName,
  titleId,
  testId,
}: JobNameLabelProps) {
  const toast = useToastIfProvided();
  const title = jobDisplayTitle(job);
  const clientTitle = jobClientTitle(job);
  const onCopy = (reference: string) => {
    if (toast) void copyClientReference(reference, toast);
    else void copyTextToClipboard(reference);
  };
  const chip = (
    <ClientReferenceChip
      reference={job.client_reference}
      clientTitle={clientTitle}
      onCopy={copyable ? onCopy : undefined}
      testId="job-name-client-reference"
      className={cn(stretched && "relative z-[1]", wrap && "mr-1.5 align-text-bottom")}
    />
  );
  const name = href ? (
    <Link
      id={titleId}
      href={href}
      className={cn(
        "hover:underline",
        stretched && "after:absolute after:inset-0 focus-visible:outline-hidden",
        titleClassName,
      )}
    >
      {title}
    </Link>
  ) : (
    <span id={titleId} className={titleClassName}>
      {title}
    </span>
  );
  // Dymek na opakowaniu, nie na linku: `title` na `<a>` przejąłby jego nazwę
  // dostępną w Chrome.
  const tooltip = clientTitle ? `${title}\nNazwa u klienta: ${clientTitle}` : title;
  if (wrap) {
    return (
      <span className={cn("block min-w-0 break-words", className)} title={tooltip} data-testid={testId}>
        {chip}
        {name}
      </span>
    );
  }
  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)} data-testid={testId}>
      {chip}
      <span className="min-w-0 truncate" title={tooltip}>
        {name}
      </span>
    </span>
  );
}
