import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SeekingContractorRow } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  showError: vi.fn(),
  showInfo: vi.fn(),
  sendCandidateShortlistEmail: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.showError, showInfo: mocks.showInfo }),
}));

vi.mock("@/lib/api", () => ({
  recommendationsApi: {
    sendCandidateShortlistEmail: mocks.sendCandidateShortlistEmail,
    prepareClientProposal: vi.fn(),
  },
}));

vi.mock("@/components/v2/CompetenceCategoryBadge", () => ({
  CompetenceCategoryName: ({ slug }: { slug: string }) => <span>{slug}</span>,
}));

import { ContractorMatchCard } from "@/components/sourcing/ContractorMatchCard";

function row(): SeekingContractorRow {
  return {
    candidate: {
      id: 7,
      name: "Anna",
      lastname: "Testowa",
      email: null,
      location: null,
      competence_category: null,
      years_it_experience: null,
      availability_status: "open_to_offers",
      champion: false,
      avatar_url: null,
    },
    source: "availability_status",
    contract_end_date: null,
    current_client_id: null,
    top_matches: [],
    below_threshold_count: 0,
  };
}

describe("ContractorMatchCard — shortlist bez rekrutacji", () => {
  beforeEach(() => {
    mocks.showError.mockReset();
    mocks.showInfo.mockReset();
    mocks.sendCandidateShortlistEmail.mockReset();
  });

  it("mówi „Brak rekrutacji…” jako informację, nie błąd", () => {
    // Runda 13 (FRONTB): runda 12 zamieniła alert() na showError, więc brak
    // rekrutacji do wysłania wyglądał jak awaria.
    render(<ContractorMatchCard row={row()} />);

    fireEvent.click(screen.getByTestId("shortlist-7"));

    expect(mocks.showInfo).toHaveBeenCalledWith("Brak rekrutacji do wysłania w shortliście.");
    expect(mocks.showError).not.toHaveBeenCalled();
    expect(mocks.sendCandidateShortlistEmail).not.toHaveBeenCalled();
  });
});
