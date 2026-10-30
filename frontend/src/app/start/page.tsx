"use client";

// Start w NEXUSIE (decyzja Artura 30.10.2026): lista przeklikań najważniejszych
// funkcji roli. Dopóki nie ma kompletu, `useStartGate` wpuszcza osobę tylko
// tutaj i na pulpit. Przeklikanie idzie po prawdziwym ekranie (`NoveltyLayer`),
// a po ostatnim kroku blokada odsyła z powrotem na tę listę.

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { startNoveltyTour } from "@/components/novelties/NoveltyLayer";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { startKey } from "@/lib/novelties/api";
import type { StartStatus } from "@/lib/novelties/logic";

export default function StartPage() {
  const router = useRouter();
  // Lista z pamięci zapytań jest w kliencie od pierwszego renderu, a serwer
  // renderuje „Ładowanie…” — bez tego hydracja się nie zgadza.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const query = useQuery({
    queryKey: startKey,
    queryFn: async () => (await api.get<StartStatus>("/api/novelties/start")).data,
  });

  const begin = (id: string, href: string) => {
    startNoveltyTour(id);
    router.push(href);
  };

  return (
    // `pb-40`: dymek „Moich ludzi” w rogu nie może zasłonić ostatniego „Przeklikaj”.
    <div className="mx-auto max-w-3xl space-y-5 pb-40">
      <header className="space-y-1">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-primary">
          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          Start w NEXUSIE
        </p>
        <h1 className="text-2xl font-semibold text-foreground">
          Przeklikaj najważniejsze funkcje swojej pracy
        </h1>
        <p className="text-sm text-muted-foreground">
          Każde przeklikanie to kilka kliknięć na prawdziwym ekranie. Dopóki nie
          przejdziesz wszystkich, NEXUS pokaże Ci tylko pulpit i tę listę.
        </p>
      </header>

      {!mounted || query.isPending ? (
        <p className="text-sm text-muted-foreground">Ładowanie…</p>
      ) : query.isError ? (
        <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {apiErrorMessage(query.error, "Nie udało się wczytać listy Startu.")}
        </p>
      ) : query.data.total === 0 ? (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          W Twojej roli nie ma nic do przeklikania.{" "}
          <Link href="/" className="font-semibold text-primary hover:underline">
            Przejdź do pulpitu
          </Link>
        </p>
      ) : (
        <StartList status={query.data} onBegin={begin} />
      )}
    </div>
  );
}

function StartList({
  status,
  onBegin,
}: {
  status: StartStatus;
  onBegin: (id: string, href: string) => void;
}) {
  const complete = status.done === status.total;
  const percent = Math.round((status.done / status.total) * 100);
  return (
    <section className="space-y-3" aria-label="Przeklikania Startu">
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between text-sm">
          <span className="font-semibold text-foreground">
            {complete ? "Gotowe — masz komplet" : `${status.done} z ${status.total}`}
          </span>
          {complete ? (
            <Link href="/" className="font-semibold text-primary hover:underline">
              Przejdź do pulpitu
            </Link>
          ) : null}
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
        </div>
      </div>

      <ol className="space-y-2">
        {status.items.map((item) => (
          <li
            key={item.id}
            className="flex items-start gap-3 rounded-lg border border-border bg-card p-4"
            data-testid="start-item"
          >
            {item.done ? (
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" aria-label="Przeklikane" />
            ) : (
              <Circle className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" aria-label="Do przeklikania" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-foreground">{item.title}</p>
              <p className="mt-0.5 text-sm text-muted-foreground">{item.why}</p>
              <p className="mt-1 text-xs text-muted-foreground">{item.where}</p>
            </div>
            {item.done ? null : (
              <Button size="sm" onClick={() => onBegin(item.id, item.href)}>
                Przeklikaj
              </Button>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
