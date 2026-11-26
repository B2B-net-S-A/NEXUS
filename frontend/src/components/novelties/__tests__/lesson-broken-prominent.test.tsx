import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readRun, writeRun, type LessonRun } from "@/lib/novelties/lessons";

// 26.11.2026: Delivery Lead sześć razy w minutę wracał z etapu „sam” do pokazu
// i stał — furtka „Coś nie działa — zalicz i dalej” była szarym napisem 11 px
// pod przyciskami. Od drugiego powrotu jest przyciskiem głównym karty.

const sendLessonEvent = vi.hoisted(() => vi.fn(async (_id: string, _event: string) => true));
const enterPoligon = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ usePathname: () => "/jobs/990001" }));
vi.mock("@/lib/novelties/api", () => ({ sendLessonEvent }));
vi.mock("@/lib/poligon/adapter", () => ({ onPoligonAction: () => () => undefined }));
vi.mock("@/lib/poligon/mode", () => ({ enterPoligon, leavePoligon: vi.fn() }));

import { LessonLayer } from "../LessonLayer";

function run(soloTries?: number): LessonRun {
  return {
    lesson: {
      id: "lekcja-arkusz-rozmowy",
      title: "Arkusz rozmowy",
      task: "Włącz „Tryb rozmowy”.",
      solo_href: "/jobs/990001?candidate=990106&panel=screening",
      check: { kind: "click", anchor: "screening.sheet.gaps" },
      questions: [{ q: "Po co?", options: ["a", "b", "c"], answer: 0, explain: "e" }],
    },
    show: [],
    stage: "solo",
    showIndex: 0,
    review: false,
    origin: "daily",
    question: 0,
    wrongStreak: 0,
    soloTries,
  };
}

beforeEach(() => {
  sendLessonEvent.mockClear();
  enterPoligon.mockClear();
  window.sessionStorage.clear();
});

describe("LessonLayer — furtka „Coś nie działa”", () => {
  it("na pierwszej próbie jest przyciskiem, ale nie głównym", () => {
    writeRun(run());
    render(<LessonLayer />);
    expect(screen.getByRole("button", { name: "Coś nie działa — zalicz i dalej" })).toBeTruthy();
    expect(screen.queryByTestId("lesson-broken-prominent")).toBeNull();
  });

  it("„Wróć do pokazu” liczy powroty w przebiegu", async () => {
    writeRun(run(1));
    render(<LessonLayer />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Wróć do pokazu/ }));
    });
    expect(sendLessonEvent).toHaveBeenCalledWith("lekcja-arkusz-rozmowy", "solo_failed");
    // Lekcja bez wpisów pokazu wraca od razu do „sam” — z licznikiem.
    expect(readRun()?.soloTries).toBe(2);
  });

  it("od drugiego powrotu do pokazu jest przyciskiem głównym z wyjaśnieniem i zalicza lekcję", async () => {
    writeRun(run(2));
    render(<LessonLayer />);
    const box = screen.getByTestId("lesson-broken-prominent");
    expect(box.textContent).toContain("zapiszemy, że coś tu nie działa");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Coś nie działa — zalicz i dalej" }));
    });
    expect(sendLessonEvent).toHaveBeenCalledWith("lekcja-arkusz-rozmowy", "broken");
  });

  it("powtórka nie dostaje furtki głównej (ma „oddaj powtórkę”)", () => {
    writeRun({ ...run(3), review: true });
    render(<LessonLayer />);
    expect(screen.queryByTestId("lesson-broken-prominent")).toBeNull();
  });
});
