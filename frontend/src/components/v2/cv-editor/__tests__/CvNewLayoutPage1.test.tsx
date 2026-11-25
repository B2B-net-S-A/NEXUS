import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import type { CvPage1Extras } from "@/lib/api";
import { CvEditorSection } from "@/lib/cv-editor-section";

import { CvNewLayoutPage1, RESULT_SAVE_DELAY_MS, chosenResult, verifiedResults } from "../CvNewLayoutPage1";

const CV =
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' +
  "<ul><li><p>Ponad <strong>7 lat</strong> w Javie.</p></li><li><p>Mikroserwisy w <strong>Spring Boot</strong>.</p></li>" +
  "<li><p>Trzeci punkt z CV.</p></li></ul>" +
  '<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2><p><strong>Języki: </strong>Java</p>' +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Java Developer</strong> 01.2017 – 02.2021</p>' +
  '<p data-cv-section="employer">Software House Przykład</p>';

const EXTRAS: CvPage1Extras = {
  result_index: 0,
  results: [
    { text: "Skrócił testy o 40%.", company: "Firma Przykładowa A", verified: true },
    { text: "Wymyślony wynik.", company: "Firma B", verified: false },
    { text: "Wdrożył 120 testów API.", company: "Firma Przykładowa C", verified: true },
  ],
};

const editors: Editor[] = [];

function open(): Editor {
  const editor = new Editor({ extensions: [StarterKit, CvEditorSection], content: CV });
  editors.push(editor);
  return editor;
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
  vi.useRealTimers();
});

function renderPage1(overrides: Partial<Parameters<typeof CvNewLayoutPage1>[0]> = {}) {
  const editor = open();
  const props = {
    editor,
    extras: EXTRAS,
    disabled: false,
    onSaveResult: vi.fn(async () => undefined),
    onOpenPositions: vi.fn(),
    onOpenText: vi.fn(),
    ...overrides,
  };
  render(<CvNewLayoutPage1 {...props} />);
  return { editor, props };
}

describe("wybór wyniku", () => {
  it("na liście są tylko sprawdzone wyniki; wybrany = result_index, gdy sprawdzony", () => {
    expect(verifiedResults(EXTRAS).map((choice) => choice.index)).toEqual([0, 2]);
    expect(chosenResult(EXTRAS)?.result.text).toBe("Skrócił testy o 40%.");
    expect(chosenResult({ ...EXTRAS, result_index: 1 })).toBeNull();
    expect(chosenResult({ results: [] })).toBeNull();
  });
});

const GENERATED: CvPage1Extras = {
  ...EXTRAS,
  why: ["**9 lat** w IT, w tym **5 lat** jako Java Developer.", "", "Migracja płatności do chmury w Firmie A."],
  why_generated: [
    { slot: "experience", text: "**9 lat** w IT, w tym **5 lat** jako Java Developer.", verified: true },
    { slot: "requirements", text: "Z wymagań klienta: Java.", verified: false, issue: "label" },
    {
      slot: "key_task",
      text: "Migracja płatności do chmury w Firmie A.",
      verified: true,
      source: "screening",
      quote: "przenieśliśmy płatności do chmury",
    },
  ],
};

