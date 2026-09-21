import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  mocks.brandedGet.mockResolvedValue({ data: { status: "none" } });
});

describe("SavedCvView — linki dla klienta po „CV Wysłane”", () => {
  it("pyta o linki CAŁEJ pary (kandydat, rekrutacja), nie bieżącego etapu, i pokazuje etap linku", async () => {
    mocks.listForRecruitment.mockResolvedValue({
      data: [
        {
          revoke_key: "v2$abc", token_preview: "v2 · abc123…", is_v2: true, revoked: false,
          created_at: "2026-09-10T10:00:00Z", created_by_name: "Anna Nowak",
          expires_at: "2099-01-01T00:00:00Z", view_count: 3, max_views: null,
          stage_id: 555, stage_name: "Zweryfikowany",
        },
      ],
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
    mocks.listForRecruitment.mockResolvedValue({ data: [] });
    mount();
    expect(await screen.findByText(/W tej rekrutacji nie utworzono jeszcze linku/)).toBeInTheDocument();
  });

  it("awaria odczytu linków to alert z „Ponów”", async () => {
    mocks.listForRecruitment.mockRejectedValue(new Error("boom"));
    mount();
    expect(await screen.findByText(/Nie udało się wczytać: linki dla klienta/)).toBeInTheDocument();
    expect(screen.queryByText(/nie utworzono jeszcze linku/)).toBeNull();
  });
});
