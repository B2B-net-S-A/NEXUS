"use client";

import { Copy } from "lucide-react";
import { useToast } from "@/components/Toast";
import { copyTextToClipboard } from "@/lib/clipboard";

interface CopyValueButtonProps {
  value: string;
  /** Co kopiujemy, w bierniku: „adres e-mail”, „numer telefonu”. */
  what: string;
}

/**
 * Ikona „kopiuj” obok e-maila i telefonu w „Kontaktach klienta” (prośba DL
 * 17.11.2026: „jak przy kandydatach”). Wygląd i komunikaty jak w nagłówku
 * profilu kandydata, ale wynik schowka sprawdzany, nie zakładany.
 */
export function CopyValueButton({ value, what }: CopyValueButtonProps) {
  const { showSuccess, showError } = useToast();
  const copy = async () => {
    if (await copyTextToClipboard(value)) {
      showSuccess(`Skopiowano ${what}`);
    } else {
      showError(`Nie udało się skopiować — zaznacz ${what} i skopiuj ręcznie.`);
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`Kopiuj ${what}`}
      title={`Kopiuj ${what}`}
      className="inline-flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground pointer-coarse:size-10"
    >
      <Copy className="size-3.5" aria-hidden />
    </button>
  );
}
