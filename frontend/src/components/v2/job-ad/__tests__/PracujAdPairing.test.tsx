/**
 * Ogłoszenie ze strefy Pracuj.pl ↔ rekrutacja (23.11.2026): podpowiedź po
 * tytule jest zaznaczona, ale łączy człowiek; rekruter widzi tylko stan;
 * kolejka „bez rekrutacji” przypisuje z podpowiedzi i ostrzega przy kilku.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import type { PracujAd, PracujAdsPanel, PracujQueueItem } from "@/lib/api/jobAd";

import {
  PracujAdPairing,
  pairedMessage,
  plural,
  type PracujAdPairingApi,
} from "../PracujAdPairing";
import { PracujUnpairedAds, type PracujUnpairedApi } from "../PracujUnpairedAds";

function ad(overrides: Partial<PracujAd> = {}): PracujAd {
  return {
    strefa_id: "8819139",
    title: "Młodszy Kierownik Projektu (k/m/x)",
    applications: 20,
    logged_applications: 25,
    first_seen_at: "2026-11-20T12:00:00Z",
    last_seen_at: "2026-11-22T14:47:00Z",
    live: true,
    suggested: false,
    paired_at: null,
    ...overrides,
  };
}

function panel(overrides: Partial<PracujAdsPanel> = {}): PracujAdsPanel {
  return { paired: [], options: [], last_import_at: "2026-11-22T14:47:00Z", ...overrides };
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function pairingApi(): PracujAdPairingApi {
  return {
    pairPracujAd: vi.fn(async (_jobId: number, strefaId: string) => ({
      strefa_id: strefaId,
      added: 22,
      already: 3,
      skipped: 0,
      job_not_open: false,
    })),
    unpairPracujAd: vi.fn(async () => undefined),
  };
}

beforeEach(() => vi.clearAllMocks());

describe("plural i komunikat", () => {
  it("odmienia po polsku", () => {
    expect([1, 2, 5, 12, 22, 25].map((n) => plural(n, "osoba", "osoby", "osób"))).toEqual([
      "osoba",
      "osoby",
      "osób",
      "osób",
      "osoby",
      "osób",
    ]);
  });

  it("mówi, ile osób trafiło do „Nowi”", () => {
    expect(
      pairedMessage({ strefa_id: "1", added: 22, already: 3, skipped: 1, job_not_open: false }),
    ).toBe(
      "Połączone: 22 osoby trafiły do „Nowi”, 3 już są w rekrutacji, 1 zatrzymały bramki (np. czarna lista, konflikt klienta).",
    );
  });
});

describe("PracujAdPairing", () => {
  it("zaznacza podpowiedź i łączy dopiero po kliknięciu", async () => {
    const api = pairingApi();
    wrap(
      <PracujAdPairing
        jobId={789232}
        canPair
        api={api}
        panel={panel({
          options: [
            ad({ suggested: true }),
            ad({ strefa_id: "8816949", title: "Starszy Kierownik Projektu (k/m/x)" }),
          ],
        })}
      />,
    );

    expect(screen.getByRole("radio", { name: /Młodszy Kierownik/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(api.pairPracujAd).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("pracuj-ad-pair"));
    await waitFor(() => expect(api.pairPracujAd).toHaveBeenCalledWith(789232, "8819139"));
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith(
        "Połączone: 22 osoby trafiły do „Nowi”, 3 już są w rekrutacji.",
      ),
    );
  });

  it("bez podpowiedzi wybór czeka za przyciskiem", () => {
    wrap(<PracujAdPairing jobId={1} canPair api={pairingApi()} panel={panel({ options: [ad()] })} />);

    expect(screen.queryByTestId("pracuj-ad-picker")).toBeNull();
    fireEvent.click(screen.getByTestId("pracuj-ad-pick-open"));
    expect(screen.getByTestId("pracuj-ad-picker")).toBeDefined();
    // Nic nie jest zaznaczone, więc nie da się połączyć na ślepo.
    expect(screen.getByTestId("pracuj-ad-pair")).toBeDisabled();
  });

  it("rekruter widzi połączone ogłoszenie, ale bez wyboru i bez „Odłącz”", () => {
    wrap(
      <PracujAdPairing
        jobId={1}
        canPair={false}
        api={pairingApi()}
        panel={panel({ paired: [ad({ paired_at: "2026-11-23T08:00:00Z" })], options: [ad({ strefa_id: "2", suggested: true })] })}
      />,
    );

    expect(screen.getByTestId("pracuj-ad-paired")).toHaveTextContent("nr 8819139");
    expect(screen.queryByRole("button", { name: "Odłącz" })).toBeNull();
    expect(screen.queryByTestId("pracuj-ad-picker")).toBeNull();
  });

  it("rekruter bez połączenia nie widzi nic", () => {
    const { container } = wrap(
      <PracujAdPairing jobId={1} canPair={false} api={pairingApi()} panel={panel({ options: [ad()] })} />,
    );
    expect(container.querySelector("[data-testid='pracuj-ad-pairing']")).toBeNull();
  });
});

describe("PracujUnpairedAds", () => {
  function queueApi(items: PracujQueueItem[]): PracujUnpairedApi {
    return {
      pracujUnpaired: vi.fn(async () => items),
      pairPracujAd: vi.fn(async (_jobId: number, strefaId: string) => ({
        strefa_id: strefaId,
        added: 11,
        already: 0,
        skipped: 0,
        job_not_open: false,
      })),
      markPracujInternal: vi.fn(async () => undefined),
    };
  }

  it("przypisuje z podpowiedzi i ostrzega przy kilku rekrutacjach o tym tytule", async () => {
    const api = queueApi([
      {
        ...ad({ strefa_id: "8822988", title: "Tester Automatyczny (k/m/x)", logged_applications: 11 }),
        suggestions: [{ job_id: 789240, title: "Tester Automatyczny", delivery_lead_name: null }],
        more_suggestions: 0,
      },
      {
        ...ad({ strefa_id: "8823010", title: "Tester Manualny (k/m/x)" }),
        suggestions: [
          { job_id: 789238, title: "Tester Manualny x4", delivery_lead_name: null },
          { job_id: 789231, title: "Tester Manualny (ZOB-3241)", delivery_lead_name: null },
        ],
        more_suggestions: 0,
      },
    ]);
    wrap(<PracujUnpairedAds api={api} />);

    expect(await screen.findByText(/Na Pracuj.pl bez rekrutacji w NEXUSIE · 2/)).toBeDefined();
    expect(screen.getByText("Kilka rekrutacji o tym tytule — wybierz właściwą.")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: /Przypisz do: Tester Automatyczny/ }));
    await waitFor(() => expect(api.pairPracujAd).toHaveBeenCalledWith(789240, "8822988"));
  });

  it("pusta lista nie rysuje sekcji", async () => {
    const api = queueApi([]);
    const { container } = wrap(<PracujUnpairedAds api={api} />);
    await waitFor(() => expect(api.pracujUnpaired).toHaveBeenCalled());
    expect(container.querySelector("[data-testid='pracuj-unpaired']")).toBeNull();
  });

  it("awaria nie wygląda jak pusta lista", async () => {
    const api = queueApi([]);
    api.pracujUnpaired = vi.fn(async () => {
      throw new Error("500");
    });
    wrap(<PracujUnpairedAds api={api} />);
    expect(
      await screen.findByText("Nie udało się wczytać ogłoszeń z Pracuj.pl bez rekrutacji"),
    ).toBeDefined();
  });
});
