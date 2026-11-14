"use client";

// Warstwa Poligonu na prawdziwych ekranach: pasek „to jest poligon” w treści
// strony i panel ćwiczenia w rogu. Ćwiczenie zalicza klik w kotwicę albo
// zdarzenie z rekrutacji ćwiczebnej (`lib/poligon/store.ts`).

import { CheckCircle2, CircleAlert, Lightbulb, Target } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { anchorSelector } from "@/lib/novelties/logic";
import { onPoligonAction } from "@/lib/poligon/adapter";
import { LEVEL_1, type Exercise, type ExerciseContext } from "@/lib/poligon/exercises";
import { leavePoligon } from "@/lib/poligon/mode";
import { markDone, nextExerciseId, readDone } from "@/lib/poligon/progress";
import { cn } from "@/lib/utils";

import meta from "@/lib/poligon/meta.json";

const CONTEXT: ExerciseContext = {
  firstNew: meta.people[0]
    ? { candidateId: meta.people[0].candidate_id, fullName: `${meta.people[0].name} ${meta.people[0].lastname}` }
    : null,
};

/** Pasek nad treścią strony: przypomina, że dane są wymyślone. */
export function PoligonBanner() {
  return (
    <div
      role="status"
      className="sticky top-0 z-30 -mx-4 -mt-4 mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-warning/30 bg-warning-muted px-4 py-2 text-sm text-warning-muted-foreground md:-mx-6 md:-mt-6 md:mb-6 md:px-6"
    >
      <Target className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <b className="font-semibold">Poligon</b> · rekrutacja ćwiczebna — osoby i firmy są wymyślone, nic nie trafia do bazy ani do klienta
      </span>
      <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
        Od nowa
      </Button>
      <Button size="sm" variant="outline" onClick={() => leavePoligon()}>
        Wyjdź z poligonu
      </Button>
    </div>
  );
}

function pathOf(href: string): string {
  return href.split("?")[0];
}

function useAnchorRect(anchor: string | null, active: boolean): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null);
  useEffect(() => {
    if (!anchor || !active) {
      setRect(null);
      return;
    }
    const measure = () => {
      const el = Array.from(document.querySelectorAll<HTMLElement>(anchorSelector(anchor))).find((e) => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight;
      });
      setRect(el ? el.getBoundingClientRect() : null);
    };
    measure();
    const id = window.setInterval(measure, 400);
    return () => window.clearInterval(id);
  }, [anchor, active]);
  return rect;
}

type Phase = { kind: "task"; feedback?: string } | { kind: "done" };

