"use client";

// Poligon NEXUSA — onboarding pierwszego dnia (decyzje Artura z 14.11.2026).
// Ścieżka bez poziomów, per rola (15.11.2026: rekruter, Delivery Lead, TCM —
// `usePoligonPath`): nowa osoba przechodzi wszystkie ćwiczenia swojej roli, zanim
// NEXUS wpuści ją do pracy (blokada Startu prowadzi tu), a dzień onboardingu
// nie liczy się do jej statystyk. Ćwiczenia idą na prawdziwych ekranach
// w trybie poligonu (`lib/poligon/`), na rekrutacji ćwiczebnej.

import { CheckCircle2, Circle, Lock, PlayCircle, Target } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { useStartStatus } from "@/lib/novelties/api";
import { enterPoligon } from "@/lib/poligon/mode";
import { nextExerciseId, readDone, resetProgress } from "@/lib/poligon/progress";
import { usePoligonPath } from "@/lib/poligon/usePoligonPath";
import { cn } from "@/lib/utils";

export default function PoligonPage() {
  const [mounted, setMounted] = useState(false);
  const [done, setDone] = useState<Set<string>>(() => new Set());
  const status = useStartStatus(true);
  const poligon = status?.poligon ?? null;
  const serverIds = poligon?.done_ids;
  const { path, context } = usePoligonPath(poligon);

  useEffect(() => {
    setDone(readDone(serverIds ?? []));
    setMounted(true);
  }, [serverIds]);

  const modules = useMemo(() => {
    const byModule = new Map<string, (typeof path)[number][]>();
    for (const e of path) byModule.set(e.module, [...(byModule.get(e.module) ?? []), e]);
    return [...byModule.entries()];
  }, [path]);
  const nextId = nextExerciseId(done, path);
  const next = path.find((e) => e.id === nextId) ?? null;
  const doneCount = path.filter((e) => done.has(e.id)).length;
  const total = Math.max(path.length, 1);
  const required = Boolean(poligon?.required);
  const locked = required && Boolean(status?.enforced) && status?.redirect === "/poligon";

  return (
    <div className="mx-auto max-w-5xl space-y-5 pb-24">
      <header className="space-y-1">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-primary">
          <Target className="h-3.5 w-3.5" aria-hidden="true" />
          Poligon NEXUSA · onboarding
        </p>
        <h1 className="text-2xl font-semibold text-foreground">Naucz się NEXUSA na rekrutacji ćwiczebnej</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Pracujesz na prawdziwych ekranach, ale wszystkie osoby i firmy są wymyślone. Przeciągasz karty, piszesz
          notatki, odrzucasz, przypisujesz z bazy i robisz to, co należy do Twojej roli — nic nie trafia do bazy ani do
          klientów. Każde ćwiczenie zalicza się samo, kiedy je wykonasz.
        </p>
      </header>

      {required && (
        <p
          role="status"
          className={cn(
            "flex items-start gap-2 rounded-lg border px-4 py-3 text-sm",
            locked
              ? "border-warning/30 bg-warning-muted text-warning-muted-foreground"
              : "border-success/30 bg-success-muted text-success-muted-foreground",
          )}
        >
          {locked ? (
            <Lock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          ) : (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          )}
          <span>
            {locked ? (
              <>
                <b>To Twój pierwszy dzień.</b> Reszta NEXUSA otworzy się, kiedy przejdziesz wszystkie ćwiczenia. Dzień
                onboardingu nie liczy się do Twoich statystyk: weryfikacji, rekomendacji, celów ani Porcji dnia.
              </>
            ) : (
              <>
                <b>Onboarding zaliczony.</b> NEXUS jest otwarty, a dzień onboardingu nie liczy się do Twoich statystyk.
              </>
            )}
          </span>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-card px-4 py-3">
        <p className="text-sm">
          <b className="text-base font-semibold tabular-nums">
            {mounted ? doneCount : "–"} z {path.length}
          </b>{" "}
          <span className="text-muted-foreground">ćwiczeń</span>
        </p>
        <div className="h-1.5 min-w-[120px] flex-1 overflow-hidden rounded-full bg-accent" aria-hidden="true">
          <i className="block h-full bg-primary" style={{ width: `${(doneCount / total) * 100}%` }} />
        </div>
        {next ? (
          <Button onClick={() => enterPoligon(next.href)} disabled={!mounted}>
            <PlayCircle className="h-4 w-4" aria-hidden="true" />
            {doneCount === 0 ? "Zacznij onboarding" : `Wróć do ćwiczenia: ${next.module}`}
          </Button>
        ) : (
          <>
            <Button asChild>
              <Link href="/jobs">Przejdź do pracy</Link>
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                resetProgress();
                setDone(new Set());
              }}
            >
              Przejdź jeszcze raz
            </Button>
          </>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {modules.map(([module, exercises]) => {
          const moduleDone = exercises.filter((e) => done.has(e.id)).length;
          const current = exercises.some((e) => e.id === nextId);
          return (
            <section
              key={module}
              className={cn("overflow-hidden rounded-lg border border-border bg-card", current && "border-primary/40")}
            >
              <header className="flex items-center gap-2 border-b border-border px-4 py-2.5">
                {moduleDone === exercises.length ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-label="zaliczone" />
                ) : current ? (
                  <PlayCircle className="h-4 w-4 shrink-0 text-primary" aria-label="w toku" />
                ) : (
                  <Circle className="h-4 w-4 shrink-0 text-muted-foreground" aria-label="do zrobienia" />
                )}
                <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{module}</h2>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {mounted ? moduleDone : 0} z {exercises.length}
                </span>
              </header>
              <ul>
                {exercises.map((e) => (
                  <li
                    key={e.id}
                    className={cn(
                      "flex items-center gap-2.5 border-b border-border/70 px-4 py-2 text-[13px] last:border-b-0",
                      e.id === nextId && "bg-primary/5 font-medium",
                      done.has(e.id) && "text-muted-foreground",
                    )}
                  >
                    {done.has(e.id) ? (
                      <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" aria-label="zaliczone" />
                    ) : (
                      <Circle className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    )}
                    <span className="min-w-0 truncate">{e.title({ ...context, firstNew: null })}</span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
