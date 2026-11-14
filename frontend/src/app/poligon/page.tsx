"use client";

// Poligon NEXUSA — mapa ćwiczeń (decyzja Artura z 14.11.2026). Ćwiczenia idą
// na prawdziwych ekranach w trybie poligonu (`lib/poligon/`), na rekrutacji
// ćwiczebnej z wymyślonymi osobami. P1: poziom 1; poziomy 2–3 w kolejnych etapach.

import { CheckCircle2, Circle, Lock, PlayCircle, Target } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { LEVEL_1 } from "@/lib/poligon/exercises";
import { enterPoligon } from "@/lib/poligon/mode";
import { nextExerciseId, readDone, resetProgress } from "@/lib/poligon/progress";
import { cn } from "@/lib/utils";

const LATER_LEVELS = [
  {
    title: "Poziom 2 · Proces",
    when: "Tydzień 1",
    modules: ["Bramki etapów: QC CV i Cpro", "Screening: formularz i „Stawka od”", "Kandydaci do dodania i baza", "Generator CV pod klienta"],
  },
  {
    title: "Poziom 3 · Zaawansowane",
    when: "Do końca miesiąca",
    modules: ["Profil Championa", "Bliźniacze i podobne rekrutacje", "Moi ludzie i Talent Radar", "Zespół: @wzmianki, czat, przekazania"],
  },
];

export default function PoligonPage() {
  const [mounted, setMounted] = useState(false);
  const [done, setDone] = useState<Set<string>>(() => new Set());
  useEffect(() => {
    setDone(readDone());
    setMounted(true);
  }, []);

  const modules = useMemo(() => {
    const byModule = new Map<string, typeof LEVEL_1[number][]>();
    for (const e of LEVEL_1) byModule.set(e.module, [...(byModule.get(e.module) ?? []), e]);
    return [...byModule.entries()];
  }, []);
  const nextId = nextExerciseId(done);
  const next = LEVEL_1.find((e) => e.id === nextId) ?? null;
  const doneCount = LEVEL_1.filter((e) => done.has(e.id)).length;

  return (
    <div className="mx-auto max-w-5xl space-y-5 pb-24">
      <header className="space-y-1">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-primary">
          <Target className="h-3.5 w-3.5" aria-hidden="true" />
          Poligon NEXUSA
        </p>
        <h1 className="text-2xl font-semibold text-foreground">Naucz się NEXUSA na rekrutacji ćwiczebnej</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Pracujesz na prawdziwych ekranach, ale wszystkie osoby i firmy są wymyślone. Przeciągasz karty, odrzucasz,
          piszesz notatki — nic nie trafia do bazy ani do klientów. Każde ćwiczenie zalicza się samo, kiedy je wykonasz.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-card px-4 py-3">
        <p className="text-sm">
          <b className="text-base font-semibold tabular-nums">
            {mounted ? doneCount : "–"} z {LEVEL_1.length}
          </b>{" "}
          <span className="text-muted-foreground">ćwiczeń poziomu 1</span>
        </p>
        <div className="h-1.5 min-w-[120px] flex-1 overflow-hidden rounded-full bg-accent" aria-hidden="true">
          <i className="block h-full bg-primary" style={{ width: `${(doneCount / LEVEL_1.length) * 100}%` }} />
        </div>
        {next ? (
          <Button onClick={() => enterPoligon(next.href)} disabled={!mounted}>
            <PlayCircle className="h-4 w-4" aria-hidden="true" />
            {doneCount === 0 ? "Zacznij poziom 1" : `Wróć do ćwiczenia: ${next.module}`}
          </Button>
        ) : (
          <Button
            variant="outline"
            onClick={() => {
              resetProgress();
              setDone(new Set());
            }}
          >
            Przejdź poziom 1 jeszcze raz
          </Button>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <section className="overflow-hidden rounded-lg border border-border bg-card">
          <header className="border-b border-border px-4 py-2.5">
            <h2 className="text-sm font-semibold">Poziom 1 · Podstawy</h2>
            <p className="text-xs text-muted-foreground">Dzień 1 · {next ? "do zaliczenia przed pracą" : "zaliczony ✓"}</p>
          </header>
          <ul>
            {modules.map(([module, exercises]) => {
              const moduleDone = exercises.filter((e) => done.has(e.id)).length;
              const current = exercises.some((e) => e.id === nextId);
              return (
                <li key={module} className={cn("flex items-center gap-3 border-b border-border/70 px-4 py-2.5 last:border-b-0", current && "bg-primary/5")}>
                  {moduleDone === exercises.length ? (
                    <CheckCircle2 className="h-5 w-5 shrink-0 text-success" aria-label="zaliczone" />
                  ) : current ? (
                    <PlayCircle className="h-5 w-5 shrink-0 text-primary" aria-label="w toku" />
                  ) : (
                    <Circle className="h-5 w-5 shrink-0 text-muted-foreground" aria-label="do zrobienia" />
                  )}
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-medium">{module}</p>
                    <p className="text-xs text-muted-foreground">
                      {mounted ? moduleDone : 0} z {exercises.length} · {exercises.map((e) => e.title({ firstNew: null })).join(" · ")}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
        {LATER_LEVELS.map((level) => (
          <section key={level.title} className="overflow-hidden rounded-lg border border-border bg-card opacity-75">
            <header className="border-b border-border px-4 py-2.5">
              <h2 className="text-sm font-semibold">{level.title}</h2>
              <p className="text-xs text-muted-foreground">{level.when} · ćwiczenia w przygotowaniu</p>
            </header>
            <ul>
              {level.modules.map((m) => (
                <li key={m} className="flex items-center gap-3 border-b border-border/70 px-4 py-2.5 last:border-b-0">
                  <Lock className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <p className="truncate text-[13px] text-muted-foreground">{m}</p>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
