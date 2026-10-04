/**
 * Hiring manager: osoba z kontaktów klienta albo wpisana ręcznie (25.09.2026).
 * Ostatnia pozycja listy dodaje wpisaną osobę; ta sama osoba wpisana inaczej
 * nie dostaje przycisku „Dodaj” (serwer i tak by ją dopasował).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => mocks.get(...a),
    put: (...a: unknown[]) => mocks.put(...a),
  },
}));

import { HiringManagerCombobox } from "@/components/jobs/HiringManagerCombobox";
import { HiringManagerPicker } from "@/components/jobs/HiringManagerPicker";
import {
  filterHiringManagerOptions,
  hiringManagerRequestBody,
  personNameKey,
  sameContact,
  type HiringManagerChoice,
} from "@/lib/hiring-manager";

const OPTIONS = [
  { id: 1, name: "Łukasz Żółkiewski", position: "Dyrektor IT" },
  { id: 2, name: "Ewa Mazur", position: null },
];

function renderCombobox(
  props: Partial<{ clientId: number | null; value: HiringManagerChoice | null }> = {},
) {
  const onChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <span id="hm-label">Hiring manager</span>
      <HiringManagerCombobox
        clientId={"clientId" in props ? props.clientId! : 7}
        value={props.value ?? null}
        onChange={onChange}
        labelledBy="hm-label"
      />
    </QueryClientProvider>,
  );
  return onChange;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({ data: OPTIONS });
});

describe("lib/hiring-manager", () => {
  it("klucz osoby ignoruje kolejność, wielkość liter i polskie znaki", () => {
    expect(personNameKey("Łukasz Żółkiewski")).toBe(personNameKey("zolkiewski  LUKASZ"));
    expect(sameContact(OPTIONS, "zolkiewski lukasz")?.id).toBe(1);
    expect(sameContact(OPTIONS, "Łukasz")).toBeNull();
  });

  it("filtruje po początku każdego słowa, także stanowiska", () => {
    expect(filterHiringManagerOptions(OPTIONS, "luk").map((o) => o.id)).toEqual([1]);
    expect(filterHiringManagerOptions(OPTIONS, "dyrek").map((o) => o.id)).toEqual([1]);
    expect(filterHiringManagerOptions(OPTIONS, "")).toHaveLength(2);
  });

  it("buduje dokładnie jedno z trzech ciał żądania", () => {
    expect(hiringManagerRequestBody(null)).toEqual({ clear: true });
    expect(hiringManagerRequestBody({ kind: "contact", id: 2, name: "Ewa" })).toEqual({
      contact_id: 2,
    });
    expect(
      hiringManagerRequestBody({ kind: "new", name: " Jan Nowy ", position: "", email: null }),
    ).toEqual({ new_person: { name: "Jan Nowy", position: null, email: null } });
  });

  it("„Klient nie podał” wygrywa z wyborem osoby (04.10.2026)", () => {
    expect(hiringManagerRequestBody(null, true)).toEqual({ not_provided: true });
    expect(hiringManagerRequestBody({ kind: "contact", id: 2, name: "Ewa" }, true)).toEqual({
      not_provided: true,
    });
    expect(hiringManagerRequestBody({ kind: "contact", id: 2, name: "Ewa" }, false)).toEqual({
      contact_id: 2,
    });
  });
});

describe("HiringManagerCombobox", () => {
  it("bez klienta jest wyłączony i nie pyta o kontakty", () => {
    renderCombobox({ clientId: null });
    const trigger = screen.getByRole("combobox", { name: "Hiring manager" });
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveTextContent("Najpierw wybierz klienta");
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("wybiera istniejący kontakt z listy", async () => {
    const onChange = renderCombobox();
    fireEvent.click(screen.getByRole("combobox", { name: "Hiring manager" }));
    fireEvent.click(await screen.findByText("Ewa Mazur"));
    expect(onChange).toHaveBeenCalledWith({ kind: "contact", id: 2, name: "Ewa Mazur" });
    expect(mocks.get).toHaveBeenCalledWith("/api/jobs/hiring-manager-options", {
      params: { client_id: 7 },
    });
  });

  it("dodaje wpisaną osobę ze stanowiskiem", async () => {
    const onChange = renderCombobox();
    fireEvent.click(screen.getByRole("combobox", { name: "Hiring manager" }));
    await screen.findByText("Ewa Mazur");
    fireEvent.change(screen.getByPlaceholderText(/wpisz imię i nazwisko/), {
      target: { value: "Jan Nowy" },
    });
    fireEvent.click(screen.getByText("Dodaj „Jan Nowy” jako nowego hiring managera"));
    fireEvent.change(screen.getByLabelText("Stanowisko (opcjonalnie)"), {
      target: { value: "Kierownik" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Wybierz" }));
    expect(onChange).toHaveBeenCalledWith({
      kind: "new",
      name: "Jan Nowy",
      position: "Kierownik",
      email: null,
    });
  });

  it("nie proponuje dodania osoby, która już jest w kontaktach", async () => {
    renderCombobox();
    fireEvent.click(screen.getByRole("combobox", { name: "Hiring manager" }));
    await screen.findByText("Ewa Mazur");
    fireEvent.change(screen.getByPlaceholderText(/wpisz imię i nazwisko/), {
      target: { value: "mazur ewa" },
    });
    await waitFor(() => expect(screen.getByText("Ewa Mazur")).toBeInTheDocument());
    expect(screen.queryByText(/jako nowego hiring managera/)).toBeNull();
  });

  it("jedno słowo to nie osoba — „Wybierz” zostaje wyłączone", async () => {
    const onChange = renderCombobox();
    fireEvent.click(screen.getByRole("combobox", { name: "Hiring manager" }));
    await screen.findByText("Ewa Mazur");
    fireEvent.change(screen.getByPlaceholderText(/wpisz imię i nazwisko/), {
      target: { value: "Jan" },
    });
    fireEvent.click(screen.getByText("Dodaj „Jan” jako nowego hiring managera"));
    expect(screen.getByRole("button", { name: "Wybierz" })).toBeDisabled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("awaria listy nie blokuje wpisania osoby", async () => {
    mocks.get.mockRejectedValue(new Error("403"));
    renderCombobox();
    fireEvent.click(screen.getByRole("combobox", { name: "Hiring manager" }));
    expect(
      await screen.findByText(/Nie udało się wczytać kontaktów klienta/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/wpisz imię i nazwisko/), {
      target: { value: "Jan Nowy" },
    });
    expect(
      screen.getByText("Dodaj „Jan Nowy” jako nowego hiring managera"),
    ).toBeInTheDocument();
  });
});

describe("HiringManagerCombobox — „Klient nie podał” (04.10.2026)", () => {
  function renderWithDecision(notProvided: boolean) {
    const onChange = vi.fn();
    const onNotProvidedChange = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <span id="hm-label">Hiring manager</span>
        <HiringManagerCombobox
          clientId={7}
          value={null}
          onChange={onChange}
          labelledBy="hm-label"
          notProvided={notProvided}
          onNotProvidedChange={onNotProvidedChange}
        />
      </QueryClientProvider>,
    );
    return { onChange, onNotProvidedChange };
  }

  it("bez `onNotProvidedChange` pola wyboru nie ma", () => {
    renderCombobox();
    expect(screen.queryByRole("checkbox", { name: "Klient nie podał" })).toBeNull();
  });

  it("zaznaczenie zgłasza decyzję wołającemu", () => {
    const { onNotProvidedChange } = renderWithDecision(false);
    fireEvent.click(screen.getByRole("checkbox", { name: "Klient nie podał" }));
    expect(onNotProvidedChange).toHaveBeenCalledWith(true);
    expect(screen.queryByText(/nie zadziała weto/)).toBeNull();
  });

  it("zaznaczone: wybór osoby wyłączony, pod polem zdanie o wecie", () => {
    renderWithDecision(true);
    const trigger = screen.getByRole("combobox", { name: "Hiring manager" });
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveTextContent("Klient nie podał");
    expect(screen.getByRole("checkbox", { name: "Klient nie podał" })).toBeChecked();
    expect(screen.getByText(/Bez hiring managera nie zadziała weto/)).toBeInTheDocument();
  });
});

describe("HiringManagerPicker — „Klient nie podał” w doku", () => {
  function renderPicker(notProvided?: boolean) {
    const onSaved = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <HiringManagerPicker
          jobId={55}
          clientId={7}
          value={null}
          canEdit
          onSaved={onSaved}
          notProvided={notProvided}
        />
      </QueryClientProvider>,
    );
    return onSaved;
  }

  it("pokazuje zapisaną decyzję zamiast „nie przypisano”", () => {
    renderPicker(true);
    expect(screen.getByText("Klient nie podał")).toBeInTheDocument();
    expect(screen.queryByText("nie przypisano")).toBeNull();
  });

  it("zaznaczenie zapisuje PUT {not_provided: true}", async () => {
    mocks.put.mockResolvedValue({ data: {} });
    const onSaved = renderPicker(false);
    fireEvent.click(screen.getByRole("button", { name: /Przypisz/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Klient nie podał" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/jobs/55/hiring-manager", {
        not_provided: true,
      }),
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("odmowa `handoff_regression` pokazuje zdanie i braki", async () => {
    mocks.put.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: {
            code: "handoff_regression",
            message: "Rekrutacja w pracy straciłaby hiring managera.",
            blockers: [{ code: "hiring_manager", message: "Wskaż hiring managera." }],
          },
        },
      },
    });
    renderPicker(false);
    fireEvent.click(screen.getByRole("button", { name: /Przypisz/ }));
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(await screen.findByText("Ewa Mazur"));
    expect(
      await screen.findByText(
        "Rekrutacja w pracy straciłaby hiring managera. Wskaż hiring managera.",
      ),
    ).toBeInTheDocument();
  });
});
