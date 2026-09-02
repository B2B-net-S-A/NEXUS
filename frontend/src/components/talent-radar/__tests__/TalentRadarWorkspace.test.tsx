import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Powrót z profilu kandydata montuje tę stronę OD ZERA — test pokrywa więc
 * PRAWDZIWĄ naprawianą ścieżkę: sessionStorage → efekt hydracji → stan →
 * render wyników. Mockowana jest wyłącznie sieć (axiosowa instancja `api`)
 * i capability (warstwa auth) — nie warstwa persystencji, o którą tu chodzi.
 */

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  assignToJob: vi.fn(),
}));

vi.mock("@/lib/api", () => {
  const api = {
    get: (...args: unknown[]) => mocks.apiGet(...args),
    post: (...args: unknown[]) => mocks.apiPost(...args),
  };
  return {
    __esModule: true,
    default: api,
    api,
    recommendationsApi: {
      assignToJob: (...args: unknown[]) => mocks.assignToJob(...args),
    },
    extractErrorMsg: (e: unknown) => String(e),
  };
});

vi.mock("@/hooks/useCapability", () => ({
  __esModule: true,
  useCapability: () => true,
}));

import { ToastProvider } from "@/components/Toast";
import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";
import {
  TALENT_RADAR_SESSION_KEY,
  type TalentRadarSessionState,
} from "@/lib/talent-radar-session";

const SAVED_SEARCH: TalentRadarSessionState = {
  recruitment: {
    id: 71,
    title: "Senior Python Developer",
    clientId: 7,
    clientName: "Acme Sp. z o.o.",
  },
  title: "Senior Python Developer",
  text: "Szukamy osoby z Pythonem, FastAPI i Postgresem — minimum 5 lat doświadczenia.",
  budgetMax: "180",
  excludeRemoteOnly: false,
  championProfile: null,
  championSummary: null,
  response: {
    results: [
      {
        candidate_id: 101,
        total: 87,
        semantic: { points: 40, max: 60, reason: null },
        skills: { points: 10, max: 10, reason: null },
        salary: {
          points: null,
          max: null,
          reason: null,
          status: "not_applicable",
        },
        location: { points: 5, max: 5, reason: null },
        availability: { points: 5, max: 5, reason: null },
        champion_fit: { points: 0, max: 0, reason: null },
        matching_must: ["python", "fastapi"],
        gap_must: ["postgres"],
        matching_nice: ["docker"],
        gap_nice: [],
        penalties: [],
        fit_confidence: 0.8,
        candidate: {
          id: 101,
          name: "Jan",
          lastname: "Kowalski",
          location: "Warszawa",
          competence_category: "software_development",
          years_it_experience: 7,
          availability_status: "actively_looking",
          champion: false,
          avatar_url: null,
        },
      },
    ],
    meta: {
      pool_size: 1000,
      eligible_size: 800,
      returned: 1,
      degraded: false,
      reason: null,
    },
  },
};

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <TalentRadarWorkspace />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  mocks.apiGet.mockReset();
  mocks.apiPost.mockReset();
  mocks.assignToJob.mockReset();
  mocks.assignToJob.mockResolvedValue({ data: { status: "assigned" } });
  // Jedyny GET na tej stronie: otwarte rekrutacje dla pickera.
  mocks.apiGet.mockResolvedValue({
    data: {
      items: [
        {
          id: 71,
          title: "Senior Python Developer",
          client_id: 7,
          client_name: "Acme Sp. z o.o.",
        },
      ],
    },
  });
});

describe("TalentRadarWorkspace — snapshot roboczy przeżywa powrót", () => {
  it("bez snapshotu startuje od pustego formularza", async () => {
    renderWorkspace();
    expect(
      await screen.findByText("Zacznij od wklejenia requestu"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Jan Kowalski")).not.toBeInTheDocument();
  });

  it("odtwarza formularz i wyniki z sessionStorage (powrót z profilu)", async () => {
    sessionStorage.setItem(
      TALENT_RADAR_SESSION_KEY,
      JSON.stringify(SAVED_SEARCH),
    );
    renderWorkspace();

    // Wyniki wróciły — bez ponownego wyszukiwania (zero POST-ów).
    expect(await screen.findByText("Jan Kowalski")).toBeInTheDocument();
    expect(mocks.apiPost).not.toHaveBeenCalled();

    // Formularz wrócił razem z nimi: rekrutacja w pickerze i treść requestu.
    expect(
      screen.getByRole("combobox", { name: /Rekrutacja/ }),
    ).toHaveTextContent("Senior Python Developer · Acme Sp. z o.o.");
    expect(screen.getByLabelText("Treść requestu")).toHaveValue(
      SAVED_SEARCH.text,
    );

    // Link do profilu niesie back-ref — profil pokaże „Wróć do Talent Radaru".
    expect(
      screen.getByRole("link", { name: "Otwórz profil" }),
    ).toHaveAttribute("href", "/candidates/101?from=talent-radar");
  });

  it("pierwszy render nie nadpisuje snapshotu pustym stanem (wyścig hydracji)", async () => {
    sessionStorage.setItem(
      TALENT_RADAR_SESSION_KEY,
      JSON.stringify(SAVED_SEARCH),
    );
    renderWorkspace();
    await screen.findByText("Jan Kowalski");

    const stored = JSON.parse(
      sessionStorage.getItem(TALENT_RADAR_SESSION_KEY) ?? "null",
    ) as TalentRadarSessionState | null;
    expect(stored?.text).toBe(SAVED_SEARCH.text);
    expect(stored?.response?.results).toHaveLength(1);
  });

  it("przypisuje wynik jednym kliknięciem do rekrutacji ze snapshotu", async () => {
    sessionStorage.setItem(
      TALENT_RADAR_SESSION_KEY,
      JSON.stringify(SAVED_SEARCH),
    );
    renderWorkspace();

    const assignButton = await screen.findByRole("button", {
      name: /Przypisz Jan Kowalski do rekrutacji Senior Python Developer/,
    });
    fireEvent.click(assignButton);

    await waitFor(() => {
      expect(mocks.assignToJob).toHaveBeenCalledWith(101, 71);
    });
    expect(
      await screen.findByRole("button", {
        name: "Jan Kowalski — przypisano do rekrutacji",
      }),
    ).toBeDisabled();
  });

  it("edycja formularza aktualizuje snapshot", async () => {
    renderWorkspace();
    const textarea = await screen.findByLabelText("Treść requestu");
    fireEvent.change(textarea, {
      target: { value: "Nowy opis roli do zapamiętania" },
    });

    await waitFor(() => {
      const stored = JSON.parse(
        sessionStorage.getItem(TALENT_RADAR_SESSION_KEY) ?? "null",
      ) as TalentRadarSessionState | null;
      expect(stored?.text).toBe("Nowy opis roli do zapamiętania");
    });
  });

  it("zepsuty snapshot nie wywraca strony — czysty start", async () => {
    sessionStorage.setItem(TALENT_RADAR_SESSION_KEY, "{nie-json");
    renderWorkspace();
    expect(
      await screen.findByText("Zacznij od wklejenia requestu"),
    ).toBeInTheDocument();
  });
});
