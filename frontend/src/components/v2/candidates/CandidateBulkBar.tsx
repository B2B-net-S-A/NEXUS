"use client";

import { Briefcase, ChevronDown, Download, FileArchive, GitCompare, Loader2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/** Porównanie mieści trzy osoby (`/candidates/compare`). */
export const COMPARE_LIMIT = 3;

export interface CandidateBulkBarProps {
  count: number;
  onAddToRecruitment: () => void;
  onCompare: () => void;
  onDownloadCvs: () => void;
  downloadingCvs: boolean;
  onAddToPool: () => void;
  addingToPool: boolean;
  /** `undefined` = rola bez prawa eksportu (lustro `CANDIDATE_EXPORT_ROLES`). */
  onExportSelected?: () => void;
  onClear: () => void;
}

/**
 * Pasek akcji zaznaczenia (makieta „Filtry", 22.09.2026): jedna główna akcja
 * („Dodaj do rekrutacji"), porównanie i reszta w „Więcej".
 */
export function CandidateBulkBar({
  count,
  onAddToRecruitment,
  onCompare,
  onDownloadCvs,
  downloadingCvs,
  onAddToPool,
  addingToPool,
  onExportSelected,
  onClear,
}: CandidateBulkBarProps) {
  if (count === 0) return null;
  const compareOverflow = Math.max(0, count - COMPARE_LIMIT);
  return (
    <div
      role="region"
      aria-label="Akcje zaznaczonych kandydatów"
      className="fixed bottom-5 left-1/2 z-40 flex -translate-x-1/2 animate-slide-in-bottom flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-foreground shadow-md"
    >
      <span className="text-sm">
        <span className="font-semibold">{count}</span> zaznaczonych
      </span>
      <span className="h-4 w-px bg-border" aria-hidden />
      <Button size="sm" variant="primary" onClick={onAddToRecruitment}>
        <Briefcase className="h-3.5 w-3.5" /> Dodaj do rekrutacji
      </Button>
      <div className="flex flex-col items-center">
        <Button
          size="sm"
          variant="outline"
          disabled={compareOverflow > 0}
          aria-describedby={compareOverflow > 0 ? "candidates-compare-limit" : undefined}
          onClick={() => {
            // Nadmiarowego zaznaczenia nie ucinamy po cichu — prosimy o odznaczenie.
            if (compareOverflow > 0) return;
            onCompare();
          }}
        >
          <GitCompare className="h-3.5 w-3.5" /> Porównaj
        </Button>
        {compareOverflow > 0 && (
          <span id="candidates-compare-limit" className="mt-0.5 text-[10px] text-muted-foreground">
            Maks. {COMPARE_LIMIT} — odznacz {compareOverflow}
          </span>
        )}
      </div>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="ghost">
            Więcej <ChevronDown className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuItem onSelect={onDownloadCvs} disabled={downloadingCvs}>
            {downloadingCvs ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FileArchive className="h-4 w-4" />
            )}
            Pobierz CV (ZIP)
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={onAddToPool} disabled={addingToPool}>
            <Users className="h-4 w-4" />
            Dodaj do puli
          </DropdownMenuItem>
          {onExportSelected && (
            <DropdownMenuItem onSelect={onExportSelected}>
              <Download className="h-4 w-4" />
              Eksportuj zaznaczone (CSV)
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <button
        type="button"
        onClick={onClear}
        className="ml-1 text-xs text-muted-foreground hover:text-foreground"
      >
        Odznacz
      </button>
    </div>
  );
}
