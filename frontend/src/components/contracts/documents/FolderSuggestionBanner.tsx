"use client";

import { Lightbulb } from "lucide-react";

import { Button } from "@/components/ui/button";
import { filesLabel, pluralForm, type FolderSuggestion } from "@/lib/contract-document-folders";

interface Props {
  suggestion: FolderSuggestion;
  currentNumber: string | null;
  readOnly: boolean;
  pending: boolean;
  onApply: () => void;
  onSelect: () => void;
  onDismiss: () => void;
}

/**
 * Podpowiedź „Poprzednia umowa” — numer innej umowy w nazwie pliku albo
 * wypowiedzenie przy aktywnej umowie. Niczego nie przenosi sama.
 */
export function FolderSuggestionBanner({
  suggestion,
  currentNumber,
  readOnly,
  pending,
  onApply,
  onSelect,
  onDismiss,
}: Props) {
  const count = suggestion.document_ids.length;
  return (
    <div
      role="status"
      className="mx-4 mb-3 flex items-start gap-3 rounded-lg border border-warning/25 bg-warning-muted px-4 py-3 text-sm text-warning-muted-foreground"
    >
      <Lightbulb className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="leading-relaxed">
          <strong className="font-semibold">
            {filesLabel(count)} {pluralForm(count, "wygląda", "wyglądają", "wygląda")} na poprzednią umowę nr{" "}
            {suggestion.number}.
          </strong>{" "}
          {currentNumber && <>Bieżąca umowa tego kontraktu ma nr {currentNumber}. </>}
          Rozpoznane po numerze umowy w nazwie pliku albo po wypowiedzeniu przy aktywnej umowie —
          sprawdź listę, zanim przeniesiesz.
        </p>
        {!readOnly && (
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" loading={pending} onClick={onApply}>
              Przenieś do folderu „{suggestion.folder_name}”
            </Button>
            <Button size="sm" variant="outline" onClick={onSelect}>
              Zaznacz te pliki
            </Button>
            <Button size="sm" variant="ghost" onClick={onDismiss}>
              Nie teraz
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
