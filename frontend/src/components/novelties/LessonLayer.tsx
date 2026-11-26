"use client";

/**
 * Lekcja nowości na Poligonie — etap „sam” i pytanie (decyzje Artura 23.11.2026).
 *
 * Pokaz prowadzi `NoveltyLayer`. Tu: zadanie bez podświetlenia, zaliczane
 * warunkiem lekcji (klik w element, ruch karty, ekran), potem pytanie
 * „po co / kiedy”. Nie wyszło albo dwa razy źle na pytanie → powrót do
 * pokazu. Pominąć się nie da; przycisk „Przerwij” wraca na listę bez zaliczenia.
 *
 * Jedna furtka: element z zadania bywa ukryty dla części odbiorców (poziom
 * dostępu, brak kart w porcji). Wtedy po `UNAVAILABLE_AFTER_MS` w etapie „sam”
 * pojawia się „Nie widzę tego u siebie” — przechodzi do pytania, które i tak
 * trzeba zaliczyć (ta sama zasada co „Nie mam tego — dalej” przy przeklikaniu:
 * nikt nie może utknąć na zawsze, Artur 30.10.2026).
 */

import { CheckCircle2, CircleAlert, Eye, MessageCircleQuestion, Target } from "lucide-react";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { sendLessonEvent } from "@/lib/novelties/api";
import {
  afterWrongAnswer,
  backFromSolo,
  BROKEN_PROMINENT_AFTER,
  goToStage,
  judgeClick,
  judgeMove,
  judgePage,
  LESSON_RUN_EVENT,
  leaveLesson,
  readRun,
  restartShow,
  shuffledOptions,
  skipBrokenLesson,
  writeRun,
  type LessonRun,
} from "@/lib/novelties/lessons";
import { keepDialogsOpen, onEveryClick } from "@/lib/novelties/logic";
import { onPoligonAction } from "@/lib/poligon/adapter";

type Outcome =
  | { kind: "none" }
  | { kind: "solo_wrong"; feedback: string }
  | { kind: "quiz_wrong"; explain: string }
  | { kind: "done" }
  | { kind: "review_failed"; feedback: string }
  /** Zapis etapu nie doszedł do serwera — nie udajemy zaliczenia. */
  | { kind: "save_error" };

/** Po tylu ms w etapie „sam” (warunek „click” albo „page”) pojawia się „Nie widzę tego u siebie”. */
export const UNAVAILABLE_AFTER_MS = 45_000;

// Nad oknami Radix (z-110, `ui/dialog.tsx`), jak karta kroku przeklikania:
// zadanie kończy się często w otwartym oknie (wysyłka do podpisu), a pytanie
// musi dać się kliknąć bez zamykania go. Klik w kartę okna nie zamyka
// (`keepDialogsOpen`, 24.11.2026): w „Klient coś zmienił” zamykał je razem
// z wpisaną treścią.
const CARD =
  "pointer-events-auto fixed bottom-5 left-5 z-[121] w-[360px] max-w-[calc(100vw-2.5rem)] rounded-xl border bg-card p-4 text-sm text-foreground shadow-lg";

