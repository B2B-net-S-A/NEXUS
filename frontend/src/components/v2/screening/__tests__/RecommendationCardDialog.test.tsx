/**
 * Okno całej karty rekomendacji — od 0424 (07.10.2026) tylko do odczytu:
 * pola karty wpisuje się w formularzu screeningu („Edytuj w screeningu”),
 * zostaje „Kopiuj” w starym formacie.
 */
import type { ComponentProps, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { RecommendationCard } from "@/lib/api/recommendationCards";

const showInfo = vi.fn();
const showError = vi.fn();
const copyTextToClipboard = vi.fn();
let cardData: RecommendationCard;

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError, showInfo }),
}));

vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (...args: unknown[]) => copyTextToClipboard(...args),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const CARD: RecommendationCard = {
  candidate_id: 1,
  job_id: 2,
  exists: true,
  fields: { rate: { raw: "120 zł/h", value: 120, source: "manual" } },
  previous: {},
  suggestions: {},
  questions: [],
  completeness: { status: "partial", filled: 1, total: 10, missing: [] },
  labels: { rate: "Stawka" },
  editable_fields: ["rate"],
  legacy_text: "Stawka: 120 zł/h",
};

vi.mock("@/lib/api/recommendationCards", () => ({
  useRecommendationCard: () => ({ data: cardData, isLoading: false, isError: false }),
}));

import { RecommendationCardDialog, screeningFormHref } from "../RecommendationCardDialog";

function mount(props: Partial<ComponentProps<typeof RecommendationCardDialog>> = {}) {
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RecommendationCardDialog
        open
        onOpenChange={onOpenChange}
        candidateId={1}
        jobId={2}
        candidateName="Tomasz Wzorcowy"
        {...props}
      />
    </QueryClientProvider>,
  );
  return onOpenChange;
}

describe("RecommendationCardDialog — tylko do odczytu (0424)", () => {
  beforeEach(() => {
    showInfo.mockReset();
    showError.mockReset();
    copyTextToClipboard.mockReset();
    cardData = CARD;
  });

  it("nie ma pól edycji ani zapisu karty", () => {
    mount();
    expect(screen.getByText("120 zł/h")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Zapisz/ })).toBeNull();
    // Karta z notatki żyje w formularzu screeningu — bez kafli źródła.
    expect(screen.queryByRole("radio", { name: /Wklej tekst/ })).toBeNull();
  });

  it("„Edytuj w screeningu” bez panelu prowadzi linkiem do formularza w rekrutacji", () => {
    mount();
    const link = screen.getByRole("link", { name: /Edytuj w screeningu/ });
    expect(link).toHaveAttribute("href", "/jobs/2?candidate=1&panel=screening");
    expect(screeningFormHref(2, 1)).toBe("/jobs/2?candidate=1&panel=screening");
  });

  it("„Edytuj w screeningu” z panelem woła akcję panelu", () => {
    const onEditInScreening = vi.fn();
    mount({ onEditInScreening });
    fireEvent.click(screen.getByRole("button", { name: /Edytuj w screeningu/ }));
    expect(onEditInScreening).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: /Edytuj w screeningu/ })).toBeNull();
  });

  it("w trybie tylko do odczytu nie ma „Edytuj w screeningu”", () => {
    mount({ readOnly: true });
    expect(screen.queryByRole("link", { name: /Edytuj w screeningu/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Edytuj w screeningu/ })).toBeNull();
  });

  it("„Kopiuj” kopiuje kartę w starym formacie", async () => {
    copyTextToClipboard.mockResolvedValue(true);
    mount();
    fireEvent.click(screen.getByRole("button", { name: /Kopiuj/ }));
    await waitFor(() => expect(copyTextToClipboard).toHaveBeenCalledWith("Stawka: 120 zł/h"));
    expect(showInfo).toHaveBeenCalledWith("Skopiowano kartę w starym formacie.");
  });
});
