import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OfferPage } from "@/components/career/site/OfferPage";
import type { CareerJobResponse } from "@/lib/career/api";

/* jsdom nie przenosi plików z `input.files` do `new FormData(form)` — nakładka na `FormData`. */
const NativeFormData = globalThis.FormData;
class BrowserLikeFormData extends NativeFormData {
  constructor(form?: HTMLFormElement) {
    super(form);
    if (!form) return;
    form.querySelectorAll<HTMLInputElement>('input[type="file"][name]').forEach((input) => {
      const file = input.files?.[0];
      if (file) this.set(input.name, file);
    });
  }
}

const fetchMock = vi.fn();
const json = (status: number, body: unknown = {}) =>
  ({ status, ok: status < 300, json: async () => body }) as unknown as Response;

const JOB: CareerJobResponse = {
  status: "open",
  recruiter: { first_name: "Marta", slug: "marta-n" },
  canonical_slug: "tester-ab12",
  job: {
    slug: "tester-ab12",
    title: "Tester automatyzujący",
    subtitle: "Testy aplikacji mobilnej",
    about: "Zespół rozwija aplikację mobilną.\n\nCzym się zajmiesz: pisanie testów; przegląd przypadków; raporty",
    must: [{ name: "Doświadczenie z Playwright", note: null }],
    nice: ["Znajomość Appium"],
    params: {
      city: "Kraków",
      remote_policy: "hybrid",
      onsite_days_per_week: 2,
      seniority: null,
      contract: "B2B",
      start: null,
      duration: null,
    },
    show: { must: true, nice: true, params: true, process: true },
  },
};

function renderPage() {
  return render(<OfferPage data={JOB} board={[]} base="" />);
}

/** Pełny formularz w rozdziale „Aplikuj” (w nagłówku stoi też szybka aplikacja). */
const full = (c: HTMLElement) => c.querySelector<HTMLElement>("#aplikuj")!;

function pickCv(container: HTMLElement, file: File) {
  const input = container.querySelector<HTMLInputElement>('input[name="cv"]')!;
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  fireEvent.change(input);
}

const pdf = () => new File([new Uint8Array(100)], "cv-anna.pdf", { type: "application/pdf" });
const submit = () => fireEvent.click(screen.getByRole("button", { name: "Wyślij zgłoszenie" }));
const consent = (c: HTMLElement) => fireEvent.click(c.querySelector('input[name="consent"]')!);

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("FormData", BrowserLikeFormData);
});
afterEach(() => vi.unstubAllGlobals());

