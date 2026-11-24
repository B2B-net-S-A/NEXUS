"use client";

// Warstwa Poligonu na prawdziwych ekranach: pasek „to jest poligon” w treści
// strony i panel ćwiczenia w rogu. Ćwiczenie zalicza klik w kotwicę albo
// zdarzenie z rekrutacji ćwiczebnej (`lib/poligon/store.ts`).

import { CheckCircle2, ChevronDown, ChevronUp, CircleAlert, Download, Lightbulb, Target } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { anchorSelector, keepDialogsOpen } from "@/lib/novelties/logic";
import { onPoligonAction } from "@/lib/poligon/adapter";
import { useStartStatus } from "@/lib/novelties/api";
import type { Exercise } from "@/lib/poligon/exercises";
import { leavePoligon } from "@/lib/poligon/mode";
import { flushProgress, markDone, nextExerciseId, readDone } from "@/lib/poligon/progress";
import { usePoligonPath } from "@/lib/poligon/usePoligonPath";
import { cn } from "@/lib/utils";

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

function modulesText(path: readonly Exercise[]): string {
  return [...new Set(path.map((e) => e.module))].join(", ").toLowerCase();
}

function pathOf(href: string): string {
  return href.split("?")[0];
}

/** Kotwica widoczna w oknie przeglądarki (z kilku elementów — pierwszy widoczny). */
function visibleAnchor(anchor: string): HTMLElement | null {
  return (
    Array.from(document.querySelectorAll<HTMLElement>(anchorSelector(anchor))).find((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight;
    }) ?? null
  );
}

function useAnchorRect(anchor: string | null, active: boolean): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null);
  useEffect(() => {
    if (!anchor || !active) {
      setRect(null);
      return;
    }
    const measure = () => {
      const el = visibleAnchor(anchor);
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
  const [leaving, setLeaving] = useState(false);
  // Zwinięte okno zostawia sam pasek postępu — na laptopie 1280×720 zasłania mniej Tablicy.
  const [collapsed, setCollapsed] = useState(false);
  const status = useStartStatus(true);
  const serverIds = status?.poligon?.done_ids;
  const { path, context: CONTEXT } = usePoligonPath(status?.poligon);
  // Ze statystyk wypada tylko dzień onboardingu nowej osoby (`onboarding_day`).
  // Serwer daje `luki` wyłącznie osobie bez takiego wymogu, a dzień ćwiczeń
  // z luk się liczy (24.11.2026: osoba z luk czytała „dziś nie liczy się”).
  const onboardingDay = status?.poligon?.required === true && !status.poligon.luki;

  useEffect(() => {
    const initial = readDone(serverIds ?? []);
    setDone(initial);
    setCurrentId((current) =>
      current && !initial.has(current) && path.some((e) => e.id === current) ? current : nextExerciseId(initial, path),
    );
  }, [serverIds, path]);

  const exercise: Exercise | null = useMemo(() => path.find((e) => e.id === currentId) ?? null, [path, currentId]);
  const index = exercise ? path.indexOf(exercise) : path.length;
  const onScreen = exercise ? pathname === pathOf(exercise.href) || pathname.startsWith(`${pathOf(exercise.href)}/`) : false;

  const complete = useCallback(
    (ex: Exercise) => {
      markDone(ex.id);
      // Do stanu, nie z `markDone`: ta zwraca tylko pamięć przeglądarki, bez
      // ćwiczeń zaliczonych na serwerze (24.11.2026: osoba z lukami po pierwszym
      // zaliczeniu wracała „Dalej” do ćwiczenia 1 z 27 i robiła wszystko od nowa).
      setDone((prev) => new Set(prev).add(ex.id));
      setPhase({ kind: "done" });
      setShowMe(false);
    },
    [],
  );

  // Widoczna kotwica („zajrzyj do…”).
  useEffect(() => {
    if (!exercise?.doneWhenVisible || phase.kind !== "task") return;
    const check = () => {
      if (visibleAnchor(exercise.anchor)) complete(exercise);
    };
    check();
    const id = window.setInterval(check, 400);
    return () => window.clearInterval(id);
  }, [exercise, phase.kind, complete]);

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
  }, [exercise, phase.kind, complete, CONTEXT]);

  const rect = useAnchorRect(exercise?.anchor ?? null, showMe && phase.kind === "task");

  const goNext = () => {
    const nextId = nextExerciseId(done, path);
    setCurrentId(nextId);
    setPhase({ kind: "task" });
    const next = path.find((e) => e.id === nextId);
    if (next && !(pathname === pathOf(next.href) || pathname.startsWith(`${pathOf(next.href)}/`))) router.push(next.href);
  };

  const finish = async () => {
    setLeaving(true);
    await flushProgress();
    leavePoligon("/jobs");
  };

  return (
    <>
      {rect && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed z-[122] rounded-lg ring-2 ring-primary ring-offset-2 ring-offset-background transition-all"
          style={{ left: rect.left - 4, top: rect.top - 4, width: rect.width + 8, height: rect.height + 8 }}
        />
      )}
      {/* Nad oknami (edytor CV ma z-[110]), jak karta lekcji nowości: 24.11.2026
          edytor zasłaniał „Zaliczone → Dalej”, a osoba klikała „Gotowe” i dostawała odmowę zapisu. */}
      <section
        ref={keepDialogsOpen}
        aria-label="Ćwiczenie na poligonie"
        className="pointer-events-auto fixed bottom-5 left-5 z-[121] w-[340px] max-w-[calc(100vw-2.5rem)] overflow-hidden rounded-xl border border-border bg-card text-sm text-foreground shadow-lg"
      >
        <header className="flex items-center gap-2 border-b border-border px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          <Target className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">
            Poligon · {exercise ? `${exercise.module} · ${index + 1} z ${path.length}` : "onboarding"}
          </span>
          <span className="flex shrink-0 gap-0.5" aria-hidden="true">
            {path.map((e) => (
              <i
                key={e.id}
                className={cn(
                  "h-1 w-1.5 rounded-full",
                  done.has(e.id) ? "bg-success" : e.id === currentId ? "bg-primary" : "bg-border",
                )}
              />
            ))}
          </span>
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Rozwiń ćwiczenie" : "Zwiń ćwiczenie"}
            className="-mr-2 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            {collapsed ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
        </header>

        {collapsed ? null : !exercise ? (
          <div className="space-y-3 px-4 py-3">
            <p className="flex items-start gap-2 rounded-lg bg-success-muted px-3 py-2 text-success-muted-foreground">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                <b>Onboarding zaliczony.</b> Za Tobą: {modulesText(path)}. NEXUS jest otwarty
                {onboardingDay ? " — dziś nie liczy się do Twoich statystyk" : ""}.
              </span>
            </p>
            <Button className="w-full" disabled={leaving} onClick={() => void finish()}>
              Zacznij pracę w NEXUSIE
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
                {nextExerciseId(done, path) ? "Dalej →" : "Zakończ onboarding"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-2 px-4 py-3">
            <h2 className="text-[15px] font-semibold leading-snug">{exercise.title(CONTEXT)}</h2>
            <p className="text-muted-foreground">{exercise.task(CONTEXT)}</p>
            {exercise.download ? (
              <a
                href={exercise.download.href}
                download
                className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
              >
                <Download className="h-3.5 w-3.5" aria-hidden="true" />
                {exercise.download.label}
              </a>
            ) : null}
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
