import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Linki dla klienta są na produkcji wyłączone stałą (#1647). Testy niżej
// sprawdzają ścieżkę z linkami (stała = true); blok „linki wyłączone" sprawdza
// stan produkcyjny.
const linkFlags = vi.hoisted(() => ({ enabled: true }));
vi.mock("@/lib/cv-generator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/cv-generator")>();
  return {
    ...actual,
    get CV_CLIENT_LINKS_UI_ENABLED() {
      return linkFlags.enabled;
    },
  };
});

const mocks = vi.hoisted(() => ({
  originalGet: vi.fn(),
  brandedGet: vi.fn(),
  listForStage: vi.fn(),
  listForRecruitment: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  candidateStageCvApi: {
    original: { get: mocks.originalGet },
    branded: { get: mocks.brandedGet },
    share: { list: mocks.listForStage, listForRecruitment: mocks.listForRecruitment },
  },
  screeningApi: { getForStage: vi.fn() },
}));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({ CVOriginalPreviewModal: () => null }));

import { SavedCvView } from "@/components/v2/recruitment/PanelSavedViews";

import { item } from "./recruitment-fixtures";

const noBranded = { status: "none", stage_id: null, stage_name: null, finalized_at: null };

const person = item(7, { name: "Marek", lastname: "Zieliński", stage: "cv_sent" });

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SavedCvView item={person} stageLabel="CV Wysłane" candidateName="Marek Zieliński" jobTitle="Senior Java" jobId={42} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.originalGet.mockResolvedValue({ data: { has_snapshot: true } });
});

describe("SavedCvView — linki dla klienta po „CV Wysłane”", () => {
  it("pyta o linki CAŁEJ pary (kandydat, rekrutacja), nie bieżącego etapu, i pokazuje etap linku", async () => {
    mocks.listForRecruitment.mockResolvedValue({
      data: {
        items: [
          {
            revoke_key: "v2$abc", token_preview: "v2 · abc123…", is_v2: true, revoked: false,
            created_at: "2026-09-10T10:00:00Z", created_by_name: "Anna Nowak",
            expires_at: "2099-01-01T00:00:00Z", view_count: 3, max_views: null,
            stage_id: 555, stage_name: "Zweryfikowany",
          },
        ],
        branded_cv: noBranded,
      },
    });
    mount();
    expect(await screen.findByText("v2 · abc123…")).toBeInTheDocument();
    expect(screen.getByText(/etap: Zweryfikowany/)).toBeInTheDocument();
    expect(screen.getByText("aktywny")).toBeInTheDocument();
    expect(mocks.listForRecruitment).toHaveBeenCalledWith(7, 42);
    // Lista per etap była tu niemal zawsze pusta — link leży na etapie sprzed ruchu.
    expect(mocks.listForStage).not.toHaveBeenCalled();
  });

  it("pusta lista mówi o rekrutacji, a awaria nie udaje pustki", async () => {
    mocks.listForRecruitment.mockResolvedValue({ data: { items: [], branded_cv: noBranded } });
    mount();
    expect(await screen.findByText(/W tej rekrutacji nie utworzono jeszcze linku/)).toBeInTheDocument();
  });

  it("awaria odczytu linków to alert z „Ponów”", async () => {
    mocks.listForRecruitment.mockRejectedValue(new Error("boom"));
    mount();
    expect(
      await screen.findByText(/Nie udało się wczytać: CV do klienta i linki dla klienta/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/nie utworzono jeszcze linku/)).toBeNull();
    // Awaria nie udaje „brak CV firmowego".
    expect(screen.queryByText(/CV do klienta: brak/)).toBeNull();
  });
});

describe("SavedCvView — odznaka „CV firmowe” czyta PARĘ, nie bieżący etap", () => {
  it("po „CV Wysłane” pokazuje gotowe CV z etapu, na którym leży", async () => {
    mocks.listForRecruitment.mockResolvedValue({
      data: {
        items: [],
        branded_cv: {
          status: "finalized", stage_id: 555, stage_name: "Zweryfikowany",
          finalized_at: "2026-09-10T10:00:00Z",
        },
      },
    });
    mount();
    expect(await screen.findByText("CV do klienta: gotowe · etap: Zweryfikowany")).toBeInTheDocument();
    expect(screen.queryByText(/CV do klienta: brak/)).toBeNull();
    // Odczyt per etap ZAKŁADA szkic na bieżącym etapie — podgląd go nie woła.
    expect(mocks.brandedGet).not.toHaveBeenCalled();
  });

  it("szkic i brak mają własne odznaki", async () => {
    mocks.listForRecruitment.mockResolvedValue({
      data: {
        items: [],
        branded_cv: { status: "draft", stage_id: 556, stage_name: "CV Wysłane", finalized_at: null },
      },
    });
    mount();
    expect(await screen.findByText("CV do klienta: szkic · etap: CV Wysłane")).toBeInTheDocument();
  });

  it("para bez CV firmowego: „brak”", async () => {
    mocks.listForRecruitment.mockResolvedValue({ data: { items: [], branded_cv: noBranded } });
    mount();
    expect(await screen.findByText("CV do klienta: brak")).toBeInTheDocument();
  });
});

describe("SavedCvView — linki dla klienta wyłączone (stan produkcyjny)", () => {
  beforeEach(() => { linkFlags.enabled = false; });
  afterEach(() => { linkFlags.enabled = true; });

  it("nie pokazuje listy linków, ale odznaka CV firmowego zostaje", async () => {
    mocks.listForRecruitment.mockResolvedValue({
      data: { items: [], branded_cv: noBranded },
    });
    mount();
    expect(await screen.findByText("CV do klienta: brak")).toBeInTheDocument();
    expect(screen.queryByText("Linki dla klienta")).toBeNull();
  });
});

