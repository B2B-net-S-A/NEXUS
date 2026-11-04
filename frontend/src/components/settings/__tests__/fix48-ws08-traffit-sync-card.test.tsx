import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Traffit wyłączony na stałe 14.10.2026 (decyzja Artura): karta w Ustawieniach
// mówi to wprost zamiast „TRAFFIT_SYNC_ENABLED=false” (flagi już nie da się
// włączyć) i nie straszy ostrzeżeniem, że import stoi.

const apiMock = vi.hoisted(() => ({ status: vi.fn() }));
vi.mock("@/lib/api", () => ({ traffitSyncApi: apiMock }));

import { TraffitSyncCard } from "../TraffitSyncCard";
import { readCheck } from "@/components/v2/dashboard/custom/SystemStatusTile";

const STATUS = {
  enabled: false,
  running: false,
  max_row_attempts: 5,
  managed_in_nexus_jobs: 3,
  quarantined: [],
  states: [
    {
      phase: "__daily__",
      last_synced_at: "2026-10-12T02:15:00Z",
      last_run_started_at: "2026-10-12T02:15:00Z",
      last_run_finished_at: "2026-10-12T04:00:00Z",
      last_status: "ok",
      stats: null,
    },
  ],
  retired_on: "2026-10-14",
  retired_message:
    "Traffit jest wyłączony od 14.10.2026 — NEXUS nie importuje już danych z Traffita.",
};

function renderCard() {
  apiMock.status.mockResolvedValue(STATUS);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TraffitSyncCard />
    </QueryClientProvider>,
  );
}

describe("TraffitSyncCard po wyłączeniu Traffita", () => {
  it("mówi, że Traffit jest wyłączony od 14.10.2026, bez nazwy zmiennej", async () => {
    renderCard();
    expect(
      await screen.findByText(
        "Wyłączony od 14.10.2026 — NEXUS nie importuje już danych z Traffita.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/TRAFFIT_SYNC_ENABLED/)).not.toBeInTheDocument();
    expect(screen.queryByText(/codziennie o 02:00/)).not.toBeInTheDocument();
  });

  it("nie pokazuje ostrzeżenia o stojącym imporcie", async () => {
    const { container } = renderCard();
    await screen.findByText(/Wyłączony od 14\.10\.2026/);
    expect(container.querySelector('[data-traffit-state="retired"]')).not.toBeNull();
    expect(container.querySelector(".text-amber-600")).toBeNull();
  });

  it("historia ostatniego biegu zostaje widoczna", async () => {
    renderCard();
    expect(await screen.findByText("Ostatni przebieg")).toBeInTheDocument();
  });
});

describe("checks.traffit = disabled na kafelku „Stan systemu”", () => {
  it("to „Wyłączone”, nie awaria ani „Nie wiadomo”", () => {
    expect(readCheck("disabled")).toEqual({ tone: "off", detail: null });
  });
});
