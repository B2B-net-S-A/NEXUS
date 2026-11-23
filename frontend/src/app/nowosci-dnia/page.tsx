"use client";

// Poranna porcja nowości jako lekcje (decyzje Artura 18.11 i 23.11.2026).
// Każda lekcja idzie na Poligonie: pokaz z NEXUSEM → sam, na innych danych →
// pytanie. Najwyżej 5 lekcji dziennie; odłożyć można raz dziennie do 15:00,
// admin może pominąć dzień. Zatrzymuje `useDailyNoveltyGate`, dane:
// `GET /api/novelties/daily`, przebieg: `lib/novelties/lessons.ts`.

import { useQueryClient } from "@tanstack/react-query";
import {
  AlarmClock,
  Check,
  ChevronDown,
  Eye,
  FastForward,
  Lock,
  MessageCircleQuestion,
  RotateCcw,
  Sparkles,
  Target,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiErrorMessage } from "@/lib/api-error";
import { dailyKey, postponeDaily, skipDaily, useDailyStatus } from "@/lib/novelties/api";
import { startLesson, type Lesson } from "@/lib/novelties/lessons";
import { useAuthStore } from "@/store/auth";

const TIME = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

const STAGES = [
  { label: "Pokaz z NEXUSEM", icon: Eye },
  { label: "Sam, na innych danych", icon: Target },
  { label: "Pytanie", icon: MessageCircleQuestion },
] as const;

function plural(count: number, one: string, few: string, many: string): string {
  if (count === 1) return one;
  const lastTwo = count % 100;
  const last = count % 10;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? few : many;
}