describe("Strona 1", () => {
  it("pola 1–3 pokazują zdania strony 1: sprawdzone z generatora, pusty slot = punkt z CV", () => {
    renderPage1({ extras: GENERATED });
    expect(screen.getByLabelText("1 · Doświadczenie")).toHaveValue("9 lat w IT, w tym 5 lat jako Java Developer.");
    expect(screen.getByText("Z generatora · lata policzone z dat stanowisk")).toBeInTheDocument();
    expect(screen.getByLabelText("2 · Wymagania klienta")).toHaveValue("Mikroserwisy w Spring Boot.");
    expect(
      screen.getByText("Zdanie z generatora nie przeszło sprawdzenia z CV — strona 1 bierze punkt 2 z CV."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("3 · Najważniejsze zadanie")).toHaveValue("Migracja płatności do chmury w Firmie A.");
    expect(screen.getByText("Z generatora · dowód z odpowiedzi kandydata na screeningu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Przywróć z generatora/ })).not.toBeInTheDocument();
  });

  it("pole nie zmienia treści CV — zdanie idzie do dodatków strony 1, jeden slot naraz", async () => {
    const { editor, props } = renderPage1({ extras: GENERATED });
    const before = editor.getHTML();
    const first = screen.getByLabelText("1 · Doświadczenie");
    fireEvent.change(first, { target: { value: "Ponad 9 lat w IT." } });
    fireEvent.blur(first);
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ why: ["Ponad 9 lat w IT.", null, null] }));
    expect(editor.getHTML()).toBe(before);
  });

  it("pusty slot pokazuje punkt z kartki i jego zmianę (np. cofnięcie)", () => {
    const { editor } = renderPage1({ extras: null });
    expect(screen.getByLabelText("2 · Wymagania klienta")).toHaveValue("Mikroserwisy w Spring Boot.");
    act(() => {
      editor.commands.insertContentAt(editor.state.doc.content.size, "<p>koniec</p>");
      editor.commands.undo();
    });
    expect(screen.getByLabelText("2 · Wymagania klienta")).toHaveValue("Mikroserwisy w Spring Boot.");
  });

  it("podpowiedź lat z dat stanowisk pod polem 1", () => {
    renderPage1();
    expect(screen.getByText("Z dat stanowisk: 4 lata 2 mies.")).toBeInTheDocument();
  });

  it("slot 3 bez zdania bierze najmocniejszy wynik z CV", () => {
    renderPage1();
    expect(screen.getByLabelText("3 · Najważniejsze zadanie")).toHaveValue("Skrócił testy o 40%.");
    expect(screen.getByText("Najmocniejszy wynik z CV")).toBeInTheDocument();
  });

  it("poprawione zdanie ma „Przywróć z generatora”, które czyści slot", async () => {
    const edited: CvPage1Extras = { ...GENERATED, why: ["Moje zdanie.", "", GENERATED.why?.[2] ?? ""] };
    const { props } = renderPage1({ extras: edited });
    expect(screen.getByText("Wpisane ręcznie · tylko w nowym CV")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Przywróć z generatora/ }));
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ why: ["", null, null] }));
  });

  it("„Przywróć” prosto z pisania w polu: wygrywa zdanie z generatora, bez zapisu poprawki", async () => {
    const edited: CvPage1Extras = { ...GENERATED, why: ["Moje zdanie.", "", GENERATED.why?.[2] ?? ""] };
    const { props } = renderPage1({ extras: edited });
    const field = screen.getByLabelText("1 · Doświadczenie");
    fireEvent.change(field, { target: { value: "Jeszcze inaczej." } });
    const restoreButton = screen.getByRole("button", { name: /Przywróć z generatora/ });
    // Klik nie zabiera fokusu z pola, więc wyjście z pola nie wysyła poprawki.
    expect(fireEvent.mouseDown(restoreButton)).toBe(false);
    fireEvent.click(restoreButton);
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ why: ["", null, null] }));
    expect(props.onSaveResult).toHaveBeenCalledTimes(1);
  });

  it("wyczyszczone pole = z generatora (pusty slot)", async () => {
    const { props } = renderPage1({ extras: GENERATED });
    const field = screen.getByLabelText("3 · Najważniejsze zadanie");
    fireEvent.change(field, { target: { value: "  " } });
    fireEvent.blur(field);
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ why: [null, null, ""] }));
  });

  it("zapis po przerwie w pisaniu, bez wyjścia z pola", async () => {
    vi.useFakeTimers();
    const { props } = renderPage1();
    fireEvent.change(screen.getByLabelText("2 · Wymagania klienta"), { target: { value: "Java w Firmie A." } });
    expect(props.onSaveResult).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(RESULT_SAVE_DELAY_MS);
    });
    expect(props.onSaveResult).toHaveBeenCalledWith({ why: [null, "Java w Firmie A.", null] });
  });

  it("„Wynik z CV (2)” wstawia sprawdzony wynik do slotu 3", async () => {
    const user = userEvent.setup();
    const { props } = renderPage1();
    await user.click(screen.getByRole("button", { name: "Wynik z CV (2)" }));
    expect(screen.queryByText("Wymyślony wynik.")).not.toBeInTheDocument();
    await user.click(await screen.findByRole("menuitem", { name: /Wdrożył 120 testów API/ }));
    await waitFor(() =>
      expect(props.onSaveResult).toHaveBeenCalledWith({ why: [null, null, "Wdrożył 120 testów API."] }),
    );
  });

  it("wybór wieńca zapisuje się w dodatkach strony 1 (23.11.2026)", async () => {
    const user = userEvent.setup();
    const { props } = renderPage1({ extras: { ...EXTRAS, wreath: "school" } });
    expect(screen.getByRole("button", { name: "Szkoła" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Certyfikat" }));
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ wreath: "cert" }));
  });

  it("błąd zapisu zdania mówi po polsku, co się stało", async () => {
    const onSaveResult = vi.fn(async () => {
      throw { response: { status: 409, data: { detail: "CV jest już u klienta — układu nie zmienisz." } } };
    });
    renderPage1({ onSaveResult });
    const field = screen.getByLabelText("3 · Najważniejsze zadanie");
    fireEvent.change(field, { target: { value: "Nowe zdanie." } });
    fireEvent.blur(field);
    expect(await screen.findByRole("alert")).toHaveTextContent("CV jest już u klienta");
  });

  it("bez dodatków pola pokazują punkty z CV, a rekrutacja bez zadania mówi o tym", () => {
    renderPage1({
      extras: {
        why_generated: [
          { slot: "experience", text: "", verified: false, issue: "empty" },
          { slot: "requirements", text: "", verified: false, issue: "no_input" },
          { slot: "key_task", text: "", verified: false, issue: "no_input" },
        ],
      },
    });
    expect(screen.getByLabelText("3 · Najważniejsze zadanie")).toHaveValue("Trzeci punkt z CV.");
    expect(screen.getByText("Punkt 1 z treści CV (wspólny z Wordem)")).toBeInTheDocument();
    expect(screen.getByText(/Profil Championa nie ma wymagań MUST/)).toBeInTheDocument();
    expect(screen.getByText(/Rekrutacja nie ma „Najważniejszego zadania”/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Wynik z CV/ })).not.toBeInTheDocument();
  });

  it("„Ułóż zdania od nowa” woła generator strony 1, błąd po polsku", async () => {
    const onRefreshWhy = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce({ response: { status: 503, data: { detail: "Nie udało się teraz znaleźć wyniku." } } });
    renderPage1({ onRefreshWhy });
    fireEvent.click(screen.getByRole("button", { name: "Ułóż zdania od nowa" }));
    await waitFor(() => expect(onRefreshWhy).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole("button", { name: "Ułóż zdania od nowa" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się teraz znaleźć wyniku.");
  });

  it("zwinięte wiersze prowadzą do stanowisk i do sekcji w „Cały tekst”", () => {
    const { props } = renderPage1();
    fireEvent.click(screen.getByRole("button", { name: /Przebieg kariery/ }));
    expect(props.onOpenPositions).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Umiejętności/ }));
    expect(props.onOpenText).toHaveBeenCalledWith("skills");
    expect(screen.getByRole("button", { name: /Przebieg kariery/ })).toHaveTextContent("1 firma na osi");
  });

  it("zablokowany formularz (zapis, asystent) nie zmienia CV", () => {
    renderPage1({ disabled: true });
    expect(screen.getByLabelText("1 · Doświadczenie")).toBeDisabled();
    expect(screen.getByLabelText("3 · Najważniejsze zadanie")).toBeDisabled();
  });

  it("CV bez dodatków strony 1 (bez etapu) edytuje punkty w treści CV, jak w Wordzie", () => {
    const { editor } = renderPage1({ onSaveResult: undefined });
    fireEvent.change(screen.getByLabelText("1 · Doświadczenie"), { target: { value: "Ponad 7 lat w Javie i Kotlinie." } });
    expect(editor.getHTML()).toContain("<li><p>Ponad <strong>7 lat</strong> w Javie i Kotlinie.</p></li>");
  });
});

