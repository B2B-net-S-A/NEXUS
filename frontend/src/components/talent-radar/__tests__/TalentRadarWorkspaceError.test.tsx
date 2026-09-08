/**
 * Dowód przez realnie zepsutą ścieżkę: workspace MUSI przekazać błąd dalej.
 *
 * Sam `TalentRadarResults` umie już renderować awarię, ale defekt siedział
 * piętro wyżej — `onError` robił `setResponse(null)` i kończył na toaście.
 * Test odrzuca `talentRadarApi.search` i sprawdza, co zostaje NA EKRANIE.
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
    interpret: async (body: { must_skills?: string[]; nice_skills?: string[] }) => ({
      must: body.must_skills ?? ["Python"], nice: body.nice_skills ?? [], excluded: ["Java"], uncertain: [],
    }),
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
    extractErrorMsg: (error: unknown) =>
      (error as { message?: string })?.message ?? "błąd",
  };
});

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.showError }),
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

import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";

const QUERY_TEXT =
  "Szukamy senior python developera z doświadczeniem w FastAPI i Postgresie.";

async function searchOnce() {
  const user = userEvent.setup();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TalentRadarWorkspace />
    </QueryClientProvider>,
  );
  await user.click(screen.getByRole("button", { name: /Wybierz klienta/ }));
  await user.type(screen.getByLabelText("Treść requestu"), QUERY_TEXT);
  if (screen.queryByRole("button", { name: /Sprawdź wymagania/ })) {
      await user.click(screen.getByRole("button", { name: /Sprawdź wymagania/ }));
    }
    await user.click(await screen.findByRole("button", { name: /Szukaj kandydatów/ }));
  return user;
}

describe("TalentRadarWorkspace — błąd wyszukiwania", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("awaria zostaje na ekranie, a nie tylko w znikającym toaście", async () => {
    mocks.search.mockRejectedValue(
      Object.assign(new Error("boom"), { response: { status: 500 } }),
    );

    await searchOnce();

    expect(
      await screen.findByText("Wyszukiwanie nie doszło do skutku"),
    ).toBeInTheDocument();
    // Ekran startowy to twierdzenie „jeszcze nic nie zrobiłeś" — po nieudanej
    // próbie jest nieprawdą.
    expect(
      screen.queryByText("Zacznij od wklejenia requestu"),
    ).not.toBeInTheDocument();
    // Toast zostaje jako natychmiastowy sygnał — nie zastępujemy go, dokładamy.
    expect(mocks.showError).toHaveBeenCalled();
  });

  it("zmiana klienta unieważnia stary błąd razem z wynikami", async () => {
    mocks.search.mockRejectedValue(
      Object.assign(new Error("boom"), { response: { status: 500 } }),
    );

    const user = await searchOnce();
    await screen.findByText("Wyszukiwanie nie doszło do skutku");

    await user.click(screen.getByRole("button", { name: /Wybierz klienta/ }));

    await waitFor(() =>
      expect(
        screen.queryByText("Wyszukiwanie nie doszło do skutku"),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText("Zacznij od wklejenia requestu"),
    ).toBeInTheDocument();
  });
});
