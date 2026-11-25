import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { writeRun, type LessonRun } from "@/lib/novelties/lessons";

// Warunek „page” w etapie „sam” (25.11.2026, test lekcji na stagingu):
// A. zakładki i filtry zmieniają samo query przez `history.replaceState`
//    (ścieżka zostaje), więc „Opieka i rozmowy” na karcie kontraktu, pigułka
//    „Zamówione po końcu” i „Nagrania” w Szkoleniach nie zaliczały się nigdy;
// B. pokaz kończący się na ekranie z warunku zaliczał „sam” od razu, zanim
//    karta przeszła na `solo_href` (Boty sprzedaży, karta firmy → Kontakty).

const sendLessonEvent = vi.hoisted(() => vi.fn(async () => true));
let pathname = "/contracts/990521";

vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
vi.mock("@/lib/novelties/api", () => ({ sendLessonEvent }));
vi.mock("@/lib/poligon/adapter", () => ({ onPoligonAction: () => () => undefined }));

import { LessonLayer } from "../LessonLayer";

function run(stage: LessonRun["stage"]): LessonRun {
  return {
    lesson: {
      id: "lekcja-karta-kontraktu",
      title: "Karta kontraktu",
      task: "Otwórz „Opieka i rozmowy”.",
      solo_href: "/contracts",
      check: { kind: "page", path_prefix: "/contracts/990521", query: { tab: "care" } },
      questions: [{ q: "Po co?", options: ["a", "b", "c"], answer: 0, explain: "e" }],
    },
    show: [],
    stage,
    showIndex: 0,
    review: false,
    origin: "daily",
    question: 0,
    wrongStreak: 0,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  sendLessonEvent.mockClear();
  window.sessionStorage.clear();
  pathname = "/contracts/990521";
  window.history.replaceState(null, "", "/contracts/990521");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("LessonLayer — warunek „page”", () => {
  it("zalicza zakładkę, która zmienia samo query (replaceState)", async () => {
    writeRun(run("solo"));
    render(<LessonLayer />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(sendLessonEvent).not.toHaveBeenCalled();

    window.history.replaceState(null, "", "/contracts/990521?tab=care");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(sendLessonEvent).toHaveBeenCalledWith("lekcja-karta-kontraktu", "solo_passed");
  });

  it("nie zalicza w dokumencie, w którym pokaz dopiero przeszedł na „sam”", async () => {
    // Pokaz skończył się na ekranie z warunku; `goToStage` zaraz przeładuje kartę na `solo_href`.
    window.history.replaceState(null, "", "/contracts/990521?tab=care");
    writeRun(run("show"));
    render(<LessonLayer />);
    await act(async () => {
      writeRun(run("solo"));
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(sendLessonEvent).not.toHaveBeenCalled();
  });
});
