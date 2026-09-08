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
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { CHAMPION_SECTIONS } from "@/lib/champion-section-state";
import { useAuthStore, type User } from "@/store/auth";

/** Etykiety sekcji mają JEDNO źródło — test nie może mieć własnej kopii. */
const BASICS_LABEL = CHAMPION_SECTIONS.find((s) => s.id === "basics")!.label;

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
  it("profil pusty — trzy karty z chipem „puste” plus chip grupy „3 z 3 sekcji puste”", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 1, champion_profile: {} },
    });
    renderEditor(1);
    await screen.findByText(BASICS_LABEL);
    // Karty samodzielne: 1 · Podstawowe, 3 · Stack, 6 · O kliencie.
    expect(screen.getAllByText("puste")).toHaveLength(3);
    // Sekcje 2 · 4 · 5 mają JEDEN wspólny chip.
    expect(screen.getByText("3 z 3 sekcji puste")).toBeInTheDocument();
    expect(screen.queryByText("wypełnione")).not.toBeInTheDocument();
    expect(screen.queryByText("Z importu (AI)")).not.toBeInTheDocument();
  });

  it("profil wypełniony BEZ znacznika pochodzenia — wypełnione sekcje dostają „wypełnione”, nigdy „Z AI”", async () => {
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
    await screen.findByText(BASICS_LABEL);
    // Sekcje 1 i 3 wypełnione; 6 pusta; grupa 2·4·5 pusta w całości.
    expect(screen.getAllByText("wypełnione")).toHaveLength(2);
    expect(screen.getAllByText("puste")).toHaveLength(1);
    expect(screen.getByText("3 z 3 sekcji puste")).toBeInTheDocument();
    expect(screen.queryByText("Z importu (AI)")).not.toBeInTheDocument();
  });

  it("profil wypełniony ZE znacznikiem pochodzenia (import dokumentu) — jeden chip „Z importu (AI)” na nagłówku, sekcje tylko „wypełnione”", async () => {
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
    await screen.findByText(BASICS_LABEL);
    // Znacznik pochodzenia jest całoprofilowy: JEDEN chip na nagłówku, sekcje
    // dostają tylko „wypełnione" (backend nie wie, które sekcje przepisano).
    expect(screen.getAllByText("Z importu (AI)")).toHaveLength(1);
    expect(screen.getAllByText("puste")).toHaveLength(2);
    // Sekcja „Podstawowe informacje" jest wypełniona — chip mówi TYLKO tyle;
    // pochodzenie nie jest stanem sekcji.
    expect(screen.getAllByText("wypełnione")).toHaveLength(1);
    expect(screen.queryByText("Z AI")).not.toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — układ makiety kroku 02", () => {
  it("stack stoi PRZED prozą: to on zasila must_skills/nice_skills", async () => {
    getMock.mockResolvedValue({ data: { job_id: 1, champion_profile: {} } });
    const { container } = renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    const headings = Array.from(container.querySelectorAll("h3")).map(
      (h) => h.textContent ?? "",
    );
    const stackAt = headings.findIndex((h) => h.includes("Stack technologiczny"));
    const proseAt = headings.findIndex((h) => h.includes("Co wpisać (search)"));
    expect(stackAt).toBeGreaterThanOrEqual(0);
    expect(proseAt).toBeGreaterThan(stackAt);
  });

  it("gdy 2 · 4 · 5 są PUSTE — skrót z dwoma polami i „Rozwiń pełne sekcje”, kotwice sekcji zostają", async () => {
    getMock.mockResolvedValue({ data: { job_id: 1, champion_profile: {} } });
    const { container } = renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    expect(screen.getByLabelText(/Frazy do searchu/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/O projekcie \(2 zdania\)/i)).toBeInTheDocument();
    // Pełne sekcje jeszcze się nie renderują…
    expect(screen.queryByText(/Obowiązki na stanowisku/i)).not.toBeInTheDocument();
    // …ale link z nawigacji ma dokąd prowadzić.
    expect(container.querySelector("#champion-section-project")).not.toBeNull();
    expect(container.querySelector("#champion-section-screening")).not.toBeNull();
  });

  it("„Rozwiń pełne sekcje” pokazuje trzy pełne formularze", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue({ data: { job_id: 1, champion_profile: {} } });
    renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    await user.click(screen.getByTestId("expand-champion-prose"));

    expect(await screen.findByText(/Obowiązki na stanowisku/i)).toBeInTheDocument();
    expect(screen.getByText(/Firmy docelowe/i)).toBeInTheDocument();
  });

  it("gdy KTÓRAKOLWIEK z 2 · 4 · 5 jest wypełniona — pełne sekcje od razu, bez chowania danych", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 1,
        champion_profile: { project: { about: "Migracja płatności.", responsibilities: "" } },
      },
    });
    renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    expect(screen.getByText(/Obowiązki na stanowisku/i)).toBeInTheDocument();
    expect(screen.queryByTestId("expand-champion-prose")).not.toBeInTheDocument();
    expect(screen.getByText("2 z 3 sekcji puste")).toBeInTheDocument();
  });

  it("etykiety stacku niosą liczniki, a zdanie o synchronizacji nazywa konsumentów", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 1,
        champion_profile: {
          stack: { must: [{ name: "Python" }, { name: "Kafka" }], nice: [{ name: "AWS" }], notes: "" },
        },
      },
    });
    const { container } = renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    expect(screen.getByText("Musi mieć · 2")).toBeInTheDocument();
    expect(screen.getByText("Mile widziane · 1")).toBeInTheDocument();
    expect(container.textContent).toContain("ranking C2");
  });
});

describe("ChampionProfileEditor — weryfikacja/briefing/wyszukiwania przeniesione do doku", () => {
  it("NIE renderuje już checklisty weryfikacji ani rekomendowanych wyszukiwań (przeniesione do JobReadinessDock)", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 1, champion_profile: {} },
    });
    renderEditor(1);
    await screen.findByText(BASICS_LABEL);
    expect(
      screen.queryByTestId("champion-verification-checklist"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("champion-recommended-searches"),
    ).not.toBeInTheDocument();
  });
});