describe("formularz oferty (plansze OfertaA i AplikacjaBledy)", () => {
  it("pusta wysyłka: lista rzeczy do poprawy, baner i nic nie idzie do API", () => {
    renderPage();
    submit();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 2, name: /2 rzeczy do poprawy, reszta została/ })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Sprawdź 2 pola oznaczone na czerwono.");
    expect(screen.getByText("Dodaj CV: PDF, DOC albo DOCX do 10 MB.")).toBeTruthy();
    expect(screen.getByText("Zaznacz zgodę, żeby wysłać zgłoszenie.")).toBeTruthy();
    expect(screen.getAllByText("Przejdź do pola")).toHaveLength(2);
  });

  it("zły typu pliku: komunikat nazywa rozszerzenie", () => {
    const { container } = renderPage();
    pickCv(full(container), new File(["x"], "portfolio.zip", { type: "application/zip" }));
    consent(full(container));
    submit();
    expect(screen.getByText("Ten plik to ZIP. CV musi być plikiem PDF, DOC albo DOCX do 10 MB.")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: /1 rzecz do poprawy/ })).toBeTruthy();
  });

  it("wysyła multipart na /apply z linkiem, CV i zgodą — bez imienia (czyta je serwer z CV)", async () => {
    fetchMock.mockResolvedValueOnce(json(201, { first_name: "Anna", email: "anna@example.com" }));
    const { container } = renderPage();
    pickCv(full(container), pdf());
    consent(full(container));
    submit();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/public\/career\/apply$/);
    const body = init.body as FormData;
    expect(body.get("link_slug")).toBe("tester-ab12");
    expect(body.get("consent")).toBe("true");
    expect(body.get("consent_future")).toBeNull();
    expect((body.get("cv") as File).name).toBe("cv-anna.pdf");
    expect(body.get("first_name")).toBeNull();
    // Ekran „Wysłane” (AplikacjaWyslana) z nazwą pliku i adresem z CV.
    expect(await screen.findByRole("heading", { level: 1, name: "CV jest u Marty." })).toBeTruthy();
    expect(screen.getByText("cv-anna.pdf")).toBeTruthy();
    expect(screen.getByText("anna@example.com")).toBeTruthy();
    expect(screen.getByText("Marta odezwie się po przejrzeniu CV. Nie musisz robić nic więcej.")).toBeTruthy();
  });

  it("CV bez e-maila (422 na `email`): pojawia się pole e-mail z komunikatem serwera", async () => {
    fetchMock.mockResolvedValueOnce(
      json(422, { detail: [{ loc: ["body", "email"], msg: "W CV nie znaleźliśmy adresu e-mail. Wpisz go." }] }),
    );
    const { container } = renderPage();
    expect(full(container).querySelector('input[name="email"]')).toBeNull();
    pickCv(full(container), pdf());
    consent(full(container));
    submit();
    expect(await within(full(container)).findByLabelText(/E-mail/)).toBeTruthy();
    expect(screen.getByText("W CV nie znaleźliśmy adresu e-mail. Wpisz go.")).toBeTruthy();
    // Puste pole e-mail przy ponownej próbie: komunikat z przeglądarki, bez wysyłki.
    submit();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Podaj adres e-mail.")).toBeTruthy();
  });

  it("awaria sieci: baner z powodem, wpisane dane zostają", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    const { container } = renderPage();
    pickCv(full(container), pdf());
    consent(full(container));
    submit();
    expect(await screen.findByText(/Brak połączenia/)).toBeTruthy();
    expect((full(container).querySelector('input[name="consent"]') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/Wpisane dane i plik zostają/)).toBeTruthy();
  });

  it("zamknięty link (404) mówi to wprost", async () => {
    fetchMock.mockResolvedValueOnce(json(404));
    const { container } = renderPage();
    pickCv(full(container), pdf());
    consent(full(container));
    submit();
    expect(await screen.findByText(/Link wygasł albo rekrutacja jest już zamknięta/)).toBeTruthy();
  });
});

describe("szybka aplikacja w nagłówku oferty: samo CV i „Wyślij CV”", () => {
  const quick = (c: HTMLElement) => c.querySelector<HTMLFormElement>("form[aria-label='Szybka aplikacja: samo CV']")!;

  it("CV i zgoda wystarczą: ta sama wysyłka, potem ekran „Wysłane”", async () => {
    fetchMock.mockResolvedValueOnce(json(201, { first_name: "Anna", email: "anna@example.com" }));
    const { container } = renderPage();
    pickCv(quick(container), pdf());
    consent(quick(container));
    fireEvent.click(within(quick(container)).getByRole("button", { name: "Wyślij CV" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = (fetchMock.mock.calls[0] as [string, RequestInit])[1].body as FormData;
    expect(body.get("link_slug")).toBe("tester-ab12");
    expect(body.get("consent")).toBe("true");
    expect((body.get("cv") as File).name).toBe("cv-anna.pdf");
    expect(await screen.findByRole("heading", { level: 1, name: "CV jest u Marty." })).toBeTruthy();
  });

  it("bez zgody nic nie wychodzi i mówi, czego brakuje", () => {
    const { container } = renderPage();
    pickCv(quick(container), pdf());
    fireEvent.click(within(quick(container)).getByRole("button", { name: "Wyślij CV" }));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(within(quick(container)).getByRole("alert").textContent).toContain("Zaznacz zgodę");
  });

  it("CV bez e-maila: pojawia się jedno pole e-mail", async () => {
    fetchMock.mockResolvedValueOnce(json(422, { detail: [{ loc: ["body", "email"], msg: "W CV nie znaleźliśmy adresu e-mail." }] }));
    const { container } = renderPage();
    pickCv(quick(container), pdf());
    consent(quick(container));
    fireEvent.click(within(quick(container)).getByRole("button", { name: "Wyślij CV" }));
    expect(await within(quick(container)).findByLabelText("E-mail")).toBeTruthy();
  });
});
