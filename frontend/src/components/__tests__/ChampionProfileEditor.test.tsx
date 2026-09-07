/**
 * `ChampionProfileEditor` — krok 02 „Zlecenie i Champion" (program „flow w
 * języku C2", PR 5/7): pełna szerokość (bez `max-w`) + chip stanu (pusta /
 * wypełniona / z AI) przy każdej z sześciu sekcji.
 *
 * Testy renderują z `canEdit={false}` (widok recruitera) — to CELOWO omija
 * `ChampionProfileSourcesPanel` i panel „Wygeneruj z opisu klienta (AI)"
 * (oba `{canEdit && (...)}`, więc się nie montują), dzięki czemu jedyne
 * zapytanie sieciowe to `GET …/champion-profile`. Weryfikacja dwustronna +
 * briefing + rekomendowane wyszukiwania NIE renderują się już tutaj — od
 * tego PR-u mieszkają w `JobReadinessDock` (`variant="champion"`), patrz
 * `JobReadinessDock.test.tsx`.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { useAuthStore, type User } from "@/store/auth";

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

const recruiter = {
  id: 7,
  name: "Marta Kowalska",
  email: "marta@example.com",
  role: "recruiter",
  roles: ["recruiter"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: { pipeline: "read" },
} satisfies User;

function renderEditor(jobId: number) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ChampionProfileEditor jobId={jobId} canEdit={false} clientId={null} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  useAuthStore.setState({
    user: recruiter,
    realUser: null,
    token: "token",
    hydrated: true,
  });
});

describe("ChampionProfileEditor — pełna szerokość", () => {
  it("kontener sekcji NIE ma już `max-w-4xl` (krok 02 renderuje edytor na pełną szerokość środka)", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 1, champion_profile: {} },
    });
    const { container } = renderEditor(1);
    await screen.findByText("Profil Championa");
    expect(container.querySelector(".max-w-4xl")).not.toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — chip stanu sekcji", () => {
  it("profil pusty — wszystkie sześć sekcji ma chip „Pusta”", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 1, champion_profile: {} },
    });
    renderEditor(1);
    await screen.findByText("1. Podstawowe informacje");
    expect(screen.getAllByText("Pusta")).toHaveLength(6);
    expect(screen.queryByText("Wypełniona")).not.toBeInTheDocument();
    expect(screen.queryByText("Z importu (AI)")).not.toBeInTheDocument();
  });

  it("profil wypełniony BEZ znacznika pochodzenia — wypełnione sekcje dostają „Wypełniona”, nigdy „Z AI”", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 2,
        champion_profile: {
          basics: { role_name: "Senior Python Developer" },
          stack: { must: [{ name: "Python" }], nice: [], notes: "" },
        },
      },
    });
    renderEditor(2);
    await screen.findByText("1. Podstawowe informacje");
    // Sekcje 1 i 3 wypełnione, 2/4/5/6 puste.
    expect(screen.getAllByText("Wypełniona")).toHaveLength(2);
    expect(screen.getAllByText("Pusta")).toHaveLength(4);
    expect(screen.queryByText("Z importu (AI)")).not.toBeInTheDocument();
  });

  it("profil wypełniony ZE znacznikiem pochodzenia (import dokumentu) — jeden chip „Z importu (AI)” na nagłówku, sekcje tylko „Wypełniona”", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 3,
        champion_profile: {
          basics: { role_name: "Senior Python Developer" },
          _source: "champion_upload",
        },
      },
    });
    renderEditor(3);
    await screen.findByText("1. Podstawowe informacje");
    // Znacznik pochodzenia jest całoprofilowy: JEDEN chip na nagłówku, sekcje
    // dostają tylko „Wypełniona" (backend nie wie, które sekcje przepisano).
    expect(screen.getAllByText("Z importu (AI)")).toHaveLength(1);
    expect(screen.getAllByText("Pusta")).toHaveLength(5);
    // Sekcja „Podstawowe informacje" jest wypełniona — chip mówi TYLKO tyle;
    // pochodzenie nie jest stanem sekcji.
    expect(screen.getAllByText("Wypełniona")).toHaveLength(1);
    expect(screen.queryByText("Z AI")).not.toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — weryfikacja/briefing/wyszukiwania przeniesione do doku", () => {
  it("NIE renderuje już checklisty weryfikacji ani rekomendowanych wyszukiwań (przeniesione do JobReadinessDock)", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 1, champion_profile: {} },
    });
    renderEditor(1);
    await screen.findByText("1. Podstawowe informacje");
    expect(
      screen.queryByTestId("champion-verification-checklist"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("champion-recommended-searches"),
    ).not.toBeInTheDocument();
  });
});
