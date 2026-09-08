/**
 * `ChampionVerificationChecklist` — wariant „rows" kroku 02 (fala 3 programu
 * „flow w języku C2") i wspólny predykat `championVerificationDone`.
 *
 * Dwie rzeczy, które ten plik ma trzymać:
 *  1. licznik doku i wiersze checklisty liczą z JEDNEJ funkcji (inaczej lista
 *     zaczyna przeczyć liczbie nad nią),
 *  2. wariant „rows" nie jest drugą kopią formularzy — „Oznacz" otwiera ten sam
 *     formularz i woła tę samą mutację co układ sekcyjny.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChampionVerificationChecklist,
  championVerificationDone,
} from "@/components/ChampionVerificationChecklist";
import { ToastProvider } from "@/components/Toast";
import type { ChampionBriefing, ChampionVerification } from "@/lib/api";

const verifyMock = vi.fn();
const consultantSuggestionsMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { get: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }) },
    championApi: {
      ...actual.championApi,
      verify: (...args: unknown[]) => verifyMock(...args),
      consultantSuggestions: (...args: unknown[]) =>
        consultantSuggestionsMock(...args),
    },
  };
});

vi.mock("@/components/calls/AudioPlayer", () => ({
  default: () => <div data-testid="mock-audio-player" />,
}));

const PENDING: ChampionVerification = {
  client: { status: "pending", key_corrections: "", confirmed_as_is: false },
  consultant: { status: "pending", insights: "", skip_reason: "" },
};

function renderRows(
  verification: ChampionVerification = PENDING,
  briefing: ChampionBriefing = { status: "pending" },
  canEdit = true,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ChampionVerificationChecklist
          jobId={501}
          verification={verification}
          briefing={briefing}
          canEdit={canEdit}
          variant="rows"
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  verifyMock.mockReset();
  verifyMock.mockResolvedValue({ data: {} });
  consultantSuggestionsMock.mockReset();
  consultantSuggestionsMock.mockResolvedValue({ data: [] });
});

describe("championVerificationDone", () => {
  it("pusta weryfikacja — nic nie jest domknięte", () => {
    expect(championVerificationDone(PENDING, { status: "pending" })).toEqual({
      client: false,
      consultant: false,
      briefing: false,
    });
  });

  it("brak danych czyta się jak brak weryfikacji, nie jak wyjątek", () => {
    expect(championVerificationDone(null, null)).toEqual({
      client: false,
      consultant: false,
      briefing: false,
    });
    expect(championVerificationDone(undefined, undefined).client).toBe(false);
  });

  it("`skipped` po stronie konsultanta ZAMYKA pozycję (świadoma decyzja DL)", () => {
    const v = {
      ...PENDING,
      consultant: {
        status: "skipped" as const,
        insights: "",
        skip_reason: "nowy klient",
      },
    };
    expect(championVerificationDone(v, { status: "pending" }).consultant).toBe(true);
  });

  it("briefing liczy się dopiero jako `attached`", () => {
    expect(championVerificationDone(PENDING, { status: "attached" }).briefing).toBe(
      true,
    );
  });
});

describe("ChampionVerificationChecklist — wariant „rows”", () => {
  it("renderuje trzy wiersze gotowości bez własnej ramki i nagłówka sekcji", () => {
    renderRows();
    expect(screen.getByTestId("readiness-row-client-verification")).toBeInTheDocument();
    expect(
      screen.getByTestId("readiness-row-consultant-verification"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("readiness-row-briefing")).toBeInTheDocument();
    // Powłoka sekcyjna (nagłówek „Weryfikacja i briefing" + badge) nie
    // renderuje się — wiersze wchodzą do JEDNEJ listy doku.
    expect(
      screen.queryByTestId("champion-verification-checklist"),
    ).not.toBeInTheDocument();
  });

  it("stany wierszy odpowiadają danym: niezweryfikowane = do uzupełnienia", () => {
    renderRows();
    expect(screen.getByTestId("readiness-row-client-verification")).toHaveAttribute(
      "data-state",
      "todo",
    );
  });

  it("konsultant `skipped` to stan NEUTRALNY, nie zielony i nie ostrzeżenie", () => {
    renderRows({
      ...PENDING,
      consultant: {
        status: "skipped" as const,
        insights: "",
        skip_reason: "nowy klient",
      },
    });
    const row = screen.getByTestId("readiness-row-consultant-verification");
    expect(row).toHaveAttribute("data-state", "neutral");
    expect(row).toHaveTextContent("Pominięto: nowy klient");
  });

  it("„Oznacz” otwiera TEN SAM formularz co układ sekcyjny i zapisuje tą samą mutacją", async () => {
    const user = userEvent.setup();
    renderRows();

    await user.click(screen.getByTestId("client-verification-toggle"));

    // Pola formularza są jedną definicją dzieloną przez oba warianty.
    expect(await screen.findByTestId("client-verification-method")).toBeInTheDocument();
    await user.click(screen.getByTestId("client-verification-confirmed"));
    await user.click(screen.getByTestId("client-verification-submit"));

    expect(verifyMock).toHaveBeenCalledWith(501, {
      side: "client",
      client: { method: "call", key_corrections: "", confirmed_as_is: true },
    });
  });

  it("bez prawa edycji wiersze zostają, ale akcji nie ma (odczyt nie jest wyłączony)", () => {
    renderRows(PENDING, { status: "pending" }, false);
    expect(screen.getByTestId("readiness-row-briefing")).toBeInTheDocument();
    expect(screen.queryByTestId("briefing-toggle")).not.toBeInTheDocument();
    expect(screen.queryByTestId("client-verification-toggle")).not.toBeInTheDocument();
  });
});
