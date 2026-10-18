"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useClientTechMap } from "@/lib/api/care";
import { cn } from "@/lib/utils";

import { gapQuestion } from "./tech-gaps";

/**
 * „Do dopytania u klienta” w oknie rozmowy opieki (D16): luki mapy technologii
 * tego klienta jako pytania. Tylko podpowiedź — nic się samo nie zapisuje.
 * Mapa wczytuje się dopiero po rozwinięciu (liczy się z kilku źródeł).
 */
export function CareGapQuestions({ clientId }: { clientId: number | null }) {
  const [open, setOpen] = useState(false);
  const map = useClientTechMap(clientId ?? 0, open && clientId != null);
  if (clientId == null) return null;
  const questions = (map.data?.gaps ?? []).map(gapQuestion);
  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="mt-3 rounded-md border border-border/60"
    >
      <CollapsibleTrigger className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-sm font-medium text-foreground hover:bg-muted/50">
        <ChevronRight
          aria-hidden
          className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-90")}
        />
        Do dopytania u klienta
        {map.isSuccess ? (
          <span className="text-xs font-normal tabular-nums text-muted-foreground">
            {questions.length}
          </span>
        ) : null}
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t border-border/60 px-3 py-2">
        {map.isLoading ? (
          <p className="text-sm text-muted-foreground">Wczytywanie pytań…</p>
        ) : map.isError ? (
          <p role="alert" className="text-sm text-destructive">
            Nie udało się wczytać pytań z mapy technologii.
          </p>
        ) : questions.length ? (
          <ul className="space-y-1.5 text-sm" aria-label="Pytania z mapy technologii">
            {questions.map((item) => (
              <li key={item.key}>
                {item.question}
                <span className="block text-xs text-muted-foreground">
                  {item.subject} · {item.detail}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Mapa technologii tego klienta nie ma luk do dopytania.
          </p>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          Podpowiedź z mapy technologii klienta. Odpowiedzi wpisz w notatce albo w karcie
          technologicznej — stąd nic się nie zapisuje.
        </p>
      </CollapsibleContent>
    </Collapsible>
  );
}
