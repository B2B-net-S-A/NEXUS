/**
 * Dowód przez realnie zepsutą ścieżkę: wymagania z profilu MUSZĄ dojechać
 * do `search`.
 *
 * Backend przyjmuje `must_skills`/`nice_skills` i składa z nich ofertę, ale
 * łańcuch urywał się TUTAJ: `parse-champion` zwraca listy, a workspace
 * zapamiętywał wyłącznie `champion_profile`, który ich nie niesie
 * (`build_champion_dict` ich nie kopiuje). Komplet zielonych testów backendu
 * jest więc zgodny ze stanem, w którym naprawa nic nie zmienia — dlatego ten
 * test jest warunkiem, nie ozdobą.
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
import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";

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

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TalentRadarWorkspace />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

async function uploadProfile(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(
    screen.getByLabelText("Profil Championa (plik)"),
    new File(["profil"], "profil.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }),
  );
  await user.click(await screen.findByRole("button", { name: "Zastosuj / zapisz szkic" }));
  await screen.findByTestId("tr-champion-loaded");
}

describe("TalentRadarWorkspace — wymagania z profilu", () => {
  beforeEach(() => {
    // Radar utrwala formularz w `sessionStorage` (#1217 — powrót z profilu
    // kandydata nie kasuje wyszukiwania). Bez tego profil wgrany w jednym
    // teście przeżywa do następnego: workspace startuje z gotowym Championem,
    // pole „Profil Championa (plik)" w ogóle się nie renderuje (to gałąź
    // „albo-albo"), a test przewraca się na szukaniu pola, nie na tym,
    // czego pilnuje.
    sessionStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
    mocks.search.mockResolvedValue({
      results: [],
      meta: {
        pool_size: 0,
        eligible_size: 0,
        returned: 0,
        degraded: false,
        reason: null,
      },
    });
    mocks.parseChampion.mockResolvedValue(PARSED);
    mocks.interpret.mockImplementation(defaultInterpret);
  });

  it("wysyła must/nice z `parse-champion` do wyszukiwania", async () => {
    const user = renderWorkspace();
    await user.click(screen.getByRole("button", { name: /Wybierz klienta/ }));
    await uploadProfile(user);

    if (screen.queryByRole("button", { name: /Sprawdź wymagania/ })) {
      await user.click(screen.getByRole("button", { name: /Sprawdź wymagania/ }));
    }
    await user.click(await screen.findByRole("button", { name: /Szukaj w całej bazie/ }));

    await waitFor(() => expect(mocks.search).toHaveBeenCalled());
    expect(mocks.search.mock.calls[0][0]).toMatchObject({
      client_id: 1,
      must_skills: ["Python", "FastAPI"],
      nice_skills: ["Kubernetes"],
    });
  });

  it("przycisk „Usuń” zabiera wymagania razem z profilem", async () => {
    const user = renderWorkspace();
    await user.click(screen.getByRole("button", { name: /Wybierz klienta/ }));
    await uploadProfile(user);
    await user.click(screen.getByRole("button", { name: "Usuń" }));

    // Bez profilu wyszukiwanie idzie z wklejonej treści — wymagania z
    // usuniętego dokumentu nie mogą po cichu sterować rankingiem.
    await user.type(
      screen.getByLabelText("Treść requestu"),
      "Szukamy senior python developera z FastAPI i Postgresem w projekcie.",
    );
    if (screen.queryByRole("button", { name: /Sprawdź wymagania/ })) {
      await user.click(screen.getByRole("button", { name: /Sprawdź wymagania/ }));
    }
    await user.click(await screen.findByRole("button", { name: /Szukaj w całej bazie/ }));

    await waitFor(() => expect(mocks.search).toHaveBeenCalled());
    const body = mocks.search.mock.calls[0][0];
    expect(body.must_skills).toEqual(["Python"]); // new text interpretation, not the removed profile
    expect(body.nice_skills).toEqual([]);
    expect(body.requirements_reviewed).toBe(true);
  });
  it("edytuje i czyści wymagania bez przywracania ich z prozy", async () => {
    const user = renderWorkspace();
    await user.click(screen.getByRole("button", { name: /Wybierz klienta/ }));
    await uploadProfile(user);
    await user.click(screen.getByRole("button", { name: /Sprawdź wymagania/ }));
    await user.clear(await screen.findByLabelText("Obowiązkowe"));
    await user.clear(screen.getByLabelText("Dodatkowe"));
    await user.type(screen.getByLabelText("Dodatkowe"), "Python");
    await user.click(screen.getByRole("button", { name: /Szukaj w całej bazie/ }));
    await waitFor(() => expect(mocks.search).toHaveBeenCalled());
    expect(mocks.search.mock.calls[0][0]).toMatchObject({ must_skills: [], nice_skills: ["Python"], requirements_reviewed: true });
  });


});

const REQUEST_TEXT = "Szukamy senior python developera z FastAPI i Postgresem, stawka do 160 zl/h, praca zdalna.";

async function interpretText(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Wybierz klienta/ }));
  await user.type(screen.getByLabelText("Treść requestu"), REQUEST_TEXT);
  await user.click(screen.getByRole("button", { name: /Sprawdź wymagania/ }));
  await screen.findByLabelText("Obowiązkowe");
}

describe("TalentRadarWorkspace — nierozstrzygnięte umiejętności (B3)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();
    mocks.search.mockResolvedValue(undefined);
    mocks.interpret.mockResolvedValue({ must: ["Python"], nice: [], excluded: [], uncertain: ["Kafka", "Docker"] });
  });

  it("„→ obowiązkowe” dopisuje nazwę do obowiązkowych i trafia do wyszukiwania", async () => {
    const user = renderWorkspace();
    await interpretText(user);
    await user.click(screen.getByRole("button", { name: "Kafka do obowiązkowych" }));
    await user.click(screen.getByRole("button", { name: "Docker do dodatkowych" }));

    expect(screen.getByLabelText("Obowiązkowe")).toHaveValue("Python, Kafka");
    expect(screen.getByLabelText("Dodatkowe")).toHaveValue("Docker");
    expect(screen.queryByRole("button", { name: "Kafka do obowiązkowych" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Szukaj w całej bazie/ }));
    await waitFor(() => expect(mocks.search).toHaveBeenCalled());
    expect(mocks.search.mock.calls[0][0]).toMatchObject({ must_skills: ["Python", "Kafka"], nice_skills: ["Docker"] });
  });

  it("„Wszystkie do obowiązkowych” przenosi całą listę", async () => {
    const user = renderWorkspace();
    await interpretText(user);
    await user.click(screen.getByRole("button", { name: "Wszystkie do obowiązkowych" }));
    expect(screen.getByLabelText("Obowiązkowe")).toHaveValue("Python, Kafka, Docker");
    expect(screen.queryByRole("button", { name: "Wszystkie do obowiązkowych" })).not.toBeInTheDocument();
  });
});

describe("TalentRadarWorkspace — podpowiedzi z treści (B3)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();
    mocks.search.mockResolvedValue(undefined);
    mocks.interpret.mockResolvedValue({ must: ["Python"], nice: [], excluded: [], uncertain: [], suggestions: { budget_max_pln_hour: 160, remote_only: true } });
  });

  it("wypełnia pusty budżet raz na treść i tylko pokazuje wskazówkę o pracy zdalnej", async () => {
    const user = renderWorkspace();
    await interpretText(user);
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue(160);
    expect(screen.getByTestId("tr-budget-hint")).toBeVisible();
    expect(screen.getByTestId("tr-remote-hint")).toHaveTextContent("W treści: praca zdalna.");
    expect(screen.getByTestId("tr-exclude-remote-only")).not.toBeChecked();
    expect(screen.getByLabelText("Dni w biurze / tydzień")).toHaveValue(null);

    // Rekruter czyści budżet i ponownie sprawdza tę samą treść — nie wpisujemy go znowu.
    await user.clear(screen.getByLabelText("Budżet PLN/h"));
    await user.type(screen.getByLabelText("Nazwa roli"), "x");
    await user.click(screen.getByRole("button", { name: /Sprawdź wymagania/ }));
    await waitFor(() => expect(mocks.interpret).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue(null);
  });

  it("nie nadpisuje budżetu wpisanego ręcznie", async () => {
    const user = renderWorkspace();
    await user.type(screen.getByLabelText("Budżet PLN/h"), "140");
    await interpretText(user);
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue(140);
    expect(screen.queryByTestId("tr-budget-hint")).not.toBeInTheDocument();
  });
});

describe("TalentRadarWorkspace — zwijany formularz (B3)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();
    mocks.search.mockResolvedValue(undefined);
    mocks.interpret.mockResolvedValue({ must: ["Python", "FastAPI"], nice: [], excluded: [], uncertain: [] });
  });

  it("po uruchomieniu przeglądu zostaje linia podsumowania z „Zmień kryteria”", async () => {
    const user = renderWorkspace();
    await interpretText(user);
    await user.click(screen.getByRole("button", { name: /Szukaj w całej bazie/ }));

    const summary = await screen.findByTestId("tr-criteria-summary");
    expect(summary).toHaveTextContent("Klient");
    expect(summary).toHaveTextContent("obowiązkowe: Python, FastAPI");
    expect(summary.textContent).toContain(`${REQUEST_TEXT.slice(0, 80)}…`);
    expect(screen.queryByLabelText("Treść requestu")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zmień kryteria" }));
    expect(screen.getByLabelText("Treść requestu")).toHaveValue(REQUEST_TEXT);
    expect(screen.queryByTestId("tr-criteria-summary")).not.toBeInTheDocument();
  });
});
