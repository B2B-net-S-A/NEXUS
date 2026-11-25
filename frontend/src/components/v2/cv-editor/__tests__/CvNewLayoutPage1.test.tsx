import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import type { CvPage1Extras } from "@/lib/api";
import { CvEditorSection } from "@/lib/cv-editor-section";

import { CvNewLayoutPage1, chosenResult, verifiedResults } from "../CvNewLayoutPage1";

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

describe("Policz wyniki od nowa", () => {
  const apiError = (status: number, data: unknown) =>
    Object.assign(new Error(`Request failed with status code ${status}`), {
      isAxiosError: true,
      response: { status, data },
    });

  it("bez wołania serwera nie ma przycisku", () => {
    renderPage1();
    expect(screen.queryByRole("button", { name: /Policz wyniki od nowa/ })).toBeNull();
  });

  it("przycisk woła liczenie i blokuje się do końca", async () => {
    let finish: () => void = () => undefined;
    const onRecalcResults = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    renderPage1({ onRecalcResults });
    const button = screen.getByRole("button", { name: /Policz wyniki od nowa/ });
    await userEvent.click(button);
    expect(onRecalcResults).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Szukam wyników w CV");
    expect(screen.getByRole("button", { name: /Inny wynik/ })).toBeDisabled();
    await act(async () => finish());
    expect(button).toBeEnabled();
    expect(button).toHaveTextContent("Policz wyniki od nowa");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("awaria modelu (503) to zdanie serwera, nie surowy błąd", async () => {
    const detail = "Nie udało się teraz znaleźć wyniku w CV. Spróbuj ponownie za chwilę.";
    renderPage1({ onRecalcResults: vi.fn(async () => Promise.reject(apiError(503, { detail }))) });
    await userEvent.click(screen.getByRole("button", { name: /Policz wyniki od nowa/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
  });

  it("limit żądań (429) to prośba o odczekanie", async () => {
    const error = apiError(429, { error: "Rate limit exceeded: 20 per 1 minute" });
    renderPage1({ onRecalcResults: vi.fn(async () => Promise.reject(error)) });
    await userEvent.click(screen.getByRole("button", { name: /Policz wyniki od nowa/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("odczekaj minutę");
    expect(alert).not.toHaveTextContent("429");
  });
});