export function PoligonLayer() {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const [done, setDone] = useState<Set<string>>(() => new Set());
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "task" });
  const [showMe, setShowMe] = useState(false);

  useEffect(() => {
    const initial = readDone();
    setDone(initial);
    setCurrentId(nextExerciseId(initial));
  }, []);

  const exercise: Exercise | null = useMemo(() => LEVEL_1.find((e) => e.id === currentId) ?? null, [currentId]);
  const index = exercise ? LEVEL_1.indexOf(exercise) : LEVEL_1.length;
  const onScreen = exercise ? pathname === pathOf(exercise.href) || pathname.startsWith(`${pathOf(exercise.href)}/`) : false;

  const complete = useCallback(
    (ex: Exercise) => {
      setDone(markDone(ex.id));
      setPhase({ kind: "done" });
      setShowMe(false);
    },
    [],
  );

  // Klik w kotwicę ćwiczenia.
  useEffect(() => {
    if (!exercise?.doneOnClick || phase.kind !== "task") return;
    const onClick = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (target?.closest(anchorSelector(exercise.anchor))) complete(exercise);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [exercise, phase.kind, complete]);

  // Zdarzenia z rekrutacji ćwiczebnej.
  useEffect(() => {
    if (!exercise?.judge || phase.kind !== "task") return;
    return onPoligonAction((action) => {
      const verdict = exercise.judge?.(action, CONTEXT);
      if (!verdict) return;
      if (verdict.done) complete(exercise);
      else setPhase({ kind: "task", feedback: verdict.feedback });
    });
  }, [exercise, phase.kind, complete]);

  const rect = useAnchorRect(exercise?.anchor ?? null, showMe && phase.kind === "task");

  const goNext = () => {
    const nextId = nextExerciseId(done);
    setCurrentId(nextId);
    setPhase({ kind: "task" });
    const next = LEVEL_1.find((e) => e.id === nextId);
    if (next && !(pathname === pathOf(next.href) || pathname.startsWith(`${pathOf(next.href)}/`))) router.push(next.href);
  };

  return (
    <>
      {rect && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed z-[70] rounded-lg ring-2 ring-primary ring-offset-2 ring-offset-background transition-all"
          style={{ left: rect.left - 4, top: rect.top - 4, width: rect.width + 8, height: rect.height + 8 }}
        />
      )}
      <section
        aria-label="Ćwiczenie na poligonie"
        className="fixed bottom-28 right-5 z-[60] w-[340px] max-w-[calc(100vw-2.5rem)] overflow-hidden rounded-xl border border-border bg-card text-sm text-foreground shadow-lg"
      >
        <header className="flex items-center gap-2 border-b border-border px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          <Target className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">
            Poligon · {exercise ? `${exercise.module} · ćwiczenie ${index + 1} z ${LEVEL_1.length}` : "poziom 1"}
          </span>
          <span className="flex gap-0.5" aria-hidden="true">
            {LEVEL_1.map((e) => (
              <i
                key={e.id}
                className={cn(
                  "h-1 w-3 rounded-full",
                  done.has(e.id) ? "bg-success" : e.id === currentId ? "bg-primary" : "bg-border",
                )}
              />
            ))}
          </span>
        </header>

        {!exercise ? (
          <div className="space-y-3 px-4 py-3">
            <p className="flex items-start gap-2 rounded-lg bg-success-muted px-3 py-2 text-success-muted-foreground">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                <b>Poziom 1 zaliczony.</b> Umiesz już poruszać się po rekrutacjach, prowadzić osoby na Tablicy i pisać notatki.
              </span>
            </p>
            <Button className="w-full" onClick={() => leavePoligon()}>
              Wróć na mapę poligonu
            </Button>
          </div>
        ) : phase.kind === "done" ? (
          <div className="space-y-2 px-4 py-3">
            <p className="flex items-start gap-2 rounded-lg bg-success-muted px-3 py-2 text-success-muted-foreground">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                <b>Zaliczone.</b> {exercise.title(CONTEXT)}.
              </span>
            </p>
            <p className="flex items-start gap-2 rounded-lg bg-primary/5 px-3 py-2">
              <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              <span>
                <b>Dobra praktyka:</b> {exercise.tip}
              </span>
            </p>
            <div className="flex justify-end pt-1">
              <Button size="sm" onClick={goNext}>
                {nextExerciseId(done) ? "Dalej →" : "Zakończ poziom 1"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-2 px-4 py-3">
            <h2 className="text-[15px] font-semibold leading-snug">{exercise.title(CONTEXT)}</h2>
            <p className="text-muted-foreground">{exercise.task(CONTEXT)}</p>
            {phase.feedback && (
              <p role="alert" className="flex items-start gap-2 rounded-lg bg-destructive-muted px-3 py-2 text-destructive-muted-foreground">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{phase.feedback}</span>
              </p>
            )}
            <div className="flex items-center gap-2 pt-1">
              {onScreen ? (
                <Button size="sm" variant="outline" onClick={() => setShowMe((v) => !v)}>
                  {showMe ? "Ukryj podpowiedź" : "Pokaż mi"}
                </Button>
              ) : (
                <Button size="sm" onClick={() => router.push(exercise.href)}>
                  Przejdź do ćwiczenia
                </Button>
              )}
              <span className="text-xs text-muted-foreground">{showMe && !rect && onScreen ? exercise.hint : "Zaliczy się samo"}</span>
            </div>
          </div>
        )}
      </section>
    </>
  );
}
