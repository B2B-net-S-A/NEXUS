import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CareerApplyForm, fieldsWord } from "@/components/career/CareerApplyForm";
import { CareerSubmitGate } from "@/components/career/CareerSubmitGate";

/*
 * jsdom nie przenosi plików z `input.files` do `new FormData(form)` — nakładka
 * dopisuje wybrany plik jak przeglądarka (wzór z testów ApplyForm).
 */
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

function jsonResponse(status: number, body: unknown = {}) {
  return { status, ok: status >= 200 && status < 300, json: async () => body } as unknown as Response;
}

function field(container: HTMLElement, name: string) {
  const el = container.querySelector<HTMLInputElement>(`[name="${name}"]`);
  if (!el) throw new Error(`missing field ${name}`);
  return el;
}

function pickCv(container: HTMLElement, file: File | null) {
  const input = field(container, "cv");
  Object.defineProperty(input, "files", { configurable: true, value: file ? [file] : [] });
  fireEvent.change(input);
}

const pdf = (name = "cv.pdf", size = 1024) =>
  new File([new Uint8Array(size)], name, { type: "application/pdf" });

function type(container: HTMLElement, name: string, value: string) {
  fireEvent.change(field(container, name), { target: { value } });
}

function fillValid(container: HTMLElement) {
  type(container, "first_name", "Jan");
  type(container, "last_name", "Kowalski");
  type(container, "email", "jan@example.com");
  pickCv(container, pdf());
  fireEvent.click(field(container, "consent"));
}

const submit = () => fireEvent.click(screen.getByRole("button", { name: /wyślij/ }));

function renderForm(props: Partial<Parameters<typeof CareerApplyForm>[0]> = {}) {
  return render(
    <CareerApplyForm linkSlug="senior-java-ab12" variant="job" rodoHref="/rodo" {...props} />,
  );
}

