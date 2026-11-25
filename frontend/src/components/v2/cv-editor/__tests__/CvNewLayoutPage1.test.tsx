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

describe("Strona 1", () => {
  it("punkty 1–2 to punkty „Dlaczego” w dokumencie edytora — pogrubienie zostaje", () => {
    const { editor } = renderPage1();
    const first = screen.getByLabelText("1 · Lata doświadczenia");
    expect(first).toHaveValue("Ponad 7 lat w Javie.");
    expect(screen.getByLabelText("2 · Technologie")).toHaveValue("Mikroserwisy w Spring Boot.");
    fireEvent.change(first, { target: { value: "Ponad 7 lat w Javie i Kotlinie." } });
    expect(editor.getHTML()).toContain("<li><p>Ponad <strong>7 lat</strong> w Javie i Kotlinie.</p></li>");
    expect(screen.getByLabelText("1 · Lata doświadczenia")).toHaveValue("Ponad 7 lat w Javie i Kotlinie.");
  });

  it("zmiana kartki (np. cofnięcie) od razu widać w polu", () => {
    const { editor } = renderPage1();
    fireEvent.change(screen.getByLabelText("2 · Technologie"), { target: { value: "Inny punkt." } });
    act(() => {
      editor.commands.undo();
    });
    expect(screen.getByLabelText("2 · Technologie")).toHaveValue("Mikroserwisy w Spring Boot.");
  });

  it("podpowiedź lat z dat stanowisk pod punktem 1", () => {
    renderPage1();
    expect(screen.getByText("Z dat stanowisk: 4 lata 2 mies.")).toBeInTheDocument();
  });

  it("najmocniejszy wynik: wybrany z listy, źródło to firma", () => {
    renderPage1();
    expect(screen.getByLabelText("3 · Najmocniejszy wynik")).toHaveValue("Skrócił testy o 40%.");
    expect(screen.getByText("Źródło: Firma Przykładowa A, zakres zadań")).toBeInTheDocument();
  });

  it("wpisany wynik zapisuje się jako zdanie rekrutera po wyjściu z pola", async () => {
    const { props } = renderPage1();
    const field = screen.getByLabelText("3 · Najmocniejszy wynik");
    fireEvent.change(field, { target: { value: "Obniżył liczbę defektów o 30%." } });
    fireEvent.blur(field);
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ result_text: "Obniżył liczbę defektów o 30%." }));
    // Treść CV się nie zmienia — wynik to dodatek nowego CV.
    expect(props.editor.getHTML()).not.toContain("defektów");
  });

  it("wyczyszczone pole = brak zdania rekrutera", async () => {
    const { props } = renderPage1({ extras: { ...EXTRAS, result_text: "Wpisane." } });
    expect(screen.getByText("Źródło: wpisane ręcznie · tylko w nowym CV")).toBeInTheDocument();
    const field = screen.getByLabelText("3 · Najmocniejszy wynik");
    fireEvent.change(field, { target: { value: "  " } });
    fireEvent.blur(field);
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ result_text: null }));
  });

  it("„Inny wynik (2)” wybiera sprawdzony wynik i czyści wpisane zdanie", async () => {
    const user = userEvent.setup();
    const { props } = renderPage1();
    await user.click(screen.getByRole("button", { name: "Inny wynik (2)" }));
    expect(screen.queryByText("Wymyślony wynik.")).not.toBeInTheDocument();
    await user.click(await screen.findByRole("menuitem", { name: /Wdrożył 120 testów API/ }));
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ result_index: 2, result_text: null }));
  });

  it("wybór wieńca zapisuje się w dodatkach strony 1 (23.11.2026)", async () => {
    const user = userEvent.setup();
    const { props } = renderPage1({ extras: { ...EXTRAS, wreath: "school" } });
    expect(screen.getByRole("button", { name: "Szkoła" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Certyfikat" }));
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ wreath: "cert" }));
  });

  it("błąd zapisu wyniku mówi po polsku, co się stało", async () => {
    const onSaveResult = vi.fn(async () => {
      throw { response: { status: 409, data: { detail: "CV jest już u klienta — układu nie zmienisz." } } };
    });
    renderPage1({ onSaveResult });
    const field = screen.getByLabelText("3 · Najmocniejszy wynik");
    fireEvent.change(field, { target: { value: "Nowy wynik." } });
    fireEvent.blur(field);
    expect(await screen.findByRole("alert")).toHaveTextContent("CV jest już u klienta");
  });

  it("bez wyników i zdania pole pokazuje punkt 3 z CV jako podpowiedź", () => {
    renderPage1({ extras: null });
    expect(screen.getByLabelText("3 · Najmocniejszy wynik")).toHaveValue("");
    expect(screen.getByLabelText("3 · Najmocniejszy wynik")).toHaveAttribute(
      "placeholder",
      "Punkt 3 z CV: Trzeci punkt z CV.",
    );
    expect(screen.queryByRole("button", { name: /Inny wynik/ })).not.toBeInTheDocument();
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
    expect(screen.getByLabelText("1 · Lata doświadczenia")).toBeDisabled();
    expect(screen.getByLabelText("3 · Najmocniejszy wynik")).toBeDisabled();
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
