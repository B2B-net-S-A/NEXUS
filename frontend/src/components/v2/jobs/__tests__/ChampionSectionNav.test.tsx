/**
 * `ChampionSectionNav` — lewa kolumna kroku 02 (program „flow w języku C2", PR 5/7).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionSectionNav } from "@/components/v2/jobs/ChampionSectionNav";
import { CHAMPION_SECTIONS } from "@/lib/champion-section-state";

const getMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    championApi: {
      ...actual.championApi,
      get: (...args: unknown[]) => getMock(...args),
    },
  };
});

function renderNav(jobId = 501) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ChampionSectionNav jobId={jobId} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
});

describe("ChampionSectionNav — lista sekcji", () => {
  it("renderuje sześć sekcji jako linki do ich kotwic, nawet zanim dane wrócą", () => {
    getMock.mockReturnValue(new Promise(() => {})); // never resolves
    renderNav();
    for (const section of CHAMPION_SECTIONS) {
      const link = screen.getByRole("link", { name: section.label });
      expect(link).toHaveAttribute("href", `#${section.anchor}`);
    }
  });

  it("woła championApi.get z jobId", () => {
    getMock.mockReturnValue(new Promise(() => {}));
    renderNav(777);
    expect(getMock).toHaveBeenCalledWith(777);
  });
});

describe("ChampionSectionNav — stan sekcji", () => {
  it("profil pusty — brak awarii, sekcje się renderują (nawet gdy nic nie jest wypełnione)", async () => {
    getMock.mockResolvedValue({ data: { job_id: 501, champion_profile: {} } });
    renderNav();
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    for (const section of CHAMPION_SECTIONS) {
      expect(screen.getByRole("link", { name: section.label })).toBeInTheDocument();
    }
  });

  it("awaria zapytania NIE usuwa nawigacji — pokazuje notatkę zamiast pustki", async () => {
    getMock.mockRejectedValue(new Error("network"));
    renderNav();
    expect(
      await screen.findByText("Nie udało się sprawdzić stanu sekcji."),
    ).toBeInTheDocument();
    // Lista sekcji zostaje mimo awarii — to nawigacja, nie źródło prawdy.
    for (const section of CHAMPION_SECTIONS) {
      expect(screen.getByRole("link", { name: section.label })).toBeInTheDocument();
    }
  });

  it("profil wypełniony ze znacznikiem AI — kropka sekcji 'basics' ma tytuł „Z AI”", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 501,
        champion_profile: {
          basics: { role_name: "Senior Python Developer" },
          _source: "champion_upload",
        },
      },
    });
    renderNav();
    const basicsLabel = CHAMPION_SECTIONS.find((s) => s.id === "basics")!.label;
    await waitFor(() => {
      const link = screen.getByRole("link", { name: basicsLabel });
      const dot = link.querySelector("span[title]");
      expect(dot).toHaveAttribute("title", "Z AI");
    });
  });
});
