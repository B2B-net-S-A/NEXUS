/**
 * Okno „Przypisz rekrutera” / „Zmień rekrutera” (`POST /api/jobs/{id}/owner`).
 *
 * Od 02.10.2026 rola nazywa się „Rekruter” (dawniej „właściciel projektu”),
 * a przydziela admin, Delivery Lead i Head of Recruitment. Okno tylko
 * przypisuje — osobę zdejmuje „×” w panelu zespołu, z potwierdzeniem.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useFormContext } from "react-hook-form";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReassignOwnerV2 } from "@/components/v2/modals/ReassignOwnerV2";
import type { UserBrief } from "@/components/v2/jobs/ownership-types";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));

vi.mock("@/lib/api", () => ({ default: apiMock, api: apiMock }));
// Pole wyboru (Radix Select) ma własną mechanikę wskaźnika, której jsdom nie
// odtwarza — podmieniamy je na zwykłą listę związaną z TYM SAMYM formularzem.
vi.mock("@/components/v2/forms/fields/RecruiterPickerField", () => ({
  RecruiterPickerField: ({ name }: { name: string }) => {
    const { setValue, watch } = useFormContext();
    const value = watch(name);
    return (
      <select
        aria-label="Osoba"
        value={typeof value === "number" ? String(value) : ""}
        onChange={(event) =>
          setValue(name, event.target.value ? Number(event.target.value) : "")
        }
      >
        <option value="">Wybierz osobę…</option>
        <option value="31">Anna Przykładowa</option>
        <option value="32">Bartek Testowy</option>
      </select>
    );
  },
}));

const bartek: UserBrief = {
  id: 32,
  name: "Bartek Testowy",
  email: "bartek@example.com",
  role: "recruiter",
};

function renderDialog(currentOwner: UserBrief | null = null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  const onOpenChange = vi.fn();
  const onAssigned = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <ReassignOwnerV2
        open
        onOpenChange={onOpenChange}
        jobId={11}
        jobTitle="Backend Engineer"
        currentOwner={currentOwner}
        onAssigned={onAssigned}
      />
    </QueryClientProvider>,
  );
  return {
    onOpenChange,
    onAssigned,
    invalidatedKeys: () =>
      invalidateSpy.mock.calls.map(
        (call) => (call[0] as { queryKey: unknown[] })?.queryKey,
      ),
  };
}

beforeEach(() => {
  for (const mock of Object.values(apiMock)) mock.mockReset();
  apiMock.post.mockResolvedValue({ data: {} });
});

describe("ReassignOwnerV2", () => {
  it("bez rekrutera: „Przypisz rekrutera”, a zapis bez wskazania osoby niczego nie wysyła", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();

    expect(screen.getByRole("heading", { name: "Przypisz rekrutera" })).toBeInTheDocument();
    expect(screen.getByText("Bez rekrutera")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Wybrana osoba od razu zacznie pracować nad rekrutacją — bez akceptacji.",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Wybierz osobę, która ma pracować nad rekrutacją.",
    );
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("przypisanie woła POST /owner, zamyka okno i odświeża obsadę wszędzie", async () => {
    const user = userEvent.setup();
    const { onOpenChange, onAssigned, invalidatedKeys } = renderDialog();

    await user.selectOptions(screen.getByLabelText("Osoba"), "31");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/api/jobs/11/owner", { user_id: 31 }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(onAssigned).toHaveBeenCalledTimes(1);
    const keys = invalidatedKeys();
    for (const key of [["job", 11], ["job", "11"], ["jobs-v2"], ["jobs-quick-counts"], REQUEST_BOARD_QUERY_KEY]) {
      expect(keys).toContainEqual(key);
    }
  });

  it("z rekruterem: „Zmień rekrutera”; ta sama osoba = zamknięcie bez zapisu", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog(bartek);

    expect(screen.getByRole("heading", { name: "Zmień rekrutera" })).toBeInTheDocument();
    expect(screen.getByText("Obecny rekruter")).toBeInTheDocument();
    expect(screen.getByLabelText("Osoba")).toHaveValue("32");
    expect(
      screen.getByText(
        "Wybrana osoba zastąpi obecnego rekrutera i od razu zacznie pracować nad rekrutacją.",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("zmiana na inną osobę zastępuje obecnego rekrutera", async () => {
    const user = userEvent.setup();
    renderDialog(bartek);

    await user.selectOptions(screen.getByLabelText("Osoba"), "31");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/api/jobs/11/owner", { user_id: 31 }),
    );
  });

  it("odmowa serwera zostawia okno z jego zdaniem i odświeża obsadę (ktoś zmienił ją wcześniej)", async () => {
    apiMock.post.mockRejectedValueOnce({
      response: { status: 409, data: { detail: "Ta rekrutacja jest zamknięta." } },
    });
    const user = userEvent.setup();
    const { onOpenChange, onAssigned, invalidatedKeys } = renderDialog();

    await user.selectOptions(screen.getByLabelText("Osoba"), "31");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Ta rekrutacja jest zamknięta.");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(onAssigned).not.toHaveBeenCalled();
    expect(invalidatedKeys()).toContainEqual(["job", "11"]);
  });

  it("okno tylko przypisuje — nie zdejmuje i nie mówi dawnymi nazwami", () => {
    renderDialog(bartek);

    expect(screen.queryByRole("button", { name: /Usuń/ })).not.toBeInTheDocument();
    for (const gone of [/właściciel/i, /Prowadzi/, /Rekruter prowadzący/]) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument();
    }
    expect(apiMock.delete).not.toHaveBeenCalled();
  });
});
