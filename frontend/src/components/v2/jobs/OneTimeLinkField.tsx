"use client";

/**
 * Pole z adresem linku, którego sekret serwer zwraca JEDEN raz.
 *
 * Linki do karty Championa i do CV niosą tokeny v2: w bazie zostaje wyłącznie
 * skrót, więc po zamknięciu odpowiedzi adresu nie da się już odtworzyć. Samo
 * „skopiowano" w toaście nie wystarcza — zapis do schowka potrafi się nie
 * udać (patrz `copyTextToClipboard`), a wtedy żywy, wielodniowy link istnieje
 * i nikt nie zna jego adresu. Adres jest więc zawsze WIDOCZNY i zaznaczalny,
 * a przycisk kopiowania mówi prawdę o wyniku.
 */

import { useId } from "react";
import { Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { copyTextToClipboard } from "@/lib/clipboard";

export interface OneTimeLinkFieldProps {
  url: string;
  label: string;
  /** Zdanie pod polem — np. ile dni link jest ważny. */
  note?: string;
  /** Wołane WYŁĄCZNIE po udanym zapisie do schowka. */
  onCopied?: () => void;
}

export function OneTimeLinkField({ url, label, note, onCopied }: OneTimeLinkFieldProps) {
  const inputId = useId();
  const { showSuccess, showError } = useToast();

  return (
    <div className="space-y-1">
      <label htmlFor={inputId} className="text-[11px] font-medium text-foreground">
        {label}
      </label>
      <div className="flex items-center gap-1.5">
        <input
          id={inputId}
          readOnly
          value={url}
          onFocus={(e) => e.currentTarget.select()}
          className="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted/30 px-2 text-[11px] text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary"
        />
        <Button
          size="sm"
          variant="outline"
          className="shrink-0"
          onClick={async () => {
            if (await copyTextToClipboard(url)) {
              showSuccess("Link skopiowany.");
              onCopied?.();
            } else {
              showError(
                "Nie udało się skopiować linku — zaznacz adres w polu i skopiuj go ręcznie.",
              );
            }
          }}
        >
          <Copy className="h-3.5 w-3.5" /> Kopiuj
        </Button>
      </div>
      {note ? (
        <p className="text-[10.5px] text-muted-foreground">{note}</p>
      ) : null}
    </div>
  );
}
