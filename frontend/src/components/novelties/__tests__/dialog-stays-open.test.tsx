import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { writeTour, type Novelty } from "@/lib/novelties/logic";
import { writeRun, type LessonRun } from "@/lib/novelties/lessons";

// Lekcja „Klient coś zmienił” (24.11.2026): „Rozumiem” na karcie kroku 2
// zamykało okno „Co zmienił klient?” (Radix zamyka dialog po kliknięciu poza
// nim), więc krok 3 („Przygotuj zmiany”) nie miał czego wskazać. Karta lekcji
// („teraz sam”, pytanie) też zamykała okno, a z nim wpisaną treść.

const sendEvent = vi.fn();

vi.mock("next/navigation", () => ({ usePathname: () => "/jobs/990001" }));
vi.mock("@/lib/novelties/api", () => ({
  sendLessonEvent: vi.fn(async () => true),
  useDailyStatus: () => ({ enforced: false, items: [] }),
  useMyNoveltiesState: () => ({ items: [CLIENT_CHANGE, NEW_CV], loaded: true }),
  useNoveltyEvent: () => sendEvent,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel: (s: { user: object; hydrated: boolean }) => unknown) =>
    sel({ user: { id: 1, role: "recruiter" }, hydrated: true }),
}));
vi.mock("@/lib/poligon/adapter", () => ({ onPoligonAction: () => () => undefined }));

import { LessonLayer } from "../LessonLayer";
import { NoveltyLayer } from "../NoveltyLayer";

function novelty(id: string, steps: Novelty["steps"]): Novelty {
  return {
    id,
    title: id,
    why: "Po co",
    tier: "tour",
    shipped_on: "2026-11-23",
    where: "Rekrutacja → Profil Championa",
    href: "/jobs",
    practice_href: null,
    dot_anchor: steps[0].anchor,
    used_anchor: null,
    path_prefix: null,
    steps,
    done: false,
    start: false,
    completed_via: null,
    show_card: true,
    required_now: false,
    can_postpone: false,
  };
}

// Kroki jak w rejestrze (`novelties.json`): dwa ostatnie to „Rozumiem” w oknie.
const CLIENT_CHANGE = novelty("klient-cos-zmienil", [
  { anchor: "champion.client-change.open", text: "Kliknij „Klient coś zmienił”.", hint: "h", ack: false },
  { anchor: "champion.client-change.text", text: "Tu wklejasz mail od klienta.", hint: "h", ack: true },
  { anchor: "champion.client-change.propose", text: "„Przygotuj zmiany” daje listę zmian.", hint: "h", ack: true },
]);
// Następny krok poza oknem: „Rozumiem” zamyka okno jak dotąd.
const NEW_CV = novelty("nowe-cv-od-kandydata", [
  { anchor: "candidate.profile.add-cv", text: "Kliknij „Dodaj CV”.", hint: "h", ack: false },
  { anchor: "candidate.add-cv.dialog", text: "Wybierasz plik.", hint: "h", ack: true },
  { anchor: "person.cv.upload-new", text: "W rekrutacji „Wgraj nowe CV”.", hint: "h", ack: true },
]);

function ClientChangeDialog({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  const [open, setOpen] = useState(true);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        setOpen(next);
      }}
    >
      <DialogContent>
        <DialogTitle>Co zmienił klient?</DialogTitle>
        <textarea aria-label="Treść od klienta" data-tour="champion.client-change.text" />
        <button type="button" data-tour="champion.client-change.propose">
          Przygotuj zmiany
        </button>
      </DialogContent>
    </Dialog>
  );
}

