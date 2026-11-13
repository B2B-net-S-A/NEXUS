"use client";

import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type { TrainingFileRow, TrainingHandoverItem } from "@/lib/api/trainings";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";

import { ToneBadge } from "./TrainingStatus";
import { HANDOVER_LABELS, HANDOVER_TONES, canReviewFile, formatBytes } from "./training-model";

interface HandoverReviewProps {
  items: TrainingHandoverItem[];
  canManage: boolean;
  onDownload: (file: TrainingFileRow) => void;
  onReview: (input: { fileId: number; accept: boolean; note: string }) => Promise<boolean>;
  busy?: boolean;
}

function dueText(days: number | null): string {
  if (days === null) return "termin do ustalenia";
  if (days === 0) return "w dniu szkolenia";
  return days === 1 ? "1 dzień po szkoleniu" : `${days} dni po szkoleniu`;
}

/** Pozycje Zał. 1 pkt 4: najnowszy plik każdej, przyjęcie albo zwrot z uwagą. */
export function HandoverReview({ items, canManage, onDownload, onReview, busy }: HandoverReviewProps) {
  const { askReason, confirmDialog } = useConfirmV2();

  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">Zamówienie nie ma plików do przekazania.</p>;
  }

  const returnFile = async (file: TrainingFileRow, label: string) => {
    const note = await askReason({
      title: `Zwróć do poprawy: ${label}`,
      description:
        "Trener dostanie uwagę i 3 dni robocze na poprawę (§ 11 ust. 4 umowy).",
      confirmLabel: "Zwróć do poprawy",
      field: { label: "Co poprawić", minLength: 3, maxLength: 2000 },
    });
    if (note) await onReview({ fileId: file.id, accept: false, note });
  };

  return (
    <ul className="divide-y divide-border">
      {confirmDialog}
      {items.map((item) => (
        <li key={item.key} className="py-3" data-testid={`handover-${item.key}`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground">
                {item.label}
                {item.required ? null : (
                  <span className="ml-1 text-xs font-normal text-muted-foreground">(opcjonalne)</span>
                )}
              </p>
              <p className="text-xs text-muted-foreground">
                {item.format || "format do ustalenia"} · {dueText(item.due_days)}
              </p>
            </div>
            <ToneBadge tone={HANDOVER_TONES[item.state]}>{HANDOVER_LABELS[item.state]}</ToneBadge>
          </div>
          {item.files.length > 0 ? (
            <ul className="mt-2 space-y-2">
              {item.files.map((file) => {
                const allowed = canReviewFile(item.state, file.status);
                return (
                  <li
                    key={file.id}
                    className="flex flex-wrap items-center gap-2 rounded-md bg-muted/50 px-3 py-2 text-sm"
                  >
                    <button
                      type="button"
                      className="inline-flex min-w-0 items-center gap-1.5 text-left text-primary hover:underline"
                      onClick={() => onDownload(file)}
                    >
                      <Download className="h-3.5 w-3.5 shrink-0" aria-hidden />
                      <span className="truncate">{file.file_name}</span>
                    </button>
                    <span className="text-xs text-muted-foreground">
                      {formatBytes(file.size_bytes)} · {formatDateTimePl(file.uploaded_at)}
                    </span>
                    {canManage ? (
                      <span className="ml-auto flex gap-1.5">
                        {allowed.accept ? (
                          <Button
                            size="sm"
                            disabled={busy}
                            onClick={() => onReview({ fileId: file.id, accept: true, note: "" })}
                          >
                            Przyjmij
                          </Button>
                        ) : null}
                        {allowed.return ? (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy}
                            onClick={() => returnFile(file, item.label)}
                          >
                            Zwróć do poprawy
                          </Button>
                        ) : null}
                      </span>
                    ) : null}
                    {file.status === "returned" && file.review_note ? (
                      <p className="w-full text-xs text-destructive-muted-foreground">
                        Uwaga: {file.review_note}
                        {file.fix_due_on ? ` · poprawa do ${formatIsoDatePl(file.fix_due_on)}` : ""}
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
