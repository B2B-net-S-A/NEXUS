/**
 * Podpis w NEXUSIE u dostawcy w chmurze (kierunek K1, 22.11.2026): strona
 * kontraktora i panel reprezentanta. Bez `available` oba ekrany wyglądają jak
 * dotąd; z nim start idzie do dostawcy, a po powrocie ekran pyta o stan sesji.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PublicSignDocument, PublicSignView } from "@/lib/api/b2bEsign";

const mocks = vi.hoisted(() => ({
  leave: vi.fn(),
  search: "",
  mine: vi.fn(),
  available: vi.fn(),
  start: vi.fn(),
  status: vi.fn(),
  companySign: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

vi.mock("@/lib/remote-signing", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/remote-signing")>()),
  leaveForProvider: (...a: unknown[]) => mocks.leave(...a),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

vi.mock("@/lib/api/b2bEsign", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/b2bEsign")>();
  return {
    ...actual,
    b2bEsignApi: {
      mine: (...a: unknown[]) => mocks.mine(...a),
      companyRemoteAvailable: (...a: unknown[]) => mocks.available(...a),
      companyRemoteStart: (...a: unknown[]) => mocks.start(...a),
      companyRemoteStatus: (...a: unknown[]) => mocks.status(...a),
      companySign: (...a: unknown[]) => mocks.companySign(...a),
      companyPdf: vi.fn(),
    },
  };
});

import B2BSignForm from "@/app/sign/b2b/[token]/B2BSignForm";

import { CompanySignaturesPanel } from "../CompanySignaturesPanel";

const AVAILABLE = { available: true, provider_label: "SimplySign" };
const NDA: PublicSignDocument = { id: 4, title: "NDA klienta", signed: false, requirement: "any" };
const RODO: PublicSignDocument = { id: 5, title: "Oświadczenie RODO", signed: false, requirement: "any" };

function json(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

function bodyOf(fetchMock: ReturnType<typeof vi.fn>, call: number) {
  return JSON.parse(String(fetchMock.mock.calls[call][1].body));
}

function signedView(documents: PublicSignDocument[]): PublicSignView {
  return {
    contract_number: "1610/2026",
    contractor_name: "Piotr Przykładowy",
    status: "signed_by_you",
    expires_at: null,
    contract_signed: true,
    documents,
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("strona kontraktora: podpis w NEXUSIE (K1)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("bez dostawcy strona wygląda jak dotąd", () => {
    const { unmount } = render(
      <B2BSignForm token="t" initialState="waiting" contractNumber="1610/2026" documents={[NDA]} />,
    );
    expect(screen.getByText("1. Pobierz dokumenty (2)")).toBeInTheDocument();
    expect(screen.queryByText("1. Jak podpiszesz umowę?")).toBeNull();
    unmount();
    render(
      <B2BSignForm
        token="t"
        initialState="waiting"
        remoteSigning={{ available: false, provider_label: null }}
      />,
    );
    expect(screen.getByText("1. Pobierz umowę")).toBeInTheDocument();
    expect(screen.queryByText(/w NEXUSIE/)).toBeNull();
  });

  it("razem z umową: jeden start na cały komplet i przejście do dostawcy", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ redirect_url: "https://dostawca.example/podpis/abc", session_id: "s1" }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(
      <B2BSignForm
        token="t"
        initialState="waiting"
        contractNumber="1610/2026"
        documents={[NDA, RODO]}
        remoteSigning={AVAILABLE}
      />,
    );
    expect(screen.getByText("Dokumenty (3)")).toBeInTheDocument();
    expect(screen.getByText("wymagany podpis kwalifikowany")).toBeInTheDocument();
    expect(screen.getAllByText("dowolny podpis")).toHaveLength(2);
    expect(screen.getByText("2. NDA klienta i Oświadczenie RODO: wybierz sposób")).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: /Razem z umową, tym samym podpisem kwalifikowanym/ }),
    ).toBeChecked();
    expect(screen.getByRole("radio", { name: /Mam podpis kwalifikowany w telefonie/ })).toBeChecked();
    expect(container.textContent).not.toContain("—");
    await userEvent.click(screen.getByRole("button", { name: "Podpisz 3 dokumenty w NEXUSIE" }));
    await waitFor(() => expect(mocks.leave).toHaveBeenCalledWith("https://dostawca.example/podpis/abc"));
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/public\/b2b-sign\/t\/remote\/start$/);
    expect(bodyOf(fetchMock, 0)).toEqual({ include_document_ids: [4, 5], method: "own_certificate" });
  });

  it("bez podpisu kwalifikowanego i z kodem z maila: tylko umowa i dokumenty z wymogiem klienta", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ redirect_url: "https://dostawca.example/x", session_id: "s2" }));
    vi.stubGlobal("fetch", fetchMock);
    const clientQualified: PublicSignDocument = {
      id: 6,
      title: "Oświadczenie o niekaralności",
      signed: false,
      requirement: "qualified",
    };
    const { container } = render(
      <B2BSignForm
        token="t"
        initialState="waiting"
        contractNumber="1610/2026"
        documents={[NDA, clientQualified]}
        acceptEmail="p***@example.com"
        remoteSigning={AVAILABLE}
      />,
    );
    await userEvent.click(screen.getByRole("radio", { name: /Nie mam podpisu kwalifikowanego/ }));
    expect(screen.getByText("Najpierw potwierdzisz, że to Ty")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Kodem z maila/ }));
    // Ten sam blok akceptacji kodem co dotąd.
    expect(screen.getByRole("button", { name: /Wyślij kod/ })).toBeInTheDocument();
    expect(screen.getByText(/na adres p\*\*\*@example.com/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("—");
    await userEvent.click(screen.getByRole("button", { name: "Potwierdź tożsamość i podpisz" }));
    await waitFor(() => expect(mocks.leave).toHaveBeenCalled());
    expect(bodyOf(fetchMock, 0)).toEqual({ include_document_ids: [6], method: "one_time" });
  });

  it("błąd startu: komunikat serwera, bez przejścia do dostawcy", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Dostawca podpisu nie odpowiada." }, 503)));
    render(<B2BSignForm token="t" initialState="waiting" contractNumber="1610/2026" remoteSigning={AVAILABLE} />);
    await userEvent.click(screen.getByRole("button", { name: "Podpisz umowę w NEXUSIE" }));
    expect(await screen.findByText("Dostawca podpisu nie odpowiada.")).toBeInTheDocument();
    expect(mocks.leave).not.toHaveBeenCalled();
  });

  it("„Wolę podpisać u siebie” zostawia pobierz i wgraj", async () => {
    render(
      <B2BSignForm
        token="t"
        initialState="waiting"
        contractNumber="1610/2026"
        documents={[NDA]}
        remoteSigning={AVAILABLE}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Wolę podpisać u siebie i wgrać pliki" }));
    expect(screen.getByText("1. Pobierz dokumenty (2)")).toBeInTheDocument();
    expect(document.getElementById("b2b-sign-file-contract")).not.toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: "Wolę podpisać w NEXUSIE, bez pobierania plików" }),
    );
    expect(screen.getByText("1. Jak podpiszesz umowę?")).toBeInTheDocument();
  });

  it("po powrocie: czeka na zatwierdzenie, potem pokazuje komplet z widoku serwera", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.history.replaceState(null, "", "/sign/b2b/t?remote=s1");
    const done = signedView([{ ...NDA, signed: true, signed_via: "qualified" }]);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ state: "waiting_for_user", message: null, view: null }))
      .mockResolvedValueOnce(json({ state: "signing", message: null, view: null }))
      .mockResolvedValueOnce(json({ state: "done", message: null, view: done }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(
      <B2BSignForm
        token="t"
        initialState="waiting"
        contractNumber="1610/2026"
        documents={[NDA]}
        remoteSigning={AVAILABLE}
        remoteSessionId="s1"
      />,
    );
    expect(await screen.findByText("Zatwierdź podpis w aplikacji SimplySign")).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/public\/b2b-sign\/t\/remote\/s1$/);
    expect(container.textContent).not.toContain("—");
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    expect(await screen.findByText("Podpis zatwierdzony, kończymy")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    expect(await screen.findByText("Gotowe: 2 z 2")).toBeInTheDocument();
    expect(screen.getAllByText("podpis kwalifikowany: Piotr Przykładowy")).toHaveLength(2);
    expect(window.location.search).toBe("");
    expect(container.textContent).not.toContain("—");
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("podpis gotowy, a dokumenty kodem jeszcze czekają: dzisiejszy blok kodu", async () => {
    const view: PublicSignView = {
      ...signedView([NDA]),
      status: "waiting",
      accept_code_email: "p***@example.com",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ state: "done", message: null, view })));
    render(
      <B2BSignForm
        token="t"
        initialState="waiting"
        contractNumber="1610/2026"
        documents={[NDA]}
        remoteSigning={AVAILABLE}
        remoteSessionId="s1"
      />,
    );
    expect(await screen.findByText("Umowa podpisana w NEXUSIE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wyślij kod/ })).toBeInTheDocument();
    expect(screen.queryByText("1. Jak podpiszesz umowę?")).toBeNull();
  });

  it.each([
    ["failed", "Podpis nie został złożony", "Certyfikat wygasł."],
    ["cancelled", "Podpis anulowany", null],
  ] as const)("stan %s: komunikat i powrót do wyboru", async (state, title, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ state, message, view: null })));
    const { container } = render(
      <B2BSignForm
        token="t"
        initialState="waiting"
        contractNumber="1610/2026"
        remoteSigning={AVAILABLE}
        remoteSessionId="s1"
      />,
    );
    expect(await screen.findByText(title)).toBeInTheDocument();
    if (message) expect(screen.getByText(message)).toBeInTheDocument();
    expect(container.textContent).not.toContain("—");
    await userEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(screen.getByText("1. Jak podpiszesz umowę?")).toBeInTheDocument();
  });

  it("po 3 minutach bez odpowiedzi przestaje pytać i mówi o tym", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = vi.fn().mockResolvedValue(json({ state: "waiting_for_user", message: null, view: null }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(
      <B2BSignForm
        token="t"
        initialState="waiting"
        contractNumber="1610/2026"
        remoteSigning={AVAILABLE}
        remoteSessionId="s1"
      />,
    );
    expect(await screen.findByText("Zatwierdź podpis w aplikacji SimplySign")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(181_000));
    expect(await screen.findByText("Nie mamy jeszcze odpowiedzi od dostawcy podpisu")).toBeInTheDocument();
    const calls = fetchMock.mock.calls.length;
    expect(calls).toBeGreaterThan(50);
    expect(calls).toBeLessThanOrEqual(92);
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(fetchMock.mock.calls.length).toBe(calls);
    expect(container.textContent).not.toContain("—");
  });

  it("link wygasł w trakcie: strona przechodzi na „Poproś o nowy link”", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Termin minął." }, 410)));
    render(<B2BSignForm token="t" initialState="waiting" remoteSigning={AVAILABLE} remoteSessionId="s1" />);
    expect(await screen.findByRole("button", { name: "Poproś o nowy link" })).toBeInTheDocument();
  });
});

function wrap(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return { client, ...render(<QueryClientProvider client={client}>{node}</QueryClientProvider>) };
}

const WAITING = [
  {
    id: 3,
    generated_contract_id: 9,
    contract_number: "1611/2026",
    client_name: "Bank B",
    contractor_name: "Ewa Przykładowa",
    contractor_signed_at: "2026-11-21T10:14:00Z",
  },
  {
    id: 4,
    generated_contract_id: 10,
    contract_number: "1612/2026",
    client_name: null,
    contractor_name: "Jan Testowy",
    contractor_signed_at: "2026-11-21T11:00:00Z",
  },
];

describe("panel reprezentanta: podpis zaznaczonych w NEXUSIE (K1)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.search = "";
    mocks.mine.mockResolvedValue(WAITING);
  });

  it("bez dostawcy panel wygląda jak dotąd", async () => {
    mocks.available.mockResolvedValue({ available: false, provider_label: null });
    wrap(<CompanySignaturesPanel />);
    expect(await screen.findByText("Ewa Przykładowa")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Plik z oboma podpisami")).toHaveLength(2);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByText(/w NEXUSIE/)).toBeNull();
  });

  it("awaria sprawdzenia dostawcy zostawia dzisiejszy panel", async () => {
    mocks.available.mockRejectedValue(new Error("500"));
    wrap(<CompanySignaturesPanel />);
    expect(await screen.findByText("Ewa Przykładowa")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Plik z oboma podpisami")).toHaveLength(2);
  });

  it("zaznaczone umowy idą do dostawcy jednym startem", async () => {
    mocks.available.mockResolvedValue(AVAILABLE);
    mocks.start.mockResolvedValue({ redirect_url: "https://dostawca.example/firma", session_id: "s9" });
    wrap(<CompanySignaturesPanel />);
    const button = await screen.findByRole("button", { name: "Podpisz zaznaczone w NEXUSIE (2)" });
    expect(screen.getByText(/jednym potwierdzeniem w aplikacji SimplySign/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Zaznacz 1612/2026 · Jan Testowy" }));
    expect(button).toHaveAccessibleName("Podpisz zaznaczone w NEXUSIE (1)");
    await userEvent.click(button);
    await waitFor(() => expect(mocks.start).toHaveBeenCalledWith([3]));
    expect(mocks.leave).toHaveBeenCalledWith("https://dostawca.example/firma");
  });

  it("nic nie zaznaczone: przycisk nieaktywny", async () => {
    mocks.available.mockResolvedValue(AVAILABLE);
    wrap(<CompanySignaturesPanel />);
    await screen.findByRole("button", { name: /Podpisz zaznaczone w NEXUSIE/ });
    for (const box of screen.getAllByRole("checkbox")) await userEvent.click(box);
    expect(screen.getByRole("button", { name: "Podpisz zaznaczone w NEXUSIE (0)" })).toBeDisabled();
  });

  it("„Wolę pobrać plik…” pokazuje dzisiejsze wgranie", async () => {
    mocks.available.mockResolvedValue(AVAILABLE);
    wrap(<CompanySignaturesPanel />);
    await userEvent.click(
      await screen.findByRole("button", { name: /Wolę pobrać plik, podpisać u siebie i wgrać/ }),
    );
    expect(screen.getAllByLabelText("Plik z oboma podpisami")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /Podpisz zaznaczone w NEXUSIE/ })).toBeNull();
  });

  it("po powrocie: czeka, a po podpisie odświeża listy jak wgranie pliku", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mocks.search = "tab=generated&remote=s9";
    window.history.replaceState(null, "", "/contracts/b2b-generator?tab=generated&remote=s9");
    mocks.available.mockResolvedValue(AVAILABLE);
    mocks.status
      .mockResolvedValueOnce({ state: "waiting_for_user", message: null, done_request_ids: [] })
      .mockResolvedValueOnce({ state: "done", message: null, done_request_ids: [3, 4] });
    const { client } = wrap(<CompanySignaturesPanel />);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    expect(await screen.findByText("Zatwierdź podpis w aplikacji SimplySign")).toBeInTheDocument();
    expect(mocks.status).toHaveBeenCalledWith("s9");
    // W trakcie nie da się wystartować drugi raz.
    expect(screen.queryByRole("button", { name: /Podpisz zaznaczone w NEXUSIE/ })).toBeNull();
    mocks.mine.mockResolvedValue([]);
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    expect(await screen.findByText("Podpisane za B2Bnetwork: 2 umowy")).toBeInTheDocument();
    const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
    expect(keys).toEqual(
      expect.arrayContaining([
        JSON.stringify(["b2b-esign-mine"]),
        JSON.stringify(["b2b-generated"]),
        JSON.stringify(["kanban"]),
        JSON.stringify(["board-tasks"]),
      ]),
    );
    expect(window.location.search).toBe("?tab=generated");
    // Lista opustoszała, a wynik zostaje, dopóki go nie zamkniesz.
    await waitFor(() => expect(screen.queryByText("Ewa Przykładowa")).toBeNull());
    const done = screen.getByText("Podpisane za B2Bnetwork: 2 umowy").closest("div")!.parentElement!;
    await userEvent.click(within(done).getByRole("button", { name: "Zamknij" }));
    expect(screen.queryByText(/Podpisane za B2Bnetwork/)).toBeNull();
  });

  it("anulowany podpis: komunikat i lista znów do zaznaczania", async () => {
    mocks.search = "remote=s9";
    mocks.available.mockResolvedValue(AVAILABLE);
    mocks.status.mockResolvedValue({
      state: "cancelled",
      message: "Prośba wygasła w aplikacji.",
      done_request_ids: [],
    });
    wrap(<CompanySignaturesPanel />);
    expect(await screen.findByText("Podpis za B2Bnetwork anulowany")).toBeInTheDocument();
    expect(screen.getByText("Prośba wygasła w aplikacji.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Podpisz zaznaczone w NEXUSIE (2)" })).toBeEnabled();
  });

  it("sesja nieznana serwerowi: błąd od razu, bez pytania przez 3 minuty", async () => {
    mocks.search = "remote=zla";
    mocks.available.mockResolvedValue(AVAILABLE);
    mocks.status.mockRejectedValue({ response: { status: 404, data: { detail: "Nie ma takiej sesji podpisu." } } });
    wrap(<CompanySignaturesPanel />);
    expect(await screen.findByText("Nie ma takiej sesji podpisu.")).toBeInTheDocument();
    expect(mocks.status).toHaveBeenCalledTimes(1);
  });
});
