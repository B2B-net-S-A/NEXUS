/**
 * Okno „Ogłoszenie na portale” — kontrakty, o które najłatwiej się potknąć:
 * do schowka idą tylko teksty policzone przez serwer, znalezisko blokujące
 * wyłącza kopiowanie, ponowne przygotowanie pyta o zgodę, a awaria zapytania
 * nie wygląda jak rekrutacja bez ogłoszenia.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

const clipboard = vi.hoisted(() => ({
  copyTextToClipboard: vi.fn(async () => true),
  copyHtmlToClipboard: vi.fn(async () => true),
}));
vi.mock("@/lib/clipboard", () => clipboard);

import type { AdLang, JobAdState } from "@/lib/api/jobAd";

import { JobAdWindow, type JobAdWindowApi } from "../JobAdWindow";
import { adState, CLIENT_FINDING, CONTENT, EMPTY_STATE, TECH } from "./job-ad-fixtures";

type SaveInput = Parameters<JobAdWindowApi["save"]>[1];
type SaveImpl = (jobId: number, input: SaveInput) => Promise<JobAdState>;

function setup(initial: JobAdState | Error, saveImpl?: SaveImpl) {
  const api = {
    get: vi.fn(async (_jobId: number) => {
      if (initial instanceof Error) throw initial;
      return initial;
    }),
    generate: vi.fn(async (_jobId: number, _lang: AdLang) => adState()),
    save: vi.fn<SaveImpl>(
      saveImpl ?? (async (_jobId, input) => adState({ content: input.content })),
    ),
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <JobAdWindow
        jobId={7}
        jobTitle="Senior Java Developer — płatności"
        open
        onClose={vi.fn()}
        api={api}
      />
    </QueryClientProvider>,
  );
  return api;
}

beforeEach(() => {
  vi.clearAllMocks();
  clipboard.copyTextToClipboard.mockResolvedValue(true);
  clipboard.copyHtmlToClipboard.mockResolvedValue(true);
});

describe("JobAdWindow — rekrutacja bez ogłoszenia", () => {
  it("proponuje przygotowanie i po kliknięciu pokazuje pola portalu", async () => {
    const api = setup(EMPTY_STATE);
    expect(
      await screen.findByRole("heading", { name: "Ta rekrutacja nie ma jeszcze ogłoszenia" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Pracuj.pl" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Przygotuj ogłoszenie" }));

    expect(await screen.findByRole("region", { name: "O projekcie" })).toHaveTextContent(
      "Zespół buduje mikroserwisy rozliczeniowe.",
    );
    expect(api.generate).toHaveBeenCalledWith(7, "pl");
    expect(screen.getByRole("tab", { name: "Pracuj.pl" })).toBeInTheDocument();
  });

  it("awaria wczytania nie udaje rekrutacji bez ogłoszenia", async () => {
    setup(new Error("500"));
    expect(await screen.findByText("Nie udało się wczytać ogłoszenia")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Ta rekrutacja nie ma jeszcze ogłoszenia" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Przygotuj ogłoszenie" })).not.toBeInTheDocument();
  });
});

describe("JobAdWindow — kopiowanie", () => {
  it("lista idzie do schowka jako HTML i tekst policzone przez serwer", async () => {
    setup(adState());
    fireEvent.click(await screen.findByRole("button", { name: "Kopiuj: Nasze wymagania" }));

    await waitFor(() =>
      expect(clipboard.copyHtmlToClipboard).toHaveBeenCalledWith(
        "<ul><li>min. 5 lat doświadczenia w Javie</li><li>praktyka z Apache Kafka</li></ul>",
        "min. 5 lat doświadczenia w Javie\npraktyka z Apache Kafka",
      ),
    );
    expect(
      await screen.findByRole("button", { name: "Skopiowane: Nasze wymagania" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kopiuj: O projekcie" })).toBeInTheDocument();
  });

  it("pole tekstowe kopiuje się jako zwykły tekst", async () => {
    setup(adState());
    fireEvent.click(await screen.findByRole("button", { name: "Kopiuj: Tytuł stanowiska" }));
    await waitFor(() =>
      expect(clipboard.copyTextToClipboard).toHaveBeenCalledWith("Senior Java Developer (k/m/x)"),
    );
    expect(clipboard.copyHtmlToClipboard).not.toHaveBeenCalled();
  });

  it("nieudany zapis do schowka nie pokazuje „Skopiowane”", async () => {
    clipboard.copyHtmlToClipboard.mockResolvedValue(false);
    setup(adState());
    fireEvent.click(await screen.findByRole("button", { name: "Kopiuj: Nasze wymagania" }));
    await waitFor(() => expect(toast.showError).toHaveBeenCalled());
    expect(
      screen.queryByRole("button", { name: "Skopiowane: Nasze wymagania" }),
    ).not.toBeInTheDocument();
  });

  it("opis JustJoin.IT kopiuje się z formatowaniem albo jako zwykły tekst", async () => {
    setup(adState());
    fireEvent.mouseDown(await screen.findByRole("tab", { name: "JustJoin.IT" }), { button: 0 });
    expect(await screen.findByText("Tech stack z poziomem")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Kopiuj opis" }));
    await waitFor(() =>
      expect(clipboard.copyHtmlToClipboard).toHaveBeenCalledWith("<p>opis html</p>", "opis tekst"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Kopiuj zwykły tekst" }));
    await waitFor(() => expect(clipboard.copyTextToClipboard).toHaveBeenCalledWith("opis tekst"));
  });
});

describe("JobAdWindow — kontrola przed skopiowaniem", () => {
  const blocked = () =>
    adState({
      content: { ...CONTENT, about: "Platforma płatności dla klienta Bank Przykładowy." },
      findings: [CLIENT_FINDING],
    });

  it("znalezisko blokujące wyłącza kopiowanie w obu zakładkach", async () => {
    setup(blocked());
    expect(await screen.findByText("Kopiowanie jest wyłączone.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kopiuj: Nasze wymagania" })).toBeDisabled();
    expect(screen.getByTestId("job-ad-checks-summary")).toHaveTextContent(
      "Kontrola: 1 do usunięcia",
    );

    fireEvent.mouseDown(screen.getByRole("tab", { name: "JustJoin.IT" }), { button: 0 });
    expect(await screen.findByRole("button", { name: "Kopiuj opis" })).toBeDisabled();
    expect(clipboard.copyHtmlToClipboard).not.toHaveBeenCalled();
  });

  it("„Usuń fragment” zapisuje treść bez wskazanego fragmentu i odblokowuje kopiowanie", async () => {
    const api = setup(blocked());
    const panel = await screen.findByRole("complementary", {
      name: "Kontrola przed skopiowaniem",
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Usuń fragment" }));

    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    expect(api.save.mock.calls[0][1]).toMatchObject({
      content: { about: "Platforma płatności." },
      tech: TECH,
      expected_updated_at: "2026-10-12T09:20:00Z",
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Kopiuj: Nasze wymagania" })).toBeEnabled(),
    );
    expect(screen.getByTestId("job-ad-checks-summary")).toHaveTextContent("Kontrola: bez uwag");
  });

  it("uwaga doradcza nie blokuje kopiowania", async () => {
    setup(
      adState({
        findings: [
          {
            code: "missing_duration",
            severity: "advise",
            message: "Brak długości współpracy.",
            excerpt: null,
            field: "duration",
          },
        ],
      }),
    );
    expect(await screen.findByText("Brak długości współpracy.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kopiuj: Nasze wymagania" })).toBeEnabled();
    expect(screen.queryByText("Kopiowanie jest wyłączone.")).not.toBeInTheDocument();
    expect(screen.getByTestId("job-ad-checks-summary")).toHaveTextContent(
      "Kontrola: 1 do poprawy",
    );
  });
});

describe("JobAdWindow — poprawki i ponowne przygotowanie", () => {
  it("edycja listy zapisuje jedną pozycję na wiersz i unieważnia „Skopiowane”", async () => {
    const api = setup(adState());
    fireEvent.click(await screen.findByRole("button", { name: "Kopiuj: Nasze wymagania" }));
    await screen.findByRole("button", { name: "Skopiowane: Nasze wymagania" });

    fireEvent.click(screen.getByRole("button", { name: "Edytuj: Nasze wymagania" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Treść: Nasze wymagania" }), {
      target: { value: "Java 21\n\n  Spring Boot w produkcji  \n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    expect(api.save.mock.calls[0][1].content.requirements).toEqual([
      "Java 21",
      "Spring Boot w produkcji",
    ]);
    // Nowa treść = nowy tekst do skopiowania.
    expect(
      await screen.findByRole("button", { name: "Kopiuj: Nasze wymagania" }),
    ).toBeInTheDocument();
  });

  it("warunki z lewej kolumny zapisują się razem z resztą treści", async () => {
    const api = setup(adState());
    fireEvent.change(await screen.findByLabelText("Długość współpracy"), {
      target: { value: " 18 miesięcy " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz warunki" }));
    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    expect(api.save.mock.calls[0][1].content).toMatchObject({
      duration: "18 miesięcy",
      start: "listopad 2026",
      about: CONTENT.about,
    });
  });

  it("„Przygotuj ponownie” pyta o zgodę, zanim zastąpi treść", async () => {
    const api = setup(adState());
    fireEvent.click(await screen.findByRole("button", { name: "Przygotuj ponownie" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Przygotować ogłoszenie ponownie?",
    });
    expect(api.generate).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Przygotuj ponownie" }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith(7, "pl"));
  });

  it("treść złożona bez modelu i zmieniona rekrutacja są nazwane wprost", async () => {
    setup(adState({ source: "template", stale: true }));
    expect(await screen.findByText("Model był niedostępny.")).toBeInTheDocument();
    expect(
      screen.getByText("Rekrutacja zmieniła się od przygotowania ogłoszenia."),
    ).toBeInTheDocument();
  });

  it("zapis odrzucony, bo ktoś zmienił ogłoszenie, wczytuje je ponownie", async () => {
    const conflict = {
      response: {
        status: 409,
        data: { detail: { code: "job_ad_changed", message: "Ktoś zmienił ogłoszenie." } },
      },
    };
    const api = setup(adState(), async () => {
      throw conflict;
    });
    fireEvent.click(await screen.findByRole("button", { name: "Edytuj: O projekcie" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Treść: O projekcie" }), {
      target: { value: "Nowy opis." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(toast.showError).toHaveBeenCalledWith("Ktoś zmienił ogłoszenie.");
    // Niezapisana poprawka zostaje w polu — rekruter nie traci tekstu.
    expect(screen.getByRole("textbox", { name: "Treść: O projekcie" })).toHaveValue("Nowy opis.");
  });
});
