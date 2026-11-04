"use client";

import { useState } from "react";
import { Copy, Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copyTextToClipboard } from "@/lib/clipboard";

import { signatureMailHref } from "./equipment-format";

interface ProtocolLinkBoxProps {
  url: string;
  number: string;
  email: string | null;
}

/**
 * Link do potwierdzenia odbioru. Adres pokazujemy tylko raz (w bazie jest jego
 * skrót) — recepcja kopiuje go albo otwiera gotową wiadomość w swojej poczcie.
 */
export function ProtocolLinkBox({ url, number, email }: ProtocolLinkBoxProps) {
  const [copied, setCopied] = useState<boolean | null>(null);
  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3 text-sm">
      <p className="font-medium">Link do potwierdzenia odbioru (ważny 14 dni, jednorazowy)</p>
      <div className="flex gap-2">
        <Input readOnly value={url} aria-label="Link do podpisu" className="h-9 font-mono text-xs" />
        <Button
          variant="outline"
          onClick={async () => setCopied(await copyTextToClipboard(url))}
        >
          <Copy className="h-4 w-4" aria-hidden />
          Kopiuj
        </Button>
        <Button variant="outline" asChild>
          <a href={signatureMailHref(email, number, url)}>
            <Mail className="h-4 w-4" aria-hidden />
            Otwórz w poczcie
          </a>
        </Button>
      </div>
      {copied === true ? <p className="text-xs text-muted-foreground">Skopiowano.</p> : null}
      {copied === false ? (
        <p role="alert" className="text-xs text-destructive">
          Nie udało się skopiować — zaznacz adres i skopiuj ręcznie.
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Ten adres zobaczysz tylko teraz. Gdy zginie, utwórz nowy link — poprzedni przestanie działać.
      </p>
    </div>
  );
}
