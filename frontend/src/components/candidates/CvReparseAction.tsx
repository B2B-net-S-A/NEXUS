"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import api, { extractErrorMsg } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

/**
 * „Odczytaj CV ponownie” — następny krok, gdy wgrane CV nie zasiliło profilu
 * (UAT B12). Kolejkuje tę samą ścieżkę co wgranie pliku; wynik pojawia się po
 * odczycie w tle, więc przycisk nie udaje, że dane są już w profilu.
 */
export function CvReparseAction({ candidateId }: { candidateId: number }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<"idle" | "sending" | "queued" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function reparse() {
    setState("sending");
    setError(null);
    try {
      await api.post(`/api/candidates/${candidateId}/cv/reparse`);
      setState("queued");
      // Odczyt trwa w tle; po chwili profil pobiera się ponownie.
      window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.detail(candidateId) });
      }, 30_000);
    } catch (e) {
      setError(extractErrorMsg(e));
      setState("error");
    }
  }

  if (state === "queued") {
    return (
      <span role="status" className="text-xs text-muted-foreground">
        Odczyt CV uruchomiony — dane pojawią się w profilu po jego zakończeniu.
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button size="sm" variant="outline" onClick={() => void reparse()} disabled={state === "sending"}>
        <RefreshCw className="h-3.5 w-3.5" />
        {state === "sending" ? "Uruchamiam…" : "Odczytaj CV ponownie"}
      </Button>
      {error && (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      )}
    </span>
  );
}
