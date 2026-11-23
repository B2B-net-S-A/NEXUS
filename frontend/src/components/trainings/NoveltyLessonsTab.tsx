"use client";

// Szkolenia → „Nowości w NEXUSIE” (pomysł Igora, decyzja Artura 23.11.2026):
// wszystkie lekcje nowości z roli osoby, po miejscu w NEXUSIE, z wyszukiwarką.
// Powtórka idzie tylko na Poligonie — pokaz, potem samodzielnie — więc
// prawdziwe rekrutacje i kontrakty zostają nietknięte.

import { RotateCcw, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMyLessons } from "@/lib/novelties/api";
import { lessonArea, startLesson, type Lesson } from "@/lib/novelties/lessons";
import { resolveViewState } from "@/lib/view-state";

const DAY = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", timeZone: "Europe/Warsaw" });

const FILTERS = [
  { value: "all", label: "Wszystkie" },
  { value: "todo", label: "Jeszcze nie umiem" },
  { value: "week", label: "Ostatnie 7 dni" },
] as const;
type Filter = (typeof FILTERS)[number]["value"];

function statusText(lesson: Lesson): string {
  if (lesson.state === "done") return "umiesz";
  if (lesson.legacy_done) return "przeklikane przed lekcjami";
  if (lesson.state === "retry") return "samemu jeszcze nie wyszło";
  if (lesson.state === "shown") return "po pokazie";
  return "jeszcze nie";
}

/** Lekcje po miejscu w NEXUSIE; najliczniejsze grupy pierwsze. */
export function groupLessons(
  lessons: readonly Lesson[],
  query: string,
  filter: Filter,
  today: Date,
): [string, Lesson[]][] {
  const needle = query.trim().toLowerCase();
  const since = new Date(today.getTime() - 7 * 86_400_000).toISOString().slice(0, 10);
  const groups = new Map<string, Lesson[]>();
  for (const lesson of lessons) {
    const text = [lesson.title, lesson.task, ...lesson.novelties.map((n) => `${n.title} ${n.why} ${n.where}`)]
      .join(" ")
      .toLowerCase();
    if (needle && !text.includes(needle)) continue;
    if (filter === "todo" && lesson.state === "done") continue;
    if (filter === "week" && lesson.shipped_on < since) continue;
    const area = lessonArea(lesson);
    groups.set(area, [...(groups.get(area) ?? []), lesson]);
  }
  return [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0], "pl"));
}

export function NoveltyLessonsTab() {
  const query = useMyLessons();
  const [text, setText] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const lessons = useMemo(() => query.data ?? [], [query.data]);
  const groups = useMemo(() => groupLessons(lessons, text, filter, new Date()), [lessons, text, filter]);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: lessons.length === 0,
  });
  if (state === "loading") return <p className="text-sm text-muted-foreground">Ładowanie…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => query.refetch()} />;
  }
  if (state === "empty") {
    return (
      <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
        Na razie nie ma lekcji z Twoich ekranów. Pojawią się tu razem z porannymi nowościami.
      </p>
    );
  }

  const known = lessons.filter((l) => l.state === "done").length;
  return (
    <div className="space-y-3">
      <p className="rounded-md bg-primary/5 px-3 py-2 text-xs text-foreground">
        Każda lekcja otwiera się na Poligonie, na ćwiczebnych danych: najpierw pokaz z NEXUSEM, potem samodzielnie.
        Twoje prawdziwe rekrutacje i kontrakty zostają nietknięte.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Szukaj: umowa, CV, Tablica…"
            aria-label="Szukaj w nowościach"
            className="pl-8"
          />
        </div>
        {FILTERS.map((f) => (
          <Button
            key={f.value}
            size="sm"
            variant={filter === f.value ? "secondary" : "ghost"}
            aria-pressed={filter === f.value}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">
          Umiesz {known} z {lessons.length}
        </span>
      </div>
      {groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nic nie pasuje do wyszukiwania.</p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {groups.map(([area, items]) => (
            <section key={area} className="min-w-0 rounded-lg border border-border bg-card">
              <h3 className="flex items-center gap-2 border-b border-border px-4 py-2 text-sm font-semibold">
                {area}
                <span className="text-xs font-normal text-muted-foreground">{items.length}</span>
              </h3>
              <ul className="divide-y divide-border">
                {items.map((lesson) => (
                  <li key={lesson.id} className="flex items-center gap-2 px-4 py-2" data-testid="training-lesson">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm" title={lesson.title}>
                        {lesson.title}
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        {DAY.format(new Date(`${lesson.shipped_on}T12:00:00Z`))} · {statusText(lesson)}
                      </p>
                    </div>
                    {lesson.state !== "done" && !lesson.legacy_done ? (
                      <Badge variant="warning" size="sm">
                        nowe
                      </Badge>
                    ) : null}
                    <Button size="sm" variant="ghost" className="shrink-0" onClick={() => startLesson(lesson, "trainings")}>
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Powtórz na Poligonie
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
