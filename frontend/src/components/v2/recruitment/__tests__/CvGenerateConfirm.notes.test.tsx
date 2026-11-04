import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvGenerateConfirm } from "@/components/v2/recruitment/CvGenerateConfirm";
import { NO_CONFIRMATIONS, type CvConfirmStep } from "@/lib/cv-generate-confirm";

const formState = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));

vi.mock("@/lib/api", () => ({ default: { get: vi.fn(() => Promise.resolve({ data: {} })), post: vi.fn() } }));
vi.mock("@/lib/api/screeningForm", () => ({ useScreeningFormState: () => formState.current }));
vi.mock("@/lib/screening-summary", () => ({ screeningFormHref: () => "/form", screeningSummaryRows: () => [] }));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

function loaded(raw: string | null) {
  return {
    isPending: false,
    isError: false,
    isSuccess: true,
    data: { card: { fields: raw == null ? {} : { recommendation: { raw } } } },
  };
}

function setup({
  left = ["notes"],
  noteDraft = "",
  notesSourceOn,
}: { left?: CvConfirmStep[]; noteDraft?: string; notesSourceOn?: boolean } = {}) {
  const onNoteDraftChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CvGenerateConfirm
        candidateId={1}
        jobId={2}
        files={[]}
        answers={null}
        existingNotes={0}
        fileId={null}
        onFileChange={() => undefined}
        noteDraft={noteDraft}
        onNoteDraftChange={onNoteDraftChange}
        confirmed={NO_CONFIRMATIONS}
        onConfirm={() => undefined}
        left={left}
        notesSourceOn={notesSourceOn}
      />
    </QueryClientProvider>,
  );
  return { step: screen.getByTestId("cv-confirm-notes"), onNoteDraftChange };
}

const LONG = `Kandydat ma 7 lat doświadczenia. ${"Prowadził zespół analityków. ".repeat(10)}`;

describe("Krok 3: „Dlaczego ten kandydat” ze screeningu", () => {
  beforeEach(() => {
    formState.current = loaded("Prowadził wdrożenia magazynowe w dwóch firmach.");
  });

  it("pokazuje tekst ze screeningu, a pole notatek zostaje puste", () => {
    const { step, onNoteDraftChange } = setup();
    const why = within(step).getByTestId("cv-notes-why");
    expect(why).toHaveTextContent("Prowadził wdrożenia magazynowe w dwóch firmach.");
    expect(why).toHaveTextContent("AI przeczyta to przy generacji");
    expect(within(step).getByRole("textbox", { name: "Dodatkowe notatki do CV" })).toHaveValue("");
    expect(onNoteDraftChange).not.toHaveBeenCalled();
    expect(within(why).getByRole("link", { name: "Popraw w formularzu" })).toHaveAttribute("href", "/form");
  });

  it("krótki tekst nie ma „Pokaż całość”, długi rozwija się i zwija", async () => {
    const short = setup();
    expect(within(short.step).queryByRole("button", { name: "Pokaż całość" })).toBeNull();
    cleanup();

    formState.current = loaded(LONG);
    const { step } = setup();
    const toggle = within(step).getByRole("button", { name: "Pokaż całość" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(within(step).getByRole("button", { name: "Zwiń" })).toHaveAttribute("aria-expanded", "true");
  });

  it("puste pole mówi o braku i prowadzi do formularza", () => {
    formState.current = loaded(null);
    const { step } = setup();
    const why = within(step).getByTestId("cv-notes-why");
    expect(why).toHaveTextContent("W screeningu nie ma „Dlaczego ten kandydat”");
    expect(within(why).getByRole("link", { name: "Uzupełnij w formularzu" })).toHaveAttribute("href", "/form");
  });

  it("same spacje liczą się jak puste pole", () => {
    formState.current = loaded("   ");
    const { step } = setup();
    expect(within(step).getByTestId("cv-notes-why")).toHaveTextContent("W screeningu nie ma");
  });

  it("wyłączone notatki w źródłach: nie obiecuje, że AI to przeczyta", () => {
    const { step } = setup({ notesSourceOn: false });
    const why = within(step).getByTestId("cv-notes-why");
    expect(why).toHaveTextContent("Prowadził wdrożenia magazynowe");
    expect(why).not.toHaveTextContent("AI przeczyta to przy generacji");
    expect(why).toHaveTextContent("AI tego nie przeczyta");
  });

  it("awaria odczytu nie udaje pustego pola i daje „Ponów”", async () => {
    const refetch = vi.fn();
    formState.current = { isPending: false, isError: true, isSuccess: false, data: undefined, refetch };
    const { step } = setup();
    expect(within(step).queryByText(/W screeningu nie ma/)).toBeNull();
    expect(within(step).getByRole("alert")).toHaveTextContent("Nie udało się wczytać");
    await userEvent.click(within(step).getByRole("button", { name: "Ponów" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("wczytywanie nie pokazuje braku ani obietnicy", () => {
    formState.current = { isPending: true, isError: false, isSuccess: false, data: undefined };
    const { step } = setup();
    expect(within(step).queryByText(/W screeningu nie ma/)).toBeNull();
    expect(within(step).queryByText(/AI przeczyta/)).toBeNull();
    expect(step).toHaveTextContent("Wczytuję");
  });

  it("po potwierdzeniu krok dalej mówi, że tekst wejdzie do CV", () => {
    const { step } = setup({ left: [] });
    expect(step).toHaveTextContent("nic do dodania");
    expect(step).toHaveTextContent("„Dlaczego ten kandydat” też wejdzie do CV");
  });

  it("po potwierdzeniu bez tekstu albo z wyłączonymi notatkami nie obiecuje", () => {
    formState.current = loaded(null);
    const empty = setup({ left: [] });
    expect(empty.step).not.toHaveTextContent("też wejdzie do CV");
    cleanup();

    formState.current = loaded("Tekst");
    const off = setup({ left: [], notesSourceOn: false });
    expect(off.step).not.toHaveTextContent("też wejdzie do CV");
  });
});