export function LessonLayer() {
  const pathname = usePathname() ?? "";
  const [run, setRun] = useState<LessonRun | null>(null);
  const [outcome, setOutcome] = useState<Outcome>({ kind: "none" });
  const passing = useRef(false);

  // Etap „sam” ocenia warunek „page” tylko w dokumencie, który wczytał się już
  // w tym etapie: przejście z pokazu (`goToStage`) przeładowuje kartę na
  // `solo_href`, a do tego czasu adres to ostatni ekran pokazu (25.11.2026:
  // pokaz kończący się na ekranie z warunku zaliczał „sam” bez żadnego ruchu).
  const soloAtLoad = useRef(false);

  useEffect(() => {
    soloAtLoad.current = readRun()?.stage === "solo";
    setRun(readRun());
    const onRun = () => setRun(readRun());
    window.addEventListener(LESSON_RUN_EVENT, onRun);
    return () => window.removeEventListener(LESSON_RUN_EVENT, onRun);
  }, []);

  const update = useCallback((next: LessonRun) => {
    writeRun(next);
    setRun(next);
  }, []);

  const backToShow = useCallback(
    async (current: LessonRun, event: "solo_failed" | "restart") => {
      await sendLessonEvent(current.lesson.id, event);
      goToStage(event === "solo_failed" ? backFromSolo(current) : restartShow(current));
    },
    [],
  );

  const soloPassed = useCallback(
    async (current: LessonRun) => {
      if (passing.current) return;
      passing.current = true;
      if (current.review) {
        if (!(await sendLessonEvent(current.lesson.id, "review_passed"))) {
          passing.current = false;
          setOutcome({ kind: "save_error" });
          return;
        }
        setOutcome({ kind: "done" });
        window.setTimeout(() => leaveLesson(current), 1200);
        return;
      }
      if (!(await sendLessonEvent(current.lesson.id, "solo_passed"))) {
        passing.current = false;
        setOutcome({ kind: "save_error" });
        return;
      }
      setOutcome({ kind: "none" });
      update({ ...current, stage: "quiz", question: 0, wrongStreak: 0 });
      passing.current = false;
    },
    [update],
  );

  const soloFailed = useCallback(async (current: LessonRun, feedback: string) => {
    if (current.review) {
      if (!(await sendLessonEvent(current.lesson.id, "review_failed"))) {
        setOutcome({ kind: "save_error" });
        return;
      }
      setOutcome({ kind: "review_failed", feedback });
      return;
    }
    await sendLessonEvent(current.lesson.id, "solo_failed");
    setOutcome({ kind: "solo_wrong", feedback });
  }, []);

  const solo = run?.stage === "solo" ? run : null;
  // Karta zadania stoi w lewym dolnym rogu i przy 1280 × 720 zasłania elementy
  // z zadań („Zajęcie” w Przelewach, nazwiska w Rozliczeniach, pasek braków
  // generatora umów — test lekcji 25.11.2026). Osoba może ją zwinąć do paska.
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    setCollapsed(false);
  }, [run?.lesson.id, run?.stage, outcome.kind]);
  const [unavailable, setUnavailable] = useState(false);
  const soloKey = solo ? solo.lesson.id : null;
  const soloKind = solo?.lesson.check.kind ?? null;
  useEffect(() => {
    setUnavailable(false);
    if (!soloKey || (soloKind !== "click" && soloKind !== "page")) return;
    const id = window.setTimeout(() => setUnavailable(true), UNAVAILABLE_AFTER_MS);
    return () => window.clearTimeout(id);
  }, [soloKey, soloKind]);

  // Warunek „click”: osoba sama znajduje element.
  useEffect(() => {
    if (!solo || solo.lesson.check.kind !== "click") return;
    return onEveryClick(document, (target) => {
      if (judgeClick(solo.lesson.check, target)) window.setTimeout(() => void soloPassed(solo), 200);
    });
  }, [solo, soloPassed]);

  // Warunek „move”: ruch karty na rekrutacji ćwiczebnej.
  useEffect(() => {
    if (!solo || solo.lesson.check.kind !== "move") return;
    return onPoligonAction((action) => {
      const verdict = judgeMove(solo.lesson.check, action);
      if (!verdict) return;
      if (verdict.done) void soloPassed(solo);
      else void soloFailed(solo, verdict.feedback);
    });
  }, [solo, soloPassed, soloFailed]);

  // Warunek „page”: osoba sama doszła do ekranu. Zakładki i filtry zmieniają
  // samo query przez `history.replaceState`, bez zmiany ścieżki, więc adres
  // sprawdzamy też co pół sekundy (25.11.2026: „Opieka i rozmowy”, „Zamówione
  // po końcu” i „Nagrania” nie zaliczały się nigdy).
  useEffect(() => {
    if (!solo || solo.lesson.check.kind !== "page" || !soloAtLoad.current) return;
    let id = 0;
    const check = () => {
      if (!judgePage(solo.lesson.check, window.location.pathname, window.location.search)) return;
      // Raz: nieudany zapis pokazuje błąd, a nie wysyła zdarzenia co pół sekundy.
      window.clearInterval(id);
      void soloPassed(solo);
    };
    id = window.setInterval(check, 500);
    check();
    return () => window.clearInterval(id);
  }, [solo, pathname, soloPassed]);

  const options = useMemo(() => {
    if (!run || run.stage !== "quiz") return [];
    const question = run.lesson.questions[run.question];
    return question ? shuffledOptions(run.lesson.id, run.question, question) : [];
  }, [run]);

  if (!run || run.stage === "show") return null;

  const header = (
    <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-primary">
      {run.stage === "quiz" ? (
        <MessageCircleQuestion className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <Target className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      <span className="shrink-0 whitespace-nowrap">
        {run.review ? "Powtórka" : "Lekcja"} · {run.stage === "quiz" ? "pytanie" : "teraz sam"}
      </span>
      <span className="ml-auto truncate font-normal text-muted-foreground">{run.lesson.title}</span>
    </p>
  );

  if (outcome.kind === "done") {
    return (
      <section ref={keepDialogsOpen} className={`${CARD} border-success/30`} role="status" data-testid="lesson-done">
        <p className="flex items-start gap-2 text-success">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="font-semibold">
            {run.review ? "Powtórka zaliczona." : `Umiesz: ${run.lesson.title}.`} Wracamy do listy.
          </span>
        </p>
      </section>
    );
  }

  if (outcome.kind === "review_failed") {
    return (
      <section ref={keepDialogsOpen} className={`${CARD} border-warning/40`} role="status" data-testid="lesson-review-failed">
        {header}
        <p className="flex items-start gap-2 rounded-lg bg-warning-muted px-3 py-2 text-warning-muted-foreground">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{outcome.feedback} Ta lekcja wróci w najbliższej porcji, od pokazu.</span>
        </p>
        <div className="mt-3 flex justify-end">
          <Button size="sm" onClick={() => leaveLesson(run)}>
            Wróć do listy
          </Button>
        </div>
      </section>
    );
  }

  if (run.stage === "solo" && collapsed) {
    return (
      <section
        ref={keepDialogsOpen}
        className="pointer-events-auto fixed bottom-5 left-5 z-[121] rounded-full border border-primary/30 bg-card shadow-lg"
        aria-label="Zadanie lekcji (zwinięte)"
        data-testid="lesson-solo-collapsed"
      >
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-primary"
        >
          <Target className="h-3.5 w-3.5" aria-hidden="true" />
          {run.review ? "Powtórka" : "Lekcja"} · pokaż zadanie
        </button>
      </section>
    );
  }

  if (run.stage === "solo") {
    const stuck = !run.review && (run.soloTries ?? 0) >= BROKEN_PROMINENT_AFTER;
    return (
      <section ref={keepDialogsOpen} className={`${CARD} border-primary/30`} aria-label="Zadanie lekcji" data-testid="lesson-solo">
        {header}
        <p className="font-semibold leading-snug">{run.lesson.task}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Bez podświetlenia. Zaliczy się samo, gdy zrobisz to, o co chodzi.
        </p>
        {outcome.kind === "save_error" ? <SaveError /> : null}
        {outcome.kind === "solo_wrong" ? (
          <p role="alert" className="mt-2 flex items-start gap-2 rounded-lg bg-destructive-muted px-3 py-2 text-destructive-muted-foreground">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{outcome.feedback}</span>
          </p>
        ) : null}
        <div className="mt-3 flex items-center gap-2">
          {run.review ? null : (
            <Button
              size="sm"
              variant={outcome.kind === "solo_wrong" && !stuck ? "primary" : "outline"}
              onClick={() => void backToShow(run, "solo_failed")}
            >
              <Eye className="h-3.5 w-3.5" aria-hidden="true" />
              {outcome.kind === "solo_wrong" ? "Pokaż jeszcze raz" : "Wróć do pokazu"}
            </Button>
          )}
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            className="ml-auto text-xs font-semibold text-muted-foreground hover:text-foreground"
          >
            Zwiń
          </button>
          <button
            type="button"
            onClick={() => leaveLesson(run)}
            className="text-xs font-semibold text-muted-foreground hover:text-foreground"
          >
            Przerwij
          </button>
        </div>
        {unavailable && !run.review ? (
          <button
            type="button"
            className="mt-2 text-[11px] text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => void soloPassed(run)}
          >
            Nie widzę tego u siebie — przejdź do pytania
          </button>
        ) : null}
        {unavailable && run.review ? (
          // Powtórka nie może trzymać blokady cały piątek: oddana wraca jako lekcja od pokazu.
          <button
            type="button"
            className="mt-2 text-[11px] text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => void soloFailed(run, "Powtórka oddana.")}
          >
            Nie wychodzi — oddaj powtórkę
          </button>
        ) : null}
        <BrokenButton run={run} prominent={stuck} />
      </section>
    );
  }

  const question = run.lesson.questions[run.question];
  return (
    <section ref={keepDialogsOpen} className={`${CARD} border-primary/30`} aria-label="Pytanie lekcji" data-testid="lesson-quiz">
      {header}
      <p className="font-semibold leading-snug">{question?.q}</p>
      {outcome.kind === "save_error" ? <SaveError /> : null}
      {outcome.kind === "quiz_wrong" ? (
        <p role="alert" className="mt-2 rounded-lg bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          Nie. {outcome.explain} Teraz inne pytanie.
        </p>
      ) : null}
      <div className="mt-2 space-y-1.5" role="group" aria-label="Odpowiedzi">
        {options.map((option) => (
          <button
            key={option.text}
            type="button"
            className="w-full rounded-lg border border-border px-3 py-2 text-left text-sm hover:border-primary hover:bg-primary/5"
            onClick={async () => {
              if (option.correct) {
                if (!(await sendLessonEvent(run.lesson.id, "completed"))) {
                  setOutcome({ kind: "save_error" });
                  return;
                }
                setOutcome({ kind: "done" });
                window.setTimeout(() => leaveLesson(run), 1200);
                return;
              }
              await sendLessonEvent(run.lesson.id, "quiz_wrong");
              const next = afterWrongAnswer(run);
              if (next.backToShow) {
                await backToShow(run, "restart");
                return;
              }
              setOutcome({ kind: "quiz_wrong", explain: question?.explain ?? "" });
              update(next.run);
            }}
          >
            {option.text}
          </button>
        ))}
      </div>
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={() => leaveLesson(run)}
          className="text-xs font-semibold text-muted-foreground hover:text-foreground"
        >
          Przerwij
        </button>
      </div>
      <BrokenButton run={run} />
    </section>
  );
}

/**
 * „Coś nie działa — zalicz i dalej” (Artur, 25.11.2026): wyjście z lekcji,
 * w której coś jest zepsute. Serwer zalicza ją od razu i zapisuje ślad. Stoi
 * w zadaniu „sam” i w pytaniu, nie w pokazie (26.11.2026: od pierwszego kroku
 * pokazu służyło do pomijania całych porcji).
 */
interface BrokenButtonProps {
  run: LessonRun;
  /** Osoba wraca do pokazu kolejny raz: furtka staje się przyciskiem głównym. */
  prominent?: boolean;
}

export function BrokenButton({ run, prominent = false }: BrokenButtonProps) {
  const [sending, setSending] = useState(false);
  const skip = () => {
    setSending(true);
    void skipBrokenLesson(run);
  };
  if (prominent) {
    // 26.11.2026: szary napis pod przyciskami przeoczył Delivery Lead, który
    // sześć razy wracał do pokazu i nie mógł pracować.
    return (
      <div className="mt-3 rounded-lg bg-muted px-3 py-2" data-testid="lesson-broken-prominent">
        <p className="text-xs text-muted-foreground">
          Po pokazie dalej nie wychodzi? Zalicz lekcję i wróć do pracy — zapiszemy, że coś tu nie działa.
        </p>
        <Button size="sm" className="mt-2 w-full" loading={sending} onClick={skip}>
          Coś nie działa — zalicz i dalej
        </Button>
      </div>
    );
  }
  return (
    <Button size="sm" variant="tertiary" className="mt-1 h-auto px-0 py-1" loading={sending} onClick={skip}>
      Coś nie działa — zalicz i dalej
    </Button>
  );
}

function SaveError() {
  return (
    <p role="alert" className="mt-2 flex items-start gap-2 rounded-lg bg-destructive-muted px-3 py-2 text-destructive-muted-foreground">
      <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>Nie udało się zapisać postępu. Sprawdź połączenie i spróbuj jeszcze raz — lekcja jeszcze się nie zaliczyła.</span>
    </p>
  );
}
