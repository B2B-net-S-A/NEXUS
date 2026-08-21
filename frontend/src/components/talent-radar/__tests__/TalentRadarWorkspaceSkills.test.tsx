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
}));

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

vi.mock("@/lib/talent-radar-api", () => ({
  talentRadarApi: {
    search: (...args: unknown[]) => mocks.search(...args),
    parseChampion: (...args: unknown[]) => mocks.parseChampion(...args),
  },
}));

vi.mock("@/lib/api", () => ({
  recommendationsApi: { assignToJob: vi.fn() },
  extractErrorMsg: (error: unknown) =>
    (error as { message?: string })?.message ?? "błąd",
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showError: mocks.showError,
    showSuccess: mocks.showSuccess,
  }),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapability: () => true,
}));

vi.mock("@/components/talent-radar/TalentRadarRecruitmentPicker", () => ({
  TalentRadarRecruitmentPicker: ({
    onChange,
  }: {
    onChange: (recruitment: {
      id: number;
      title: string;
      clientId: number;
      clientName: string;
    }) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          id: 11,
          title: "Senior Python Developer",
          clientId: 1,
          clientName: "Klient",
        })
      }
    >
      Wybierz rekrutację (mock)
    </button>
  ),
}));

import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";

const PARSED = {
  champion_profile: { role_name: "Senior Python Developer" },
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
  });

  it("wysyła must/nice z `parse-champion` do wyszukiwania", async () => {
    const user = renderWorkspace();
    await user.click(screen.getByRole("button", { name: /Wybierz rekrutację/ }));
    await uploadProfile(user);

    await user.click(screen.getByRole("button", { name: /Szukaj kandydatów/ }));

    await waitFor(() => expect(mocks.search).toHaveBeenCalled());
    expect(mocks.search.mock.calls[0][0]).toMatchObject({
      client_id: 1,
      must_skills: ["Python", "FastAPI"],
      nice_skills: ["Kubernetes"],
    });
  });

  it("przycisk „Usuń” zabiera wymagania razem z profilem", async () => {
    const user = renderWorkspace();
    await user.click(screen.getByRole("button", { name: /Wybierz rekrutację/ }));
    await uploadProfile(user);
    await user.click(screen.getByRole("button", { name: "Usuń" }));

    // Bez profilu wyszukiwanie idzie z wklejonej treści — wymagania z
    // usuniętego dokumentu nie mogą po cichu sterować rankingiem.
    await user.type(
      screen.getByLabelText("Treść requestu"),
      "Szukamy senior python developera z FastAPI i Postgresem w projekcie.",
    );
    await user.click(screen.getByRole("button", { name: /Szukaj kandydatów/ }));

    await waitFor(() => expect(mocks.search).toHaveBeenCalled());
    const body = mocks.search.mock.calls[0][0];
    expect(body.must_skills).toBeUndefined();
    expect(body.nice_skills).toBeUndefined();
  });
});
