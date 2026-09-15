import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ApplyForm from "@/app/apply/[token]/ApplyForm";

/*
 * jsdom nie przenosi plików wybranych przez `input.files` do `new FormData(form)`
 * (zawsze wstawia pusty File — dokładnie jak przeglądarka przy braku wyboru).
 * Nakładka dopisuje wybrany plik tak, jak zrobiłaby to przeglądarka. Pusty
 * wybór zostaje pustym Filem, więc ścieżka „brak CV” jest testowana uczciwie.
 */
const NativeFormData = globalThis.FormData;
class BrowserLikeFormData extends NativeFormData {
  constructor(form?: HTMLFormElement) {
    super(form);
    if (!form) return;
    form
      .querySelectorAll<HTMLInputElement>('input[type="file"][name]')
      .forEach((input) => {
        const file = input.files?.[0];
        if (file) this.set(input.name, file);
      });
  }
}

const fetchMock = vi.fn();

function jsonResponse(status: number, body: unknown = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  } as unknown as Response;
}

function field(container: HTMLElement, name: string) {
  const el = container.querySelector<HTMLInputElement>(`[name="${name}"]`);
  if (!el) throw new Error(`missing field ${name}`);
  return el;
}

function pickCv(container: HTMLElement, file: File | null) {
  const input = field(container, "cv");
  Object.defineProperty(input, "files", {
    configurable: true,
    value: file ? [file] : [],
  });
  fireEvent.change(input);
}

function pdf(name = "cv.pdf", size = 1024) {
  return new File([new Uint8Array(size)], name, { type: "application/pdf" });
}

function fillValid(container: HTMLElement) {
  fireEvent.change(field(container, "first_name"), { target: { value: "Anna" } });
  fireEvent.change(field(container, "last_name"), { target: { value: "Nowak" } });
  fireEvent.change(field(container, "email"), {
    target: { value: "anna@example.com" },
  });
  pickCv(container, pdf());
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Wyślij zgłoszenie" }));
}