function lastBody(): FormData {
  return (fetchMock.mock.calls.at(-1) as [string, RequestInit])[1].body as FormData;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("FormData", BrowserLikeFormData);
  window.history.replaceState({}, "", "/r/senior-java-ab12");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CareerApplyForm — walidacja", () => {
  it("wymaga imienia, nazwiska, e-maila, CV i zgody — podsumowanie z liczbą pól", () => {
    const { container } = renderForm();
    submit();

    const summary = screen.getByRole("alert");
    expect(summary).toHaveTextContent("nie udało się wysłać — popraw 5 pól:");
    expect(summary).toHaveTextContent("imię · nazwisko · e-mail · cv · zgoda");
    expect(document.activeElement).toBe(summary);
    expect(screen.getByText(/wpisz imię/)).toBeInTheDocument();
    expect(screen.getByText(/dodaj CV — pdf, doc lub docx do 10 MB/)).toBeInTheDocument();
    expect(screen.getByText(/bez zgody nie możemy przyjąć zgłoszenia/)).toBeInTheDocument();
    expect(field(container, "email")).toHaveAttribute("aria-invalid", "true");
    expect(field(container, "consent")).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sama zgoda niezaznaczona blokuje wysyłkę", () => {
    const { container } = renderForm();
    fillValid(container);
    fireEvent.click(field(container, "consent"));
    submit();
    expect(screen.getByRole("alert")).toHaveTextContent("popraw 1 pole:");
    expect(screen.getByRole("alert")).toHaveTextContent("zgoda");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("łapie myślnik na końcu domeny, który zod przepuszcza", () => {
    const { container } = renderForm();
    fillValid(container);
    type(container, "email", "jan@firma-.pl");
    submit();
    expect(screen.getByText(/po @ nie może być myślnika/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("waliduje stawkę opcjonalną i złe CV", () => {
    const { container } = renderForm();
    fillValid(container);
    type(container, "expected_rate_hourly", "0");
    pickCv(container, new File(["x"], "cv.png", { type: "image/png" }));
    submit();
    expect(screen.getByText(/od 1 do 10 000 zł/)).toBeInTheDocument();
    expect(screen.getByText(/CV musi być plikiem pdf, doc lub docx/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("pułapka na boty jest ukryta przed ludźmi, Tabem i czytnikami", () => {
    const { container } = renderForm();
    const honeypot = field(container, "website");
    expect(honeypot).toHaveAttribute("tabindex", "-1");
    expect(honeypot).toHaveAttribute("autocomplete", "off");
    expect(honeypot.closest("[aria-hidden='true']")).not.toBeNull();
    expect(honeypot.closest(".kr-honeypot")).not.toBeNull();
    expect(screen.queryByRole("textbox", { name: /strona www/i })).toBeNull();
  });

  it("odmiana „pole/pola/pól”", () => {
    expect([1, 2, 4, 5, 12, 22, 25].map(fieldsWord)).toEqual([
      "pole",
      "pola",
      "pola",
      "pól",
      "pól",
      "pola",
      "pól",
    ]);
  });
});

describe("CareerApplyForm — wysyłka", () => {
  it("wysyła multipart z link_slug, zgodą, polami opcjonalnymi i UTM", async () => {
    window.history.replaceState(
      {},
      "",
      `/r/senior-java-ab12?utm_source=linkedin&utm_campaign=${"c".repeat(130)}`,
    );
    fetchMock.mockResolvedValue(jsonResponse(201, { ok: true, status: "received" }));
    const onSuccess = vi.fn();
    const { container } = renderForm({ onSuccess });
    fillValid(container);
    type(container, "expected_rate_hourly", "170.5");
    type(container, "availability_date", "2026-10-01");
    type(container, "city", "Warszawa");
    fireEvent.change(field(container, "work_mode"), { target: { value: "hybrid" } });
    submit();

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith({ firstName: "Jan", email: "jan@example.com" }));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/public\/career\/apply$/);
    expect(init.method).toBe("POST");
    expect(init.headers).toBeUndefined();
    const body = lastBody();
    expect(body.get("link_slug")).toBe("senior-java-ab12");
    expect(body.get("first_name")).toBe("Jan");
    expect(body.get("last_name")).toBe("Kowalski");
    expect(body.get("email")).toBe("jan@example.com");
    expect((body.get("cv") as File).name).toBe("cv.pdf");
    expect(body.get("consent")).toBe("true");
    expect(body.get("expected_rate_hourly")).toBe("170.5");
    expect(body.get("availability_date")).toBe("2026-10-01");
    expect(body.get("city")).toBe("Warszawa");
    expect(body.get("work_mode")).toBe("hybrid");
    expect(body.get("utm_source")).toBe("linkedin");
    expect(body.get("utm_campaign")).toBe("c".repeat(120));
    // Puste pola opcjonalne i pusty miodek nie jadą (backend dałby 422 na "").
    expect(body.get("website")).toBeNull();
  });

  it("puste pola opcjonalne nie są wysyłane, a tryb „dowolny” to brak preferencji", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201));
    const onSuccess = vi.fn();
    const { container } = renderForm({ onSuccess });
    fillValid(container);
    submit();
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const body = lastBody();
    for (const key of ["expected_rate_hourly", "availability_date", "city", "work_mode"]) {
      expect(body.get(key)).toBeNull();
    }
  });

  it("422 trafia przy polach, dane i plik zostają, przycisk „wyślij ponownie”", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(422, {
        detail: [
          { loc: ["body", "email"], msg: "value is not a valid email address" },
          { loc: ["body", "expected_rate_hourly"], msg: "Input should be less than or equal to 10000" },
        ],
      }),
    );
    const { container } = renderForm();
    fillValid(container);
    type(container, "expected_rate_hourly", "9999");
    submit();

    expect(await screen.findByText(/literówki/)).toBeInTheDocument();
    expect(screen.getByText(/Podaj stawkę godzinową netto od 1 do 10 000 zł/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("popraw 2 pola:");
    expect(field(container, "first_name").value).toBe("Jan");
    expect(field(container, "email").value).toBe("jan@example.com");
    expect(field(container, "consent").checked).toBe(true);
    expect(screen.getByText(/wpisane dane i plik zostają/)).toBeInTheDocument();

    fetchMock.mockResolvedValueOnce(jsonResponse(201));
    fireEvent.click(screen.getByRole("button", { name: /wyślij ponownie/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect((lastBody().get("cv") as File).name).toBe("cv.pdf");
  });

  it("422 na link_slug = link wygasł (w podsumowaniu, nie przy polu)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(422, { detail: [{ loc: ["body", "link_slug"], msg: "Field required" }] }),
    );
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(/link wygasł albo rekrutacja/);
  });

  it("404 → link wygasł / rekrutacja zamknięta", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404));
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "nie udało się wysłać — link wygasł albo rekrutacja jest już zamknięta",
    );
  });

  it("429 → komunikat o limicie prób", async () => {
    fetchMock.mockResolvedValue(jsonResponse(429));
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(/za dużo prób z tego adresu/);
  });

  it.each([
    [413, /CV jest większe niż 10 MB/],
    [415, /CV musi być plikiem pdf, doc lub docx/],
  ])("%i → błąd przy CV", async (status, message) => {
    fetchMock.mockResolvedValue(jsonResponse(status));
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("wyjątek sieci → brak połączenia, formularz aktywny", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const { container } = renderForm();
    fillValid(container);
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(/brak połączenia/);
    expect(screen.getByRole("button", { name: /wyślij ponownie/ })).toBeEnabled();
  });

  it("podgląd z wyłączoną wysyłką nie robi żadnego zapytania", () => {
    const { container } = renderForm({ preview: { disableSubmit: true } });
    fillValid(container);
    submit();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("po sukcesie bramka podmienia stronę na podziękowanie z imieniem i e-mailem", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201));
    const { container } = render(
      <CareerSubmitGate
        thanks={{
          variant: "job",
          recruiterFirstName: "Marta",
          jobHandle: "senior-java-developer",
          chromePath: "~/dynaminds/kariera",
          recruiterPageHref: "/marta-n",
          recruiterPageSlug: "marta-n",
        }}
      >
        <p>treść strony</p>
        <CareerApplyForm linkSlug="senior-java-ab12" variant="job" rodoHref="/rodo" />
      </CareerSubmitGate>,
    );
    fillValid(container);
    submit();
    expect(await screen.findByRole("heading", { name: /Dziękujemy, Jan\./ })).toBeInTheDocument();
    expect(screen.getByText(/jan@example\.com/)).toBeInTheDocument();
    expect(screen.getByText(/trafiła do Marty/)).toBeInTheDocument();
    expect(screen.queryByText("treść strony")).toBeNull();
  });
});
