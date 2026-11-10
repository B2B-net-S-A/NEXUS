import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const requirementEvidence = vi.fn();

vi.mock("@/lib/candidate-search-api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/candidate-search-api")>();
  return {
    ...actual,
    candidateSearchApi: {
      ...actual.candidateSearchApi,
      requirementEvidence: (...a: unknown[]) => requirementEvidence(...a),
    },
  };
});

import { RequirementEvidenceChips } from "@/components/v2/recruitment/RequirementEvidenceChips";

function renderChips(onShowInCv = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <RequirementEvidenceChips
        jobId={5}
        candidateId={10}
        matched={["java", "angular", "rest api"]}
        gaps={["sast"]}
        onShowInCv={onShowInCv}
      />
    </QueryClientProvider>,
  );
  return onShowInCv;
}

beforeEach(() => {
  vi.clearAllMocks();
  requirementEvidence.mockResolvedValue({
    items: {
      java: {
        sources: ["cv", "profile", "note"],
        cv: { snippet: "Certified Java Programmer with 7 years", via: null },
        notes: [{ id: 1, date: "2025-10-08", author: "Ola Testowa", snippet: "Technologie: Java, Spring", via: null }],
        notes_more: 2,
        profile: [{ where: "Lista umiejętności", snippet: "Java, Spring Boot", via: null }],
      },
      angular: {
        sources: ["profile"],
        cv: null,
        notes: [],
        notes_more: 0,
        profile: [{ where: "Pola z Traffita", snippet: "Vue.js, Angular, TypeScript", via: null }],
      },
      "rest api": { sources: [], cv: null, notes: [], notes_more: 0, profile: [] },
    },
  });
});

describe("RequirementEvidenceChips — skąd „✓” (zgłoszenie DL 09.11.2026, wariant B)", () => {
  it("przy każdym „✓” stoi źródło; bez CV dopisek jest wyróżniony", async () => {
    renderChips();
    const list = screen.getByRole("list", { name: "Wymagania must-have" });
    expect(await within(list).findByRole("button", { name: /java · CV, profil, notatka/ })).toBeEnabled();
    const angular = within(list).getByRole("button", { name: /angular · profil/ });
    expect(within(angular).getByText("· profil")).toHaveClass("text-warning-muted-foreground");
    expect(within(list).getByRole("button", { name: /rest api · bez wzmianki/ })).toBeInTheDocument();
    expect(within(list).getByText("sast — nie znaleziono")).toBeInTheDocument();
    expect(requirementEvidence).toHaveBeenCalledWith(5, 10, ["java", "angular", "rest api"], expect.anything());
  });

  it("klik pokazuje cytaty z CV, notatek i profilu, a „Pokaż w CV” otwiera plik na tym słowie", async () => {
    const user = userEvent.setup();
    const onShowInCv = renderChips();
    await user.click(await screen.findByRole("button", { name: /^java/ }));
    const box = screen.getByRole("region", { name: "Skąd ✓ java" });
    expect(within(box).getByText("08.10.2025 · Ola Testowa —", { exact: false })).toBeInTheDocument();
    expect(within(box).getByText(/\+2 kolejne/)).toBeInTheDocument();
    expect(within(box).getByText(/Lista umiejętności/)).toBeInTheDocument();
    await user.click(within(box).getByRole("button", { name: "Pokaż w CV" }));
    expect(onShowInCv).toHaveBeenCalledWith("java");
  });

  it("technologia bez CV: komunikat zamiast cytatu, bez „Pokaż w CV”", async () => {
    const user = userEvent.setup();
    renderChips();
    await user.click(await screen.findByRole("button", { name: /^angular/ }));
    const box = screen.getByRole("region", { name: "Skąd ✓ angular" });
    expect(within(box).getByText(/W tekście CV tego słowa nie ma/)).toBeInTheDocument();
    expect(within(box).queryByRole("button", { name: "Pokaż w CV" })).toBeNull();
    expect(within(box).getByText(/Pola z Traffita/)).toBeInTheDocument();
  });

  it("błąd wczytania źródeł nie wygląda jak brak źródeł", async () => {
    requirementEvidence.mockRejectedValue(new Error("boom"));
    renderChips();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Spróbuj ponownie/);
    // Chipy zostają, ale bez dopisku i bez okna — nic nie udaje „bez wzmianki”.
    const list = screen.getByRole("list", { name: "Wymagania must-have" });
    expect(within(list).getByRole("button", { name: "java" })).toBeDisabled();
    expect(within(list).queryByText(/bez wzmianki/)).toBeNull();
  });
});