function renderForm() {
  return render(<ApplyForm token="tok-123" recruiterFirstName="Kasia" />);
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("FormData", BrowserLikeFormData);
  window.history.replaceState({}, "", "/apply/tok-123");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ApplyForm — walidacja", () => {
  it("pokazuje komunikaty zod dla pustych i błędnych pól i nie wysyła", () => {
    const { container } = renderForm();
    fireEvent.change(field(container, "email"), { target: { value: "nie-email" } });
    fireEvent.change(field(container, "phone"), { target: { value: "abc" } });
    fireEvent.change(field(container, "linkedin"), {
      target: { value: "linkedin.com/in/anna" },
    });
    pickCv(container, pdf());

    submit();

    expect(screen.getByText("Imię jest wymagane")).toBeInTheDocument();
    expect(screen.getByText("Nazwisko jest wymagane")).toBeInTheDocument();
    expect(screen.getByText("Nieprawidłowy email")).toBeInTheDocument();
    expect(screen.getByText("Nieprawidłowy format telefonu")).toBeInTheDocument();
    expect(
      screen.getByText("LinkedIn URL musi zaczynać się od https://"),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("przyjmuje poprawny telefon i LinkedIn z http://", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201));
    const { container } = renderForm();
    fillValid(container);
    fireEvent.change(field(container, "phone"), {
      target: { value: "+48 (12) 345-67-89" },
    });
    fireEvent.change(field(container, "linkedin"), {
      target: { value: "http://linkedin.com/in/anna" },
    });

    submit();

    expect(await screen.findByText("Dziękujemy!")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("wymaga CV przy wysyłce bez wybranego pliku", () => {
    const { container } = renderForm();
    fireEvent.change(field(container, "first_name"), { target: { value: "Anna" } });
    fireEvent.change(field(container, "last_name"), { target: { value: "Nowak" } });
    fireEvent.change(field(container, "email"), {
      target: { value: "anna@example.com" },
    });

    submit();

    expect(
      screen.getByText("Dodaj swoje CV (PDF, DOC lub DOCX)."),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("waliduje CV już przy wyborze pliku: rozszerzenie, rozmiar, brak", () => {
    const { container } = renderForm();

    pickCv(container, new File(["x"], "cv.png", { type: "image/png" }));
    expect(
      screen.getByText("CV musi być w formacie PDF, DOC lub DOCX."),
    ).toBeInTheDocument();

    pickCv(container, pdf("cv.docx", 10 * 1024 * 1024 + 1));
    expect(screen.getByText("CV jest większe niż 10 MB.")).toBeInTheDocument();
    expect(
      screen.queryByText("CV musi być w formacie PDF, DOC lub DOCX."),
    ).toBeNull();

    pickCv(container, null);
    expect(
      screen.getByText("Dodaj swoje CV (PDF, DOC lub DOCX)."),
    ).toBeInTheDocument();

    pickCv(container, pdf("CV_Anna.DOC"));
    expect(screen.queryByText(/CV musi być|CV jest większe|Dodaj swoje CV/)).toBeNull();
    expect(screen.getByText("CV_Anna.DOC")).toBeInTheDocument();
  });

  it("blokuje wysyłkę zbyt dużego CV", () => {
    const { container } = renderForm();
    fillValid(container);
    pickCv(container, pdf("cv.pdf", 10 * 1024 * 1024 + 1));

    submit();

    expect(screen.getByText("CV jest większe niż 10 MB.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("ApplyForm — wysyłka", () => {
  it("wysyła FormData na publiczny endpoint z UTM odczytanymi raz i przyciętymi do 120 znaków", async () => {
    const longCampaign = "c".repeat(130);
    window.history.replaceState(
      {},
      "",
      `/apply/tok-123?utm_source=linkedin&utm_campaign=${longCampaign}&utm_foo=nie`,
    );
    fetchMock.mockResolvedValue(jsonResponse(201));
    const { container } = renderForm();
    // Zmiana adresu po zamontowaniu nie może nadpisać first-touch UTM.
    window.history.replaceState({}, "", "/apply/tok-123?utm_source=inne");
    fillValid(container);

    submit();

    await screen.findByText("Dziękujemy!");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/public\/apply\/tok-123$/);
    expect(init.method).toBe("POST");
    // Publiczny endpoint: bez nagłówka Authorization.
    expect(init.headers).toBeUndefined();
    const body = init.body as FormData;
    expect(body.get("first_name")).toBe("Anna");
    expect(body.get("email")).toBe("anna@example.com");
    expect((body.get("cv") as File).name).toBe("cv.pdf");
    expect(body.get("utm_source")).toBe("linkedin");
    expect(body.get("utm_campaign")).toBe("c".repeat(120));
    expect(body.get("utm_foo")).toBeNull();
    expect(body.get("utm_medium")).toBeNull();
    expect(screen.getByText(/Kasia otrzyma Twoje zgłoszenie/)).toBeInTheDocument();
  });

  it("blokuje pola i przycisk w trakcie wysyłki", async () => {
    let resolve!: (r: Response) => void;
    fetchMock.mockReturnValue(new Promise<Response>((r) => (resolve = r)));
    const { container } = renderForm();
    fillValid(container);

    submit();

    const button = await screen.findByRole("button", { name: /Wysyłanie/ });
    expect(button).toBeDisabled();
    for (const name of ["first_name", "last_name", "email", "phone", "linkedin", "cv", "message"]) {
      expect(field(container, name)).toBeDisabled();
    }

    await act(async () => resolve(jsonResponse(201)));
    expect(await screen.findByText("Dziękujemy!")).toBeInTheDocument();
  });

  it("404 → komunikat o wygasłym linku", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404));
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(
      await screen.findByText("Link wygasł lub został wycofany. Poproś o nowy."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyślij zgłoszenie" })).toBeEnabled();
  });

  it.each([
    [413, "CV jest większe niż 10 MB."],
    [415, "CV musi być w formacie PDF, DOC lub DOCX."],
  ])("%i → błąd przy polu CV i powrót do edycji", async (status, message) => {
    fetchMock.mockResolvedValue(jsonResponse(status));
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(await screen.findByText(message)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Wyślij zgłoszenie" });
    expect(button).toBeEnabled();
    expect(field(container, "first_name")).toBeEnabled();
  });

  it("429 → komunikat o limicie prób", async () => {
    fetchMock.mockResolvedValue(jsonResponse(429));
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(
      await screen.findByText(
        "Zbyt wiele prób z tego adresu IP. Spróbuj ponownie za kilka minut.",
      ),
    ).toBeInTheDocument();
  });

  it("inny status → body.detail z backendu", async () => {
    fetchMock.mockResolvedValue(jsonResponse(400, { detail: "Kandydat już aplikował." }));
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(await screen.findByText("Kandydat już aplikował.")).toBeInTheDocument();
  });

  it("inny status bez czytelnego body → komunikat ogólny", async () => {
    fetchMock.mockResolvedValue({
      status: 500,
      ok: false,
      json: async () => {
        throw new SyntaxError("not json");
      },
    } as unknown as Response);
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(
      await screen.findByText("Coś poszło nie tak. Spróbuj ponownie."),
    ).toBeInTheDocument();
  });

  it("wyjątek sieci → Brak połączenia, formularz znów aktywny", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(
      await screen.findByText("Brak połączenia. Sprawdź internet i spróbuj ponownie."),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Wyślij zgłoszenie" })).toBeEnabled(),
    );
  });
});
