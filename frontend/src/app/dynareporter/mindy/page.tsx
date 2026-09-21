"use client";

/**
 * MINDY została zastąpiona przez Jarvisa (0330) — asystenta dostępnego na
 * każdym ekranie NEXUSA (maskotka w rogu, ⌘J). Strona zostaje, bo link do
 * niej żyje w zakładkach przeglądarek; zamiast czatu wyjaśnia zmianę i otwiera
 * Jarvisa jednym kliknięciem.
 */

import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { openJarvis } from "@/lib/jarvis/events";

export default function MindyMovedPage() {
  return (
    <div className="mx-auto max-w-xl py-12">
      <div className="rounded-xl border border-border bg-card p-6 text-center shadow-xs">
        <Sparkles className="mx-auto h-8 w-8 text-primary" aria-hidden />
        <h1 className="mt-3 text-lg font-semibold text-foreground">MINDY jest teraz Jarvisem</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Asystent AI działa na każdym ekranie NEXUSA — kliknij maskotkę w prawym dolnym rogu albo naciśnij
          <kbd className="mx-1 rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">⌘J</kbd>.
          Odpowiada na pytania o kandydatów, rekrutacje, klientów i Twoje KPI, a zadania przygotowuje do
          Twojego zatwierdzenia.
        </p>
        <Button className="mt-5" onClick={() => openJarvis({ prompt: "Jak idą moje KPI w tym miesiącu?" })}>
          Otwórz Jarvisa
        </Button>
      </div>
    </div>
  );
}
