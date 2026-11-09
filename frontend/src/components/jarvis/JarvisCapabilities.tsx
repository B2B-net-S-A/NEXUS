"use client";

/** Pusty panel: co Jarvis sprawdzi, co zapisze od razu, co przygotuje do kliknięcia, a czego nie zrobi.
 *  Lista przychodzi z `GET /api/jarvis/status` — z narzędzi TEJ roli. */

import { Check, Hand, MousePointerClick, Undo2 } from "lucide-react";
import type { JarvisCapabilities as Capabilities } from "@/lib/jarvis/types";

/** Przy wyłączonym Jarvisie status przychodzi z `capabilities: {}` — brakująca lista to pusta lista. */
export function hasAnyCapability(capabilities: Partial<Capabilities> | undefined): boolean {
  return Boolean(capabilities) && Object.values(capabilities ?? {}).some((items) => (items?.length ?? 0) > 0);
}

export function JarvisCapabilities({ capabilities }: { capabilities: Partial<Capabilities> }) {
  const groups = [
    { Icon: Check, title: "Sprawdzę od razu", items: capabilities.read ?? [] },
    { Icon: Undo2, title: "Zrobię od razu, gdy poprosisz — cofniesz przez 15 minut", items: capabilities.now ?? [] },
    { Icon: MousePointerClick, title: "Przygotuję — Ty klikasz „Zrób to”", items: capabilities.write ?? [] },
    { Icon: Hand, title: "Tego nie zrobię — pokażę, gdzie kliknąć", items: capabilities.never ?? [] },
  ].filter((g) => g.items.length > 0);

  return (
    <div className="space-y-2.5 text-left" data-testid="jarvis-capabilities">
      {groups.map(({ Icon, title, items }) => (
        <div key={title} className="rounded-lg border border-border px-3 py-2">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
            <Icon className="h-3.5 w-3.5 text-primary" aria-hidden />
            {title}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">{items.join(" · ")}</p>
        </div>
      ))}
      <p className="text-xs text-muted-foreground">
        Gdy czegoś nie umiem albo Twoja rola tego nie widzi, powiem, czego brakuje i co zrobić.
      </p>
    </div>
  );
}