describe("Wyróżnik (25.11.2026)", () => {
  it("domyślnie „Automatycznie” z opisem wcześniejszej pracy u klienta", () => {
    renderPage1();
    expect(screen.getByRole("radio", { name: "Automatycznie" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/Doświadczenie w PKO BP · 2018–2023/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Etykieta")).not.toBeInTheDocument();
  });

  it("„Bez wyróżnika” zapisuje się od razu", async () => {
    const user = userEvent.setup();
    const { props } = renderPage1();
    await user.click(screen.getByRole("radio", { name: "Bez wyróżnika" }));
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ highlight: { mode: "off" } }));
    expect(screen.getByRole("radio", { name: "Bez wyróżnika" })).toHaveAttribute("aria-checked", "true");
  });

  it("„Własny” nie zapisuje się bez etykiety i zdania, a po uzupełnieniu wysyła komplet", async () => {
    vi.useFakeTimers();
    const { props } = renderPage1();
    fireEvent.click(screen.getByRole("radio", { name: "Własny" }));
    fireEvent.change(screen.getByLabelText("Etykieta"), { target: { value: "Wyróżnienie" } });
    fireEvent.change(screen.getByLabelText("Znak w wieńcu"), { target: { value: "2015" } });
    await act(async () => {
      vi.advanceTimersByTime(RESULT_SAVE_DELAY_MS);
    });
    expect(props.onSaveResult).not.toHaveBeenCalled();
    expect(screen.getByText("Uzupełnij etykietę i zdanie — wtedy wyróżnik się zapisze.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Zdanie"), {
      target: { value: "Best IT Project Manager klastra bałtyckiego Nordea za inicjatywę KYC. " },
    });
    await act(async () => {
      vi.advanceTimersByTime(RESULT_SAVE_DELAY_MS - 1);
    });
    expect(props.onSaveResult).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(props.onSaveResult).toHaveBeenCalledTimes(1);
    expect(props.onSaveResult).toHaveBeenCalledWith({
      highlight: {
        mode: "custom",
        label: "Wyróżnienie",
        token: "2015",
        text: "Best IT Project Manager klastra bałtyckiego Nordea za inicjatywę KYC.",
      },
    });
  });

  it("zapisany „Własny” wypełnia pola, pokazuje liczniki i pilnuje limitów", () => {
    renderPage1({
      extras: { ...EXTRAS, highlight: { mode: "custom", label: "Wyróżnienie", token: "PMP", text: "Zdanie." } },
    });
    expect(screen.getByRole("radio", { name: "Własny" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByLabelText("Etykieta")).toHaveValue("Wyróżnienie");
    expect(screen.getByLabelText("Etykieta")).toHaveAttribute("maxLength", "60");
    expect(screen.getByLabelText("Znak w wieńcu")).toHaveAttribute("maxLength", "8");
    expect(screen.getByLabelText("Zdanie")).toHaveAttribute("maxLength", "160");
    expect(screen.getByText("11/60")).toBeInTheDocument();
    expect(screen.getByText("3/8")).toBeInTheDocument();
  });

  it("pusty znak w wieńcu idzie jako null", async () => {
    const { props } = renderPage1();
    fireEvent.click(screen.getByRole("radio", { name: "Własny" }));
    fireEvent.change(screen.getByLabelText("Etykieta"), { target: { value: " Wyróżnienie " } });
    fireEvent.change(screen.getByLabelText("Zdanie"), { target: { value: "Zdanie." } });
    fireEvent.blur(screen.getByLabelText("Zdanie"));
    await waitFor(() =>
      expect(props.onSaveResult).toHaveBeenCalledWith({
        highlight: { mode: "custom", label: "Wyróżnienie", token: null, text: "Zdanie." },
      }),
    );
  });

  it("błąd zapisu pokazuje komunikat z API i wraca do zapisanego trybu", async () => {
    const user = userEvent.setup();
    const onSaveResult = vi.fn(async () => {
      throw { response: { status: 422, data: { detail: "Wyróżnik „Własny” wymaga etykiety i zdania." } } };
    });
    renderPage1({ onSaveResult });
    await user.click(screen.getByRole("radio", { name: "Bez wyróżnika" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wyróżnik „Własny” wymaga etykiety i zdania.");
    expect(screen.getByRole("radio", { name: "Automatycznie" })).toHaveAttribute("aria-checked", "true");
  });

  it("zablokowany formularz blokuje wybór i pola wyróżnika", () => {
    renderPage1({
      disabled: true,
      extras: { ...EXTRAS, highlight: { mode: "custom", label: "Wyróżnienie", text: "Zdanie." } },
    });
    expect(screen.getByRole("radio", { name: "Bez wyróżnika" })).toBeDisabled();
    expect(screen.getByLabelText("Etykieta")).toBeDisabled();
    expect(screen.getByLabelText("Zdanie")).toBeDisabled();
  });
});