function AddCvDialog({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  return (
    <>
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent data-tour="candidate.add-cv.dialog">
          <DialogTitle>Dodaj CV</DialogTitle>
        </DialogContent>
      </Dialog>
      <button type="button" data-tour="person.cv.upload-new">
        Wgraj nowe CV
      </button>
    </>
  );
}

/** Radix podpina nasłuch `pointerdown` na dokumencie dopiero w `setTimeout(0)` po otwarciu okna. */
async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

// Radix ustawia `pointer-events: none` na body, a karty mają `pointer-events-auto`
// (klasa, której jsdom nie liczy) — stąd bez sprawdzania.
const user = () => userEvent.setup({ pointerEventsCheck: 0 });
const tourCard = () => screen.getByTestId("novelty-tour-step");

beforeEach(() => {
  window.sessionStorage.clear();
  sendEvent.mockClear();
});

describe("karta kroku przeklikania nad otwartym oknem", () => {
  it("„Rozumiem”, gdy następny krok jest w tym samym oknie: okno zostaje, krok 3 ma co wskazać", async () => {
    writeTour({ noveltyId: "klient-cos-zmienil", step: 1 });
    const onOpenChange = vi.fn();
    render(
      <>
        <ClientChangeDialog onOpenChange={onOpenChange} />
        <NoveltyLayer />
      </>,
    );
    await settle();
    await user().click(within(tourCard()).getByRole("button", { name: "Rozumiem", hidden: true }));
    await settle();
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Co zmienił klient?" })).toBeInTheDocument();
    expect(tourCard()).toHaveTextContent("krok 3 z 3");
  });

  it("„Rozumiem” w ostatnim kroku zamyka okno bez zapisu, jak dotąd", async () => {
    writeTour({ noveltyId: "klient-cos-zmienil", step: 2 });
    const onOpenChange = vi.fn();
    render(
      <>
        <ClientChangeDialog onOpenChange={onOpenChange} />
        <NoveltyLayer />
      </>,
    );
    await settle();
    await user().click(within(tourCard()).getByRole("button", { name: "Rozumiem", hidden: true }));
    await settle();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("„Rozumiem”, gdy następny krok jest poza oknem: okno się zamyka i odsłania krok", async () => {
    writeTour({ noveltyId: "nowe-cv-od-kandydata", step: 1 });
    const onOpenChange = vi.fn();
    render(
      <>
        <AddCvDialog onOpenChange={onOpenChange} />
        <NoveltyLayer />
      </>,
    );
    await settle();
    await user().click(within(tourCard()).getByRole("button", { name: "Rozumiem", hidden: true }));
    await settle();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(tourCard()).toHaveTextContent("krok 3 z 3");
  });
});

describe("karta lekcji nad otwartym oknem", () => {
  function soloRun(): LessonRun {
    return {
      lesson: {
        id: "lekcja-klient-cos-zmienil",
        title: "„Klient coś zmienił”",
        task: "Przekaż zmianę od klienta w Profilu rekrutacji ćwiczebnej i poproś o propozycję.",
        solo_href: "/jobs/990001?tab=champion",
        check: { kind: "click", anchor: "champion.client-change.propose" },
        questions: [{ q: "Pytanie?", options: ["Tak", "Nie"], answer: 0, explain: "Bo tak." }],
      },
      show: [],
      stage: "solo",
      showIndex: 0,
      review: false,
      origin: "daily",
      question: 0,
      wrongStreak: 0,
    };
  }

  it("klik w kartę „teraz sam” nie zamyka okna z wpisaną treścią", async () => {
    writeRun(soloRun());
    const onOpenChange = vi.fn();
    render(
      <>
        <ClientChangeDialog onOpenChange={onOpenChange} />
        <LessonLayer />
      </>,
    );
    await settle();
    const card = screen.getByTestId("lesson-solo");
    await user().click(within(card).getByText(/Przekaż zmianę od klienta/));
    await settle();
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Co zmienił klient?" })).toBeInTheDocument();
  });
});

describe("pokaz w lekcji", () => {
  // 26.11.2026: „Coś nie działa — zalicz i dalej” od pierwszego kroku pokazu
  // służyło do pomijania całych porcji (4 osoby, po 5 lekcji). Furtka stoi
  // dopiero w zadaniu „sam” i w pytaniu (`lesson-page-check.test.tsx`).
  it("karta kroku pokazu nie ma „Coś nie działa”, ma „Przerwij”", async () => {
    const run: LessonRun = {
      lesson: {
        id: "lekcja-klient-cos-zmienil",
        title: "Klient coś zmienił",
        task: "Zadanie",
        solo_href: "/jobs/990001",
        check: { kind: "click", anchor: "champion.client-change.propose" },
        questions: [{ q: "Po co?", options: ["a", "b", "c"], answer: 0, explain: "e" }],
      },
      show: [CLIENT_CHANGE],
      stage: "show",
      showIndex: 0,
      review: false,
      origin: "daily",
      question: 0,
      wrongStreak: 0,
    };
    writeRun(run);
    writeTour({ noveltyId: "klient-cos-zmienil", step: 1 });
    render(
      <>
        <ClientChangeDialog onOpenChange={vi.fn()} />
        <NoveltyLayer />
      </>,
    );
    await settle();
    expect(tourCard()).toHaveTextContent("Lekcja · pokaz");
    expect(within(tourCard()).getByRole("button", { name: "Przerwij", hidden: true })).toBeInTheDocument();
    expect(within(tourCard()).queryByRole("button", { name: "Coś nie działa — zalicz i dalej", hidden: true })).toBeNull();
  });
});
