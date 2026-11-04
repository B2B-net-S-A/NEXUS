/**
 * Okno „Ogłoszenie” — kontrakty, o które najłatwiej się potknąć:
 * do schowka idą tylko teksty policzone przez serwer, znalezisko blokujące
 * wyłącza kopiowanie, ponowne przygotowanie pyta o zgodę, a awaria zapytania
 * nie wygląda jak rekrutacja bez ogłoszenia.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

const clipboard = vi.hoisted(() => ({
  copyTextToClipboard: vi.fn(async () => true),
  copyHtmlToClipboard: vi.fn(async () => true),
}));
vi.mock("@/lib/clipboard", () => clipboard);

import { jobAdQueryKey, type AdCareerState, type JobAdState } from "@/lib/api/jobAd";

import { JobAdWindow, type JobAdWindowApi } from "../JobAdWindow";
import {
  adState,
  CLIENT_FINDING,
  CONTENT,
  EMPTY_STATE,
  PRACUJ_URL,
  publication,
  TECH,
} from "./job-ad-fixtures";

const CAREER_LIVE: AdCareerState = {
  status: "live",
  url: "https://kariera.b2bnetwork.pl/r/senior-java-developer-ab12",
  published_at: "2026-10-21T09:00:00Z",
  published_by_name: "Marta Przykładowa",
};

type SaveInput = Parameters<JobAdWindowApi["save"]>[1];
type SaveImpl = (jobId: number, input: SaveInput) => Promise<JobAdState>;

type Loaded = JobAdState | Error | (() => JobAdState);
type GenerateImpl = JobAdWindowApi["generate"];

const CONFLICT = {
  response: {
    status: 409,
    data: {
      detail: { code: "job_ad_changed", message: "Ktoś zmienił ogłoszenie." },
    },
  },
};

function setup(initial: Loaded, saveImpl?: SaveImpl, generateImpl?: GenerateImpl) {
  const api = {
    get: vi.fn(async (_jobId: number) => {
      if (initial instanceof Error) throw initial;
      return typeof initial === "function" ? initial() : initial;
    }),
    generate: vi.fn<GenerateImpl>(generateImpl ?? (async () => adState())),
    save: vi.fn<SaveImpl>(
      saveImpl ?? (async (_jobId, input) => adState({ content: input.content })),
    ),
    markPublished: vi.fn<JobAdWindowApi["markPublished"]>(async (_jobId, portal, url) =>
      adState({ publications: [publication({ portal, url })] }),
    ),
    markRemoved: vi.fn<JobAdWindowApi["markRemoved"]>(async () => adState()),
    publishCareer: vi.fn<JobAdWindowApi["publishCareer"]>(async () =>
      adState({ career: CAREER_LIVE }),
    ),
  };
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
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
  return Object.assign(api, { client });
}

/** Radix przełącza zakładkę na `mousedown`. */
function openTab(name: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0 });
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
      await screen.findByRole("heading", {
        name: "Ta rekrutacja nie ma jeszcze ogłoszenia",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Pracuj.pl" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Przygotuj ogłoszenie" }));

    expect(await screen.findByRole("region", { name: "O projekcie" })).toHaveTextContent(
      "Zespół buduje mikroserwisy rozliczeniowe.",
    );
    expect(api.generate).toHaveBeenCalledWith(7, "pl", null);
    expect(screen.getByRole("tab", { name: "Pracuj.pl" })).toBeInTheDocument();
  });

  it("awaria wczytania nie udaje rekrutacji bez ogłoszenia", async () => {
    setup(new Error("500"));
    expect(await screen.findByText("Nie udało się wczytać ogłoszenia")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        name: "Ta rekrutacja nie ma jeszcze ogłoszenia",
      }),
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
      await screen.findByRole("button", {
        name: "Skopiowane: Nasze wymagania",
      }),
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
      content: {
        ...CONTENT,
        about: "Platforma płatności dla klienta Bank Przykładowy.",
      },
      findings: [CLIENT_FINDING],
    });

  it("znalezisko blokujące wyłącza kopiowanie w obu zakładkach", async () => {
    setup(blocked());
    expect(await screen.findByText("Kopiowanie jest wyłączone.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kopiuj: Nasze wymagania" })).toBeDisabled();
    expect(screen.getByTestId("job-ad-checks-summary")).toHaveTextContent(
      "Kontrola: 1 do usunięcia",
    );

    fireEvent.mouseDown(screen.getByRole("tab", { name: "JustJoin.IT" }), {
      button: 0,
    });
    expect(await screen.findByRole("button", { name: "Kopiuj opis" })).toBeDisabled();
    expect(clipboard.copyHtmlToClipboard).not.toHaveBeenCalled();
  });

  it("„Usuń fragment” zapisuje treść bez wskazanego fragmentu i odblokowuje kopiowanie", async () => {
    const api = setup(blocked());
    const panel = await screen.findByRole("region", {
      name: "Kontrola przed publikacją",
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
    expect(screen.getByTestId("job-ad-checks-summary")).toHaveTextContent("Kontrola: 1 do poprawy");
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

  it("„To oferujemy” w edycji pokazuje całą listę, wycina wklejone kopie i ukrywa punkt", async () => {
    // Zgłoszenie 28.10.2026: „Edytuj” dawało puste pole, a wklejona lista
    // kończyła się błędem „List should have at most 6 items”.
    const api = setup(adState());
    fireEvent.click(await screen.findByRole("button", { name: "Edytuj: To oferujemy" }));

    const box = screen.getByRole("textbox", { name: "Treść: To oferujemy" });
    expect(box).toHaveValue("projekt na lata");
    expect(
      within(screen.getByRole("list", { name: "Z rekrutacji — dokłada się samo" })).getByText(
        "kontrakt B2B",
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "Stały blok — dokłada się sam" })).getByText(
        "opieka medyczna",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Twoje punkty: 1 / 6")).toBeInTheDocument();

    fireEvent.change(box, {
      target: { value: "Kontrakt B2B\nprojekt na lata\nopieka medyczna\nzespół w Warszawie" },
    });
    expect(screen.getByText("Pominięto 2 punkty, które ogłoszenie już ma.")).toBeInTheDocument();
    expect(screen.getByText("Twoje punkty: 2 / 6")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ukryj w tym ogłoszeniu: opieka medyczna" }));
    expect(
      screen.getByRole("button", { name: "Przywróć: opieka medyczna" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    const saved = api.save.mock.calls[0][1].content;
    expect(saved.offer).toEqual(["projekt na lata", "zespół w Warszawie"]);
    expect(saved.offer_hidden).toEqual(["opieka medyczna"]);
  });

  it("za dużo własnych punktów w „To oferujemy” wyłącza zapis z komunikatem po polsku", async () => {
    const api = setup(adState());
    fireEvent.click(await screen.findByRole("button", { name: "Edytuj: To oferujemy" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Treść: To oferujemy" }), {
      target: { value: Array.from({ length: 7 }, (_, i) => `punkt ${i + 1}`).join("\n") },
    });
    expect(
      screen.getByText("Najwyżej 6 własnych punktów, jest 7. Usuń albo połącz część z nich."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
    expect(api.save).not.toHaveBeenCalled();
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

  it("miasto w ogłoszeniu zastępuje to z rekrutacji, a puste pole wraca do rekrutacji", async () => {
    // Zgłoszenie 28.10.2026: adres biura z lokalizacji rekrutacji zdradzał klienta.
    const api = setup(adState());
    const city = await screen.findByLabelText("Miasto w ogłoszeniu");
    expect(city).toHaveValue("");
    expect(city).toHaveAttribute("placeholder", "Z rekrutacji: Warszawa");
    fireEvent.change(city, { target: { value: " Warszawa lub Lublin " } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz warunki" }));
    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    expect(api.save.mock.calls[0][1].content).toMatchObject({
      city: "Warszawa lub Lublin",
      start: "listopad 2026",
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
    // Wersja z ekranu idzie z żądaniem: inna w bazie = odmowa zamiast podmiany.
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith(7, "pl", "2026-10-12T09:20:00Z"));
  });

  it("przygotowanie odrzucone, bo ktoś zmienił ogłoszenie, wczytuje je ponownie", async () => {
    const api = setup(adState(), undefined, async () => {
      throw CONFLICT;
    });
    fireEvent.click(await screen.findByRole("button", { name: "Przygotuj ponownie" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Przygotować ogłoszenie ponownie?",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Przygotuj ponownie" }));

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(toast.showError).toHaveBeenCalledWith("Ktoś zmienił ogłoszenie.");
  });

  it("treść złożona bez modelu i zmieniona rekrutacja są nazwane wprost", async () => {
    setup(adState({ source: "template", stale: true }));
    expect(await screen.findByText("Model był niedostępny.")).toBeInTheDocument();
    expect(
      screen.getByText("Rekrutacja zmieniła się od przygotowania ogłoszenia."),
    ).toBeInTheDocument();
  });

  it("zapis odrzucony, bo ktoś zmienił ogłoszenie, wczytuje je ponownie", async () => {
    const api = setup(adState(), async () => {
      throw CONFLICT;
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

describe("JobAdWindow — niezapisany tekst", () => {
  it("przejście do drugiej zakładki i z powrotem nie gubi otwartej poprawki", async () => {
    setup(adState());
    fireEvent.click(await screen.findByRole("button", { name: "Edytuj: Nasze wymagania" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Treść: Nasze wymagania" }), {
      target: { value: "Java 21" },
    });

    openTab("JustJoin.IT");
    // To samo pole w drugiej zakładce pokazuje tę samą otwartą poprawkę…
    expect(await screen.findByRole("textbox", { name: "Treść: Wymagania" })).toHaveValue("Java 21");
    // …a opis kopiowany w całości czeka, aż zostanie zapisana albo anulowana.
    expect(screen.getByRole("button", { name: "Kopiuj opis" })).toBeDisabled();

    openTab("Pracuj.pl");
    expect(await screen.findByRole("textbox", { name: "Treść: Nasze wymagania" })).toHaveValue(
      "Java 21",
    );
  });

  it("odrzucony zapis warunków nie czyści tego, co rekruter wpisał", async () => {
    let loads = 0;
    const api = setup(
      () =>
        ++loads === 1 ? adState() : adState({ content: { ...CONTENT, duration: "24 miesiące" } }),
      async () => {
        throw CONFLICT;
      },
    );
    fireEvent.change(await screen.findByLabelText("Start projektu"), {
      target: { value: "styczeń 2027" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz warunki" }));

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByLabelText("Długość współpracy")).toHaveValue("24 miesiące"),
    );
    expect(screen.getByLabelText("Start projektu")).toHaveValue("styczeń 2027");
  });

  it("odświeżenie w tle pod otwartą poprawką nie przepuszcza jej przez kontrolę wersji", async () => {
    const other = adState({
      content: {
        ...CONTENT,
        requirements: ["punkt dopisany przez inną osobę"],
      },
    });
    other.ad!.updated_at = "2026-10-12T12:00:00Z";
    let loads = 0;
    const api = setup(() => (++loads === 1 ? adState() : other));

    fireEvent.click(await screen.findByRole("button", { name: "Edytuj: O projekcie" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Treść: O projekcie" }), {
      target: { value: "Moja poprawka." },
    });
    // To samo robi powrót do karty przeglądarki.
    await api.client.refetchQueries({ queryKey: jobAdQueryKey(7) });
    await screen.findByText("punkt dopisany przez inną osobę");

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    // Wersja, od której zaczęła się edycja — serwer odpowie na nią 409.
    expect(api.save.mock.calls[0][1].expected_updated_at).toBe("2026-10-12T09:20:00Z");
  });

  it("zapis jednego pola nie odrzuca drugiego, otwartego wcześniej", async () => {
    let version = 0;
    const api = setup(adState(), async (_jobId, input) => {
      const next = adState({ content: input.content });
      next.ad!.updated_at = `2026-10-12T10:0${++version}:00Z`;
      return next;
    });
    fireEvent.click(await screen.findByRole("button", { name: "Edytuj: O projekcie" }));
    fireEvent.click(screen.getByRole("button", { name: "Edytuj: Nasze wymagania" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Treść: O projekcie" }), {
      target: { value: "Nowy opis." },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Treść: Nasze wymagania" }), {
      target: { value: "Java 21" },
    });

    const about = screen.getByRole("region", { name: "O projekcie" });
    fireEvent.click(within(about).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Treść: O projekcie" })).not.toBeInTheDocument(),
    );

    const requirements = screen.getByRole("region", {
      name: "Nasze wymagania",
    });
    fireEvent.click(within(requirements).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(2));
    expect(api.save.mock.calls[1][1]).toMatchObject({
      content: { about: "Nowy opis.", requirements: ["Java 21"] },
      expected_updated_at: "2026-10-12T10:01:00Z",
    });
  });
});

describe("JobAdWindow — oznaczenie publikacji", () => {
  it("po wklejeniu na portalu rekruter oznacza publikację z linkiem", async () => {
    const api = setup(adState());
    const row = await screen.findByRole("listitem", { name: "Publikacja: Pracuj.pl" });
    expect(row).toHaveTextContent("Nieoznaczone jako opublikowane");

    fireEvent.click(within(row).getByRole("button", { name: "Oznacz jako opublikowane" }));
    fireEvent.change(within(row).getByRole("textbox"), { target: { value: ` ${PRACUJ_URL} ` } });
    fireEvent.click(within(row).getByRole("button", { name: "Oznacz" }));

    await waitFor(() =>
      expect(api.markPublished).toHaveBeenCalledWith(7, "pracuj", PRACUJ_URL, false),
    );
    const published = await screen.findByRole("listitem", { name: "Publikacja: Pracuj.pl" });
    expect(published).toHaveTextContent("Opublikowane");
    expect(within(published).getByRole("link", { name: /Otwórz ogłoszenie/ })).toHaveAttribute(
      "href",
      PRACUJ_URL,
    );
  });

  it("kolumna „Gdzie publikujesz” pokazuje oba portale niezależnie od zakładki", async () => {
    setup(adState({ publications: [publication()] }));
    expect(
      await screen.findByRole("listitem", { name: "Publikacja: Pracuj.pl" }),
    ).toHaveTextContent("Opublikowane");
    expect(
      screen.getByRole("listitem", { name: "Publikacja: JustJoin.IT" }),
    ).toHaveTextContent("Nieoznaczone jako opublikowane");
    openTab("JustJoin.IT");
    expect(
      await screen.findByRole("listitem", { name: "Publikacja: Pracuj.pl" }),
    ).toHaveTextContent("Opublikowane");
  });

  it("treści z fragmentem blokującym nie da się oznaczyć jako opublikowanej", async () => {
    setup(
      adState({
        content: { ...CONTENT, about: "Platforma płatności dla klienta Bank Przykładowy." },
        findings: [CLIENT_FINDING],
      }),
    );
    const row = await screen.findByRole("listitem", { name: "Publikacja: Pracuj.pl" });
    expect(within(row).getByRole("button", { name: "Oznacz jako opublikowane" })).toBeDisabled();
  });
});

describe("JobAdWindow — strona kariery z ogłoszenia (21.10.2026)", () => {
  it("„Opublikuj na stronie” wysyła wersję z ekranu i pokazuje link", async () => {
    const api = setup(adState());
    const card = await screen.findByRole("region", { name: "Strona kariery" });
    fireEvent.click(within(card).getByRole("button", { name: "Opublikuj na stronie" }));

    await waitFor(() => expect(api.publishCareer).toHaveBeenCalledWith(7, "2026-10-12T09:20:00Z"));
    const live = await screen.findByRole("region", { name: "Strona kariery" });
    await waitFor(() => expect(live).toHaveTextContent("Wisi"));
    expect(within(live).getByRole("link", { name: /Otwórz stronę/ })).toHaveAttribute(
      "href",
      CAREER_LIVE.url,
    );
    fireEvent.click(within(live).getByRole("button", { name: "Kopiuj link" }));
    await waitFor(() =>
      expect(clipboard.copyTextToClipboard).toHaveBeenCalledWith(CAREER_LIVE.url),
    );
    expect(within(live).getByRole("button", { name: "Skopiowano link" })).toBeInTheDocument();
  });

  it("fragment blokujący wyłącza publikację na stronie", async () => {
    setup(
      adState({
        content: { ...CONTENT, about: "Platforma płatności dla klienta Bank Przykładowy." },
        findings: [CLIENT_FINDING],
      }),
    );
    const card = await screen.findByRole("region", { name: "Strona kariery" });
    expect(within(card).getByRole("button", { name: "Opublikuj na stronie" })).toBeDisabled();
    expect(card).toHaveTextContent("Najpierw usuń z treści fragmenty wskazane w kontroli.");
  });

  it("otwarta poprawka wstrzymuje publikację, bo na stronę idzie zapisana treść", async () => {
    setup(adState());
    fireEvent.click(await screen.findByRole("button", { name: "Edytuj: O projekcie" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Treść: O projekcie" }), {
      target: { value: "Nowy opis." },
    });
    const card = screen.getByRole("region", { name: "Strona kariery" });
    expect(within(card).getByRole("button", { name: "Opublikuj na stronie" })).toBeDisabled();
    expect(card).toHaveTextContent("Najpierw zapisz albo zamknij otwarte poprawki.");
  });

  it("strona ze starszą treścią proponuje aktualizację", async () => {
    setup(adState({ career: { ...CAREER_LIVE, status: "outdated" } }));
    const card = await screen.findByRole("region", { name: "Strona kariery" });
    expect(card).toHaveTextContent("Starsza treść");
    expect(within(card).getByRole("button", { name: "Zaktualizuj na stronie" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Kopiuj link" })).toBeInTheDocument();
  });
});
