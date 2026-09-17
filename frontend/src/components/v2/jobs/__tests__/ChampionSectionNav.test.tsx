/**
 * `ChampionSectionNav` — lewa kolumna kroku 02 (program „flow w języku C2", PR 5/7).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionSectionNav } from "@/components/v2/jobs/ChampionSectionNav";
import {
  CHAMPION_SECTION_STATE_LABEL,
  CHAMPION_SECTIONS,
} from "@/lib/champion-section-state";

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
      const link = screen.getByRole("link", { name: (n: string) => n.startsWith(section.label) });
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
      expect(screen.getByRole("link", { name: (n: string) => n.startsWith(section.label) })).toBeInTheDocument();
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
      expect(screen.getByRole("link", { name: (n: string) => n.startsWith(section.label) })).toBeInTheDocument();
    }
  });

  it("profil wypełniony ze znacznikiem AI — kropka sekcji 'basics' ma tytuł „wypełnione”", async () => {
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
      // Dostępna nazwa = etykieta + stan dla czytnika ekranu („…, wypełnione").
      const link = screen.getByRole("link", { name: (n: string) => n.startsWith(basicsLabel) });
      const dot = link.querySelector("span[title]");
      // Pochodzenie „z AI" nie jest stanem sekcji (znacznik całoprofilowy).
      expect(dot).toHaveAttribute("title", CHAMPION_SECTION_STATE_LABEL.filled);
    });
  });
});

describe("ChampionSectionNav — kolejność kroku 02", () => {
  it("stack (3) stoi ZARAZ po podstawach (1), przed prozą (2 · 4 · 5) i klientem (6)", () => {
    getMock.mockReturnValue(new Promise(() => {}));
    renderNav();
    const order = screen
      .getAllByRole("link")
      .map((link) => link.textContent ?? "");
    expect(order[0]).toContain("Podstawowe informacje");
    expect(order[1]).toContain("Stack technologiczny");
    expect(order[2]).toContain("Co wpisać (search)");
    expect(order[5]).toContain("O kliencie");
  });

  it("numery w etykietach zostają szablonowe — wiążą ekran ze wzorem Word", () => {
    getMock.mockReturnValue(new Promise(() => {}));
    renderNav();
    const order = screen
      .getAllByRole("link")
      .map((link) => link.textContent ?? "");
    // Drugi wpis na liście nosi numer 3, nie 2 — kolejność jest robocza,
    // numeracja szablonowa.
    expect(order[1].startsWith("3 · ")).toBe(true);
  });
});

// Audyt B48: profil sprzed 09.2026 trzyma stack w kolumnach rekrutacji
// (`job_values`) — edytor go stamtąd wczytuje (`seedChampionFromJob`),
// a nawigacja liczyła stan z samego `champion_profile` i pokazywała „puste"
// przy sekcji, która obok była „wypełnione" z listą technologii.
describe("ChampionSectionNav — stack z kolumn rekrutacji (profil legacy)", () => {
  it("pusty stack profilu + niepuste kolumny → kropka „wypełnione”, jak w edytorze", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 501,
        champion_profile: { stack: { must: [], nice: [], notes: "" } },
        job_values: { must: "Angular\nTypeScript", nice: "" },
      },
    });
    renderNav();
    const stackLabel = CHAMPION_SECTIONS.find((s) => s.id === "stack")!.label;
    await waitFor(() => {
      const link = screen.getByRole("link", { name: (n: string) => n.startsWith(stackLabel) });
      expect(link.querySelector("span[title]")).toHaveAttribute(
        "title",
        CHAMPION_SECTION_STATE_LABEL.filled,
      );
    });
  });

  it("pusty stack i puste kolumny → nadal „puste”", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 501, champion_profile: {}, job_values: { must: "", nice: "" } },
    });
    renderNav();
    const stackLabel = CHAMPION_SECTIONS.find((s) => s.id === "stack")!.label;
    await waitFor(() => {
      const link = screen.getByRole("link", { name: (n: string) => n.startsWith(stackLabel) });
      expect(link.querySelector("span[title]")).toHaveAttribute(
        "title",
        CHAMPION_SECTION_STATE_LABEL.empty,
      );
    });
  });
});

// PR 5: sekcja 1 „Podstawowe informacje” wczytuje puste pola z kolumn
// rekrutacji w edytorze (`seedChampionFromJob`) — nawigacja MUSI liczyć stan
// z TEGO SAMEGO seeda, inaczej kropka „basics” pokazuje „puste” obok
// wypełnionego pola „Nazwa roli” (parytet z audytem B48, ale dla sekcji 1).
describe("ChampionSectionNav — sekcja 1 z pól rekrutacji (parytet z edytorem, PR 5)", () => {
  it("pusty profil + niepusta kolumna (stawka) → kropka „wypełnione”, jak w edytorze", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 501,
        champion_profile: {},
        job_values: { rate_value: 120 },
      },
    });
    renderNav();
    const basicsLabel = CHAMPION_SECTIONS.find((s) => s.id === "basics")!.label;
    await waitFor(() => {
      const link = screen.getByRole("link", { name: (n: string) => n.startsWith(basicsLabel) });
      expect(link.querySelector("span[title]")).toHaveAttribute(
        "title",
        CHAMPION_SECTION_STATE_LABEL.filled,
      );
    });
  });

  it("pusty profil i puste kolumny → nadal „puste”", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 501, champion_profile: {}, job_values: {} },
    });
    renderNav();
    const basicsLabel = CHAMPION_SECTIONS.find((s) => s.id === "basics")!.label;
    await waitFor(() => {
      const link = screen.getByRole("link", { name: (n: string) => n.startsWith(basicsLabel) });
      expect(link.querySelector("span[title]")).toHaveAttribute(
        "title",
        CHAMPION_SECTION_STATE_LABEL.empty,
      );
    });
  });
});