/** Trzy etapy lekcji: zielony = zrobione, pomarańczowy = nie wyszło, szary = przed Tobą. */
function Stages({ lesson }: { lesson: Lesson }) {
  const status = (i: number): "ok" | "fail" | "todo" => {
    if (lesson.state === "done") return "ok";
    if (lesson.state === "retry") return i === 0 ? "ok" : i === 1 ? "fail" : "todo";
    if (lesson.state === "shown") return i === 0 ? "ok" : "todo";
    return "todo";
  };
  return (
    <ol className="mt-2 flex flex-wrap items-center gap-1 text-[11px]" aria-label="Etapy lekcji">
      {STAGES.map((stage, i) => {
        const s = status(i);
        const Icon = s === "ok" ? Check : s === "fail" ? RotateCcw : stage.icon;
        return (
          <li key={stage.label} className="flex items-center gap-1">
            {i > 0 ? <span className="text-muted-foreground" aria-hidden="true">→</span> : null}
            <span
              className={`flex items-center gap-1 rounded-full border px-2 py-0.5 ${
                s === "ok"
                  ? "border-success/30 bg-success-muted text-success-muted-foreground"
                  : s === "fail"
                    ? "border-warning/30 bg-warning-muted text-warning-muted-foreground"
                    : "border-border text-muted-foreground"
              }`}
            >
              <Icon className="h-3 w-3" aria-hidden="true" />
              {i + 1}. {stage.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function LessonAction({ lesson, primary }: { lesson: Lesson; primary: boolean }) {
  if (lesson.review) {
    if (lesson.review_state === "passed") return <Badge variant="success" size="md">Zrobione bez podpowiedzi</Badge>;
    if (lesson.review_state === "failed") return <Badge variant="warning" size="md">Nie wyszło, lekcja wróci</Badge>;
    return (
      <Button size="sm" variant={primary ? "primary" : "outline"} onClick={() => startLesson(lesson, "daily")}>
        <Target className="h-3.5 w-3.5" aria-hidden="true" /> Zacznij
      </Button>
    );
  }
  if (lesson.state === "done") return <span className="text-xs font-medium text-success">Umiesz</span>;
  if (lesson.state === "retry") {
    return (
      <div className="flex flex-col items-end gap-1">
        <Button size="sm" onClick={() => startLesson(lesson, "daily")}>
          <Eye className="h-3.5 w-3.5" aria-hidden="true" /> Pokaż jeszcze raz
        </Button>
        <button
          type="button"
          className="text-[11px] text-muted-foreground underline-offset-2 hover:underline"
          onClick={() => startLesson(lesson, "daily", { solo: true })}
        >
          Spróbuj sam od razu
        </button>
      </div>
    );
  }
  if (lesson.state === "shown") {
    return (
      <Button size="sm" variant={primary ? "primary" : "outline"} onClick={() => startLesson(lesson, "daily", { solo: true })}>
        <Target className="h-3.5 w-3.5" aria-hidden="true" /> Teraz sam
      </Button>
    );
  }
  return (
    <Button size="sm" variant={primary ? "primary" : "outline"} onClick={() => startLesson(lesson, "daily")}>
      <Eye className="h-3.5 w-3.5" aria-hidden="true" /> Zacznij od pokazu
    </Button>
  );
}

function LessonCard({ lesson, index, primary }: { lesson: Lesson; index: number; primary: boolean }) {
  const [open, setOpen] = useState(false);
  const done = lesson.review ? lesson.review_state === "passed" : lesson.state === "done";
  return (
    <li className="rounded-lg border border-border bg-card px-4 py-3" data-testid="daily-lesson">
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
            done ? "bg-success text-success-foreground" : "bg-primary/10 text-primary"
          }`}
          aria-hidden="true"
        >
          {done ? <Check className="h-3.5 w-3.5" /> : index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="flex w-full flex-wrap items-baseline gap-x-2 text-left"
          >
            <span className="text-sm font-semibold leading-snug">{lesson.title}</span>
            {lesson.review ? <Badge variant="soft" size="sm">Powtórka z tygodnia</Badge> : null}
            <span className="text-[11px] text-muted-foreground">
              {lesson.novelties.length} {plural(lesson.novelties.length, "zmiana", "zmiany", "zmian")}
            </span>
            <ChevronDown
              className={`h-3.5 w-3.5 self-center text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
              aria-hidden="true"
            />
          </button>
          {open ? (
            <ul className="mt-1 space-y-0.5">
              {lesson.novelties.map((n) => (
                <li key={n.id} className="text-xs text-muted-foreground">
                  · <span className="text-foreground">{n.title}</span> — {n.why}
                </li>
              ))}
            </ul>
          ) : null}
          {done ? null : (
            <p className="mt-1.5 flex items-start gap-1.5 rounded-md bg-muted px-2.5 py-1.5 text-xs text-foreground">
              <Target className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
              <span>
                <span className="font-semibold">Zadanie: </span>
                {lesson.task}
              </span>
            </p>
          )}
          {lesson.review ? null : <Stages lesson={lesson} />}
          {lesson.state === "retry" && !lesson.review ? (
            <p className="mt-1 text-[11px] text-warning-muted-foreground">
              Samemu jeszcze nie wyszło. Obejrzyj pokaz jeszcze raz i spróbuj ponownie.
            </p>
          ) : null}
        </div>
        <div className="shrink-0 self-center">
          <LessonAction lesson={lesson} primary={primary} />
        </div>
      </div>
    </li>
  );
}

export default function DailyNoveltiesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const status = useDailyStatus(hydrated && Boolean(user));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!status) return null;
  const lessons = status.lessons ?? [];
  const open = status.total - status.done;
  const firstOpen = lessons.find((l) =>
    l.review ? l.review_state === "todo" : l.state !== "done",
  );
  const postponedTo = status.postponed_until ? TIME.format(new Date(status.postponed_until)) : null;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await queryClient.invalidateQueries({ queryKey: dailyKey });
      router.push("/dashboard");
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się. Spróbuj jeszcze raz."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4 pb-40">
      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-primary">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            Nowości na dziś
          </p>
          <div className="ml-auto flex gap-1.5">
            {status.can_skip ? (
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(skipDaily)}>
                <FastForward className="h-3.5 w-3.5" aria-hidden="true" /> Pomiń na dziś
              </Button>
            ) : null}
            {status.can_postpone ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="sm" variant="outline" disabled={busy}>
                    <AlarmClock className="h-3.5 w-3.5" aria-hidden="true" /> Odłóż na później
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-72">
                  {status.postpone_options.map((option) => (
                    <DropdownMenuItem key={option.key} onSelect={() => void act(() => postponeDaily(option.key))}>
                      {option.label}
                    </DropdownMenuItem>
                  ))}
                  <p className="px-2 py-1.5 text-[11px] text-muted-foreground">
                    Raz dziennie, najpóźniej do 15:00. O tej godzinie lekcje wrócą jak rano. Czego dziś nie
                    zrobisz, jutro będzie na początku i bez odkładania.
                  </p>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>
        </div>
        <h1 className="text-2xl font-semibold text-foreground">
          {lessons.length === 0
            ? "Nic nowego od ostatniego razu"
            : open === 0
              ? "Gotowe na dziś"
              : `${status.novelty_count} ${plural(status.novelty_count, "zmiana", "zmiany", "zmian")} w NEXUSIE · ${
                  lessons.length
                } ${plural(lessons.length, "lekcja", "lekcje", "lekcji")} na dziś`}
        </h1>
        <p className="text-sm text-muted-foreground">
          {lessons.length === 0
            ? "Gdy coś się zmieni w Twoich ekranach, rano dostaniesz tu lekcję."
            : open === 0
              ? "Wszystko zrobione. Do jutra NEXUS nie pokaże Ci żadnej nowości."
              : `Wszystko na Poligonie: prawdziwe ekrany, ćwiczebne dane, nic się nie zapisze naprawdę. Najpierw NEXUS pokazuje, jak to zrobić, potem robisz to sam na innych danych i odpowiadasz na pytanie. Ok. ${
                  open * 3
                } min.`}
        </p>
        {status.can_skip && open > 0 ? (
          <p className="rounded-md border border-border bg-muted px-3 py-1.5 text-xs text-foreground">
            Masz rolę admina, więc lekcje są dla Ciebie dobrowolne. Pominięte czekają w Szkolenia → Nowości w NEXUSIE.
          </p>
        ) : null}
        {postponedTo && open > 0 ? (
          <p className="rounded-md border border-border bg-muted px-3 py-1.5 text-xs text-foreground">
            Lekcje odłożone do {postponedTo}. Możesz zacząć wcześniej.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        ) : null}
      </header>

      {lessons.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">
            {status.done} z {status.total} {plural(status.total, "lekcji", "lekcji", "lekcji")}
          </p>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${(status.done / Math.max(1, status.total)) * 100}%` }}
            />
          </div>
        </div>
      ) : null}

      {lessons.length > 0 ? (
        <ol className="space-y-2">
          {lessons.map((lesson, i) => (
            <LessonCard key={lesson.id} lesson={lesson} index={i} primary={firstOpen?.id === lesson.id} />
          ))}
        </ol>
      ) : null}

      {status.later > 0 ? (
        <p className="text-xs text-muted-foreground">
          {status.later} {plural(status.later, "lekcja przechodzi", "lekcje przechodzą", "lekcji przechodzi")} na kolejne
          dni, bo dziennie jest najwyżej 5 lekcji. Nic nie przepada.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3">
        {open === 0 || status.can_skip || !status.enforced ? (
          <Button size="sm" variant={open === 0 ? "primary" : "outline"} onClick={() => router.push("/dashboard")}>
            Dalej do NEXUSA →
          </Button>
        ) : (
          <Button size="sm" variant="outline" disabled>
            <Lock className="h-3.5 w-3.5" aria-hidden="true" /> Dalej do NEXUSA: jeszcze {open}{" "}
            {plural(open, "lekcja", "lekcje", "lekcji")}
          </Button>
        )}
        {lessons.length > 0 ? (
          <p className="min-w-0 flex-1 text-xs text-muted-foreground">
            Lekcja zalicza się, gdy zrobisz zadanie sam i dobrze odpowiesz na pytanie. Pokazów możesz oglądać, ile
            chcesz.
          </p>
        ) : null}
      </div>
    </div>
  );
}
