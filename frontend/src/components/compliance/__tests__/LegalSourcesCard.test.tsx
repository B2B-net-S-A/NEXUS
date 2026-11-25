import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => get(...a), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

import { LegalSourcesCard } from "@/components/compliance/LegalSourcesCard";
import {
  EMPTY_CORPUS,
  actLine,
  legalSourceGroups,
  plural,
  reviewLine,
} from "@/components/compliance/legal-sources-model";
import type { LegalActStatus, LegalSources } from "@/lib/api/legalSources";

// Fikcyjne liczby i daty — repo jest publiczne.
function act(overrides: Partial<LegalActStatus> = {}): LegalActStatus {
  return {
    key: "kc",
    short_name: "KC",
    title: "Kodeks cywilny",
    source: "eli",
    ident: "DU/1964/93",
    in_registry: true,
    fetch_status: "ok",
    fetch_error: null,
    checked_at: "2099-03-02T05:00:00Z",
    versions: 2,
    current: {
      ident: "DU/2099/11",
      valid_from: "2099-01-15",
      published_on: "2099-02-01",
      url: "https://example.test/kc",
      format: "pdf",
      provisions: 1200,
      vectors: 900,
      amendments_after: [],
    },
    ...overrides,
  };
}

function sources(overrides: Partial<LegalSources> = {}): LegalSources {
  return {
    acts: [
      act(),
      act({ key: "kp", short_name: "KP", title: "Kodeks pracy", current: { ...act().current!, amendments_after: [{ id: "DU/2099/50", date: "2099-02-20" }] } }),
      act({ key: "rodo", short_name: "RODO", title: "RODO", source: "eurlex", versions: 1 }),
    ],
    acts_total: 3,
    acts_ready: 3,
    provisions_total: 3600,
    embeddings_enabled: true,
    documents: {
      case_law: { count: 22, latest_fetched_at: "2099-03-01T03:00:00Z" },
      templates: { repo: 21, client_clauses: 3, custom_approved: 1 },
      framework_contracts: { contracts: 5, amendments: 12 },
    },
    template_review: { open: 2, last_created_at: "2099-03-02T06:00:00Z" },
    ...overrides,
  };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LegalSourcesCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
});

describe("Źródła asystenta prawnego — model", () => {
  it("odmienia liczebniki jak w języku polskim", () => {
    expect(plural(1, "umowa", "umowy", "umów")).toBe("umowa");
    expect(plural(3, "umowa", "umowy", "umów")).toBe("umowy");
    expect(plural(12, "umowa", "umowy", "umów")).toBe("umów");
    expect(plural(22, "umowa", "umowy", "umów")).toBe("umowy");
    expect(plural(25, "umowa", "umowy", "umów")).toBe("umów");
  });

  it("grupy: przepisy z datą sprawdzenia, zmiany po tekście jednolitym, nasze dokumenty, same linki", () => {
    const [law, ours, links] = legalSourceGroups(sources());
    expect(law.empty).toBeUndefined();
    expect(law.rows.map((r) => [r.name, r.state])).toEqual([
      ["KC, KP", "sprawdzone 2.03.2099"],
      ["RODO", "sprawdzone 2.03.2099"],
      ["Zmiany po tekście jednolitym", "tekst jednolity ich nie obejmuje"],
      ["Orzeczenia SN i sądów powszechnych", "22 orzeczenia"],
    ]);
    expect(ours.rows.map((r) => r.state)).toEqual(["5 umów, 12 aneksów", "21 wzorów, 3 klientów", "1 zatwierdzony"]);
    expect(links.rows[0]).toMatchObject({ name: "LEX, Gofin", state: "tylko link — nie do modelu", tone: "danger" });
  });

  it("nieudane pobranie aktu to ostrzeżenie, nie zielony stan", () => {
    const [law] = legalSourceGroups(sources({ acts: [act(), act({ key: "kp", short_name: "KP", fetch_status: "failed" })] }));
    expect(law.rows[0]).toMatchObject({ state: "1 z 2 do ponowienia", tone: "warning" });
    expect(actLine(act({ current: null, fetch_status: "failed" }))).toMatchObject({ detail: "nie udało się pobrać", tone: "warning" });
    expect(actLine(act()).detail).toBe("stan na 15.01.2099 · 2 wersje");
  });

  it("pusty korpus mówi to wprost i zostawia orzeczenia", () => {
    const [law] = legalSourceGroups(
      sources({ acts: [act({ current: null, checked_at: null, fetch_status: "pending", versions: 0 })], acts_ready: 0 }),
    );
    expect(law.empty).toBe(EMPTY_CORPUS);
    expect(law.rows.map((r) => r.name)).toEqual(["Orzeczenia SN i sądów powszechnych"]);
  });

  it("linia „Przejrzyj wzór”: ostatnie założenie albo „brak”", () => {
    expect(reviewLine({ open: 0, last_created_at: null })).toMatch(/ostatnio: brak$/);
    expect(reviewLine({ open: 2, last_created_at: "2099-03-02T06:00:00Z" })).toMatch(/ostatnio: 2\.03\.2099 · otwarte: 2$/);
  });
});

describe("Źródła asystenta prawnego — karta", () => {
  it("pokazuje dane z GET /api/legal/sources", async () => {
    get.mockResolvedValue({ data: sources() });
    renderCard();
    expect(screen.getByText("Wczytywanie źródeł…")).toBeInTheDocument();
    expect(await screen.findByText("5 umów, 12 aneksów")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/legal/sources");
    expect(screen.getByText("tylko link — nie do modelu")).toBeInTheDocument();
    expect(screen.getByText(/ostatnio: 2\.03\.2099/)).toBeInTheDocument();
    const details = screen.getByText(/Akty w korpusie \(3 z 3\)/).closest("details");
    expect(details).not.toBeNull();
    expect(within(details as HTMLElement).getAllByText("stan na 15.01.2099 · 2 wersje")).toHaveLength(2);
    expect(within(details as HTMLElement).getByText("stan na 15.01.2099 · 1 wersja")).toBeInTheDocument();
  });

  it("błąd serwera to komunikat z API i ponowienie, nie pusta karta", async () => {
    get.mockImplementation(async () => {
      throw Object.assign(new Error("boom"), { response: { status: 500, data: { detail: "Korpus chwilowo niedostępny." } } });
    });
    renderCard();
    expect(await screen.findByRole("alert")).toHaveTextContent("Korpus chwilowo niedostępny.");
    expect(screen.getByRole("button", { name: /spróbuj/i })).toBeInTheDocument();
    expect(screen.queryByText("Nasze dokumenty")).toBeNull();
  });

  it("403 mówi, kto widzi źródła", async () => {
    get.mockImplementation(async () => {
      throw Object.assign(new Error("403"), { response: { status: 403 } });
    });
    renderCard();
    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.getByText(/dostępem do Generatora umów B2B/)).toBeInTheDocument();
  });

  it("pusty korpus: komunikat w grupie przepisów, reszta karty zostaje", async () => {
    get.mockResolvedValue({ data: sources({ acts: [], acts_total: 0, acts_ready: 0, provisions_total: 0 }) });
    renderCard();
    expect(await screen.findByText(EMPTY_CORPUS)).toBeInTheDocument();
    expect(screen.getByText("Nasze dokumenty")).toBeInTheDocument();
    expect(screen.queryByText(/Akty w korpusie/)).toBeNull();
  });
});
