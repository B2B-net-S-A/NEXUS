/**
 * Okno „Szukaj z requestu" na liście kandydatów (22.09.2026) przekazuje
 * radarowi gotowe wejście. Radar ma wtedy pokazać wyłącznie wybraną ścieżkę
 * i sam przejść do kroku „Sprawdź wymagania" — rekruter nie klika drugi raz
 * tego, co już podał w oknie.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  parseChampion: vi.fn(),
  showError: vi.fn(),
  showSuccess: vi.fn(),
  interpret: vi.fn(),
}));

const defaultInterpret = async (body: { must_skills?: string[]; nice_skills?: string[] }) => ({
  must: body.must_skills ?? ["Python"], nice: body.nice_skills ?? [], excluded: ["Java"], uncertain: [] as string[],
});

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/full-candidate-search-api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/full-candidate-search-api")>(),
  candidateSearchApi: {
    start: async ({ radar }: { radar: unknown }) => { await mocks.search(radar); return { run_id: "run", state: "queued" }; },
    page: async () => ({ run_id: "run", state: "complete", versions: {}, results: [],
      counts: { population: 0, pending: 0, evaluated: 0, failed: 0, eligible: 0, excluded: 0, needs_verification: 0 },
      ranking_complete: true, total_after_threshold: 0, next_offset: null }),
  },
}));

vi.mock("@/lib/talent-radar-api", () => ({
  talentRadarApi: {
    interpret: (...args: unknown[]) => mocks.interpret(...args),
    search: (...args: unknown[]) => mocks.search(...args),
    parseChampion: (...args: unknown[]) => mocks.parseChampion(...args),
  },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  // `HIDDEN_LABELS_PL` (0278) jest realną stałą, potrzebną przez
  // `TalentRadarResults` do renderu chipów „ukryto N" — sam `extractErrorMsg`
  // tego nie niesie.
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, post: async (_url: string, { profile }: { profile: import("@/lib/api").ChampionProfile }) => {
      const cp = structuredClone(profile);
      cp.stack.must = String(cp.stack.must).split("\n").filter(Boolean).map(name => ({ name }));
      cp.stack.nice = String(cp.stack.nice).split("\n").filter(Boolean).map(name => ({ name }));
      cp.basics.rate_value = Number(cp.basics.rate_value) || null;
      return { data: { champion_profile: cp } };
    } },
    extractErrorMsg: (error: unknown) =>
      (error as { message?: string })?.message ?? "błąd",
  };
});

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.showError, showSuccess: mocks.showSuccess }),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapability: () => true,
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (state: unknown) => unknown) =>
    select({ user: { id: 7, effective_section_access: { pipeline: "read" } } }),
}));

vi.mock("@/components/talent-radar/SavedRequestSearch", () => ({
  SavedRequestSearch: ({ initialJob, hidePicker }: { initialJob?: { title: string }; hidePicker?: boolean }) => (
    <div data-testid="saved-request">{initialJob?.title}|{String(hidePicker)}</div>
  ),
}));

vi.mock("@/components/talent-radar/TalentRadarClientPicker", () => ({
  TalentRadarClientPicker: ({
    onChange,
  }: {
    onChange: (client: { id: number; name: string }) => void;
  }) => (
    <button type="button" onClick={() => onChange({ id: 1, name: "Klient" })}>
      Wybierz klienta (mock)
    </button>
  ),
}));

import { EMPTY_CHAMPION_PROFILE } from "@/lib/api";
import {
  TalentRadarWorkspace,
  type TalentRadarInitialRequest,
} from "@/components/talent-radar/TalentRadarWorkspace";

const PARSED = {
  champion_profile: { ...EMPTY_CHAMPION_PROFILE, basics: { ...EMPTY_CHAMPION_PROFILE.basics, role_name: "Senior Python Developer", rate_value: 150, work_mode: "hybrydowo", candidate_location_pref: "Kraków" }, stack: { must: [{name: "Python"}, {name: "FastAPI"}], nice: [{name: "Kubernetes"}], notes: "" } },
  must_skills: ["Python", "FastAPI"],
  nice_skills: ["Kubernetes"],
  summary: {
    role_name: "Senior Python Developer",
    must_count: 2,
    nice_count: 1,
    rate_value: 150,
    location: "Kraków",
    work_mode: "hybrydowo",
  },
};


function renderWith(initial: TalentRadarInitialRequest) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TalentRadarWorkspace embedded initial={initial} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const REQUEST_TEXT = "Szukamy Senior Python Developera z FastAPI, praca hybrydowa w Krakowie, B2B.";

describe("TalentRadarWorkspace — wejście z okna „Szukaj z requestu”", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();
    mocks.parseChampion.mockResolvedValue(PARSED);
    mocks.interpret.mockImplementation(defaultInterpret);
  });

  it("tekst: wypełnia formularz i sam sprawdza wymagania (bez przełącznika źródła)", async () => {
    renderWith({
      source: "text",
      text: REQUEST_TEXT,
      client: { id: 4, name: "Bank SA" },
      budget: "170",
      officeDays: "2",
      officeCity: "Kraków",
    });
    await waitFor(() => expect(mocks.interpret).toHaveBeenCalledTimes(1));
    expect(mocks.interpret.mock.calls[0][0]).toMatchObject({ client_id: 4, text: REQUEST_TEXT });
    expect(await screen.findByLabelText("Obowiązkowe")).toHaveValue("Python");
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue(170);
    expect(screen.getByLabelText("Dni w biurze / tydzień")).toHaveValue(2);
    expect(screen.getByLabelText("Miasto biura")).toHaveValue("Kraków");
    expect(screen.queryByRole("button", { name: "Zapisana rekrutacja" })).toBeNull();
    // Wyszukiwanie w bazie rusza dopiero po sprawdzeniu — nie samo.
    expect(mocks.search).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Szukaj w całej bazie/ })).toBeEnabled();
  });

  it("za krótka treść nie odpala sprawdzenia — powód zostaje przy formularzu", async () => {
    renderWith({ source: "text", text: "Java", client: { id: 4, name: "Bank SA" } });
    expect(await screen.findByText(/min\. 30 znaków/)).toBeInTheDocument();
    expect(mocks.interpret).not.toHaveBeenCalled();
  });

  it("plik: parsuje od razu, a wymagania sprawdza po zatwierdzeniu profilu", async () => {
    const user = renderWith({
      source: "file",
      file: new File(["profil"], "profil.docx"),
      client: { id: 4, name: "Bank SA" },
    });
    await waitFor(() => expect(mocks.parseChampion).toHaveBeenCalledTimes(1));
    expect(mocks.interpret).not.toHaveBeenCalled();
    await user.click(await screen.findByRole("button", { name: "Zastosuj / zapisz szkic" }));
    await waitFor(() => expect(mocks.interpret).toHaveBeenCalledTimes(1));
    expect(mocks.interpret.mock.calls[0][0]).toMatchObject({ client_id: 4, must_skills: ["Python", "FastAPI"] });
  });

  it("rekrutacja: pokazuje wyłącznie wyniki zapisanej rekrutacji", () => {
    renderWith({ source: "job", job: { id: 9, title: "Java Developer" } });
    expect(screen.getByTestId("saved-request")).toHaveTextContent("Java Developer|true");
  });
});
