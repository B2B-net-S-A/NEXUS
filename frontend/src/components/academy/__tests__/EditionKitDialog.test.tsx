import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditionKitDialog } from "@/components/academy/EditionKitDialog";
import type { EditionParticipant } from "@/lib/api/academy-edition";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post } }));

function participant(id: number, name: string): EditionParticipant {
  return {
    application_id: id,
    candidate_id: 1000 + id,
    full_name: name,
    email: null,
    city: null,
    status: "signed",
    status_label: "W akademii",
    left: false,
    cohort_month: null,
    contract: { state: "podpisana", at: null },
    hotel: "nie_dotyczy",
    ticket: "nie_dotyczy",
    logistics_note: null,
    kit: { state: "brak", items: [] },
    protocol: null,
  };
}

function laptop(id: number, inventory: string) {
  return {
    id,
    model: { id: 1, category: "laptop", name: "Vostro Testowy", manufacturer: null, price_pln: "2000.00", is_active: true },
    category: "laptop",
    inventory_number: inventory,
    serial_number: `TEST-${id}`,
    imei: null,
    iccid: null,
    phone_number: null,
    access_card_number: null,
    status: "na_stanie",
    ownership: "nasz",
    purchase_date: null,
    location: null,
    notes: null,
    holder: null,
    issue_protocol: null,
  };
}

const EDITION = { programId: 1, month: "2026-11" };

const PEOPLE = [participant(1, "Marta Przykładowa"), participant(2, "Kamil Testowy"), participant(3, "Igor Wymyślony")];

function wrap(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({ data: { items: [laptop(21, "L-2"), laptop(22, "L-1")], total: 2 } });
});

describe("EditionKitDialog", () => {
  it("issues the kit to people with a complete set and reports each person", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({
      data: {
        issued: 1,
        failed: 1,
        results: [
          {
            application_id: 1,
            ok: true,
            link_url: null,
            protocol: { number: "PZO/2026/10/010", holder: { email: null } },
          },
          { application_id: 2, ok: false, status: 409, message: "Pozycji nie da się wydać." },
        ],
      },
    });
    wrap(<EditionKitDialog edition={EDITION} participants={PEOPLE} onClose={vi.fn()} />);
    const model = await screen.findByRole("checkbox", { name: /Vostro Testowy/ });
    expect(screen.getByText("wolnych 2 · potrzeba 3")).toBeInTheDocument();
    await user.click(model);
    await user.click(screen.getByRole("button", { name: "Dalej: przydział" }));
    // Dwa laptopy na trzy osoby: trzecia bez kompletu, nie idzie do wydania.
    expect(screen.getByText("Brakuje sprzętu — bez wydania")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Wydaj, podpis na papierze" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [url, body] = mocks.post.mock.calls[0];
    expect(url).toBe("/api/academy/programs/1/editions/2026-11/issue");
    expect(body.send_link).toBe(false);
    expect(body.participants).toEqual([
      { application_id: 1, lines: [{ item_id: 22 }] },
      { application_id: 2, lines: [{ item_id: 21 }] },
    ]);
    expect(await screen.findByText("Wydano zestawy: 1 z 2")).toBeInTheDocument();
    expect(screen.getByText(/PZO\/2026\/10\/010/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Nie wydano: Pozycji nie da się wydać.");
  });

  it("a failed stock request is an error, not 'no free equipment'", async () => {
    mocks.get.mockRejectedValue({ response: { status: 500, data: {} } });
    wrap(<EditionKitDialog edition={EDITION} participants={PEOPLE} onClose={vi.fn()} />);
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText("Brak wolnego sprzętu na stanie.")).toBeNull();
  });
});
