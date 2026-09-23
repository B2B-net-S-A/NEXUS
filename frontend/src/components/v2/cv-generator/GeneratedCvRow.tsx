"use client";

import type { GeneratedCvItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { classifyCvWarnings, contentModeLabel } from "@/lib/cv-generator";

import { formatCvListDate } from "./cv-generator-form";
import { StatusChip } from "./GeneratorParts";

/** „1 uwaga”, „2 uwagi”, „5 uwag”. */
export function remarksLabel(count: number): string {
  if (count === 1) return "1 uwaga";
  const lastTwo = count % 100;
  const last = count % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} uwagi`;
  return `${count} uwag`;
}

export interface GeneratedCvRowProps {
  item: GeneratedCvItem;
  /** Wersje językowe tego samego pakietu (drugi dokument „Obie”). */
  siblings?: readonly GeneratedCvItem[];
  now?: Date;
  onOpen: (item: GeneratedCvItem) => void;
  onRetry?: (item: GeneratedCvItem) => void;
  onSelectForRecruitment?: (item: { id: number; filename: string }) => void;
  /** Link dla klienta — tylko przy `CV_CLIENT_LINKS_UI_ENABLED` (dziś wyłączone). */
  onShare?: (item: GeneratedCvItem) => void;
  selected?: boolean;
}

/** Wiersz listy „Moje CV”. */
export function GeneratedCvRow({ item, siblings = [], now, onOpen, onRetry, onSelectForRecruitment, onShare, selected }: GeneratedCvRowProps) {
  const docs = [item, ...siblings];
  const languages = [...new Set(docs.map((doc) => doc.language.toUpperCase()))];
  const processing = docs.some((doc) => doc.status === "processing");
  const failed = item.status === "failed";
  const review = classifyCvWarnings(docs.flatMap((doc) => doc.warnings ?? [])).review.length;
  const consentMissing = docs.some((doc) => doc.consent_missing);
  const jobTitle = item.job_title ?? item.position ?? null;

  return (
    <tr className="align-top">
      <td className="px-3 py-3">
        <p className="font-medium text-foreground">{item.candidate_name}</p>
        {item.origin === "auto" ? (
          <p className="text-xs text-muted-foreground">automatycznie po weryfikacji</p>
        ) : item.job_id == null ? (
          <p className="text-xs text-muted-foreground">bez procesu</p>
        ) : null}
        {item.origin === "auto" && item.needs_review ? (
          <p className="mt-1">
            <StatusChip tone="warn">wygenerowane automatycznie — sprawdź przed wysyłką</StatusChip>
          </p>
        ) : null}
      </td>
      <td className="px-3 py-3">
        {jobTitle ? <p className="text-foreground">{jobTitle}</p> : null}
        <p className="text-xs text-muted-foreground">{item.client_name ?? "—"}</p>
      </td>
      <td className="px-3 py-3">
        <span className="flex flex-wrap gap-1">
          {languages.map((language) => (
            <StatusChip key={language} tone="neutral">{language}</StatusChip>
          ))}
        </span>
      </td>
      <td className="px-3 py-3 text-foreground">{contentModeLabel(item.content_mode)}</td>
      <td className="px-3 py-3">
        <span className="flex flex-wrap gap-1">
          {processing ? (
            <StatusChip tone="info">generuje się…</StatusChip>
          ) : failed ? (
            <StatusChip tone="danger">nie powstało — ponów</StatusChip>
          ) : review > 0 ? (
            <StatusChip tone="warn">{remarksLabel(review)}</StatusChip>
          ) : (
            <StatusChip tone="ok">bez uwag</StatusChip>
          )}
          {consentMissing && !failed ? <StatusChip tone="danger">brak zgody RODO</StatusChip> : null}
        </span>
      </td>
      <td className="whitespace-nowrap px-3 py-3 text-muted-foreground">{formatCvListDate(item.created_at, now)}</td>
      <td className="px-3 py-3 text-right">
        <span className="inline-flex flex-wrap justify-end gap-1">
          {onSelectForRecruitment && item.status === "ready" ? (
            <Button type="button" variant="outline" size="sm" disabled={!item.can_download} onClick={() => onSelectForRecruitment(item)}>
              {selected ? "Wybrano · wczytaj ponownie" : "Użyj w rekrutacji"}
            </Button>
          ) : null}
          {onShare && item.status === "ready" ? (
            <Button type="button" variant="outline" size="sm" disabled={!item.can_download || consentMissing} onClick={() => onShare(item)}>
              Udostępnij klientowi
            </Button>
          ) : null}
          {failed && onRetry ? (
            <Button type="button" variant="outline" size="sm" onClick={() => onRetry(item)}>Ponów</Button>
          ) : (
            <Button type="button" variant="outline" size="sm" onClick={() => onOpen(item)}>Otwórz</Button>
          )}
        </span>
      </td>
    </tr>
  );
}
