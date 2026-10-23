/**
 * „Dział u klienta” w oknie rozmowy: awaria listy działów nie może wyglądać
 * jak klient bez działów z podsuniętym „Nowy dział…” (audyt 22.10.2026, F88).
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const areas = vi.hoisted(() => ({
  current: {} as Record<string, unknown>,
  refetch: vi.fn(),
}));

vi.mock("@/lib/api/care", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/care")>()),
  useClientAreas: () => ({ ...areas.current, refetch: areas.refetch }),
}));
vi.mock("@/lib/api/client-people", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client-people")>()),
  useClientOrg: () => ({ data: undefined, isError: false, isLoading: false }),
}));

import { ClientStateSection } from "../ClientStateSection";
import { emptyClientState } from "../conversation-form";

function renderArea() {
  return render(
    <ClientStateSection
      knownTechnologies={1}
      clientId={30}
      view={undefined}
      loading={false}
      failed={false}
      form={{ ...emptyClientState(), modes: { area: "change" } }}
      onChange={() => {}}
    />,
  );
}

beforeEach(() => {
  areas.refetch.mockReset();
});

describe("ClientStateSection — dział u klienta", () => {
  it("przy awarii listy działów mówi o błędzie i daje „Ponów”, bez listy z „Nowy dział…”", async () => {
    areas.current = {
      data: undefined,
      isError: true,
      isLoading: false,
      isSuccess: false,
      error: { response: { status: 500, data: { detail: "Błąd serwera" } } },
    };
    renderArea();
    expect(screen.queryByRole("combobox", { name: "Dział u klienta" })).toBeNull();
    expect(screen.getByText(/Nie udało się wczytać działów klienta|Błąd serwera/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Ponów" }));
    expect(areas.refetch).toHaveBeenCalled();
  });

  it("po udanym odczycie pokazuje listę działów", () => {
    areas.current = {
      data: [{ id: 1, name: "Płatności kartowe" }],
      isError: false,
      isLoading: false,
      isSuccess: true,
    };
    renderArea();
    expect(screen.getByRole("combobox", { name: "Dział u klienta" })).toBeInTheDocument();
  });
});
