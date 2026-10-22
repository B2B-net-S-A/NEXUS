/**
 * Okno „Rozmowa z menedżerem” z karty „Popyt do sprawdzenia” (22.10.2026):
 * sekcja „Czego potrzebuje dział?” wymaga rozstrzygnięcia, oceny są
 * opcjonalne, „Potrzeba potwierdzona” zapisuje rolę, liczbę osób i technologie
 * z mapy działu i prowadzi na `/jobs/new` z adresu serwera, „Nie teraz” nie
 * nawiguje. Bez menedżera na karcie wybiera się go z osób klienta. Dane fikcyjne.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  push: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));
// Radix Select w jsdom nie otwiera listy — natywny <select> o tym samym kontrakcie.
vi.mock("@/components/ui/select", () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string;
    onValueChange: (next: string) => void;
    children: React.ReactNode;
  }) => (
    <select data-testid="select" value={value} onChange={(e) => onValueChange(e.target.value)}>
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}));

import { ClientFeedbackDialog } from "@/components/care/ClientFeedbackDialog";
import { jobsNewHref, type DemandContext } from "@/lib/api/care-clients";
import { clientOrgWithHealth, peopleTechMap } from "@/app/preview/hr-client-people/fixtures";
import { useAuthStore, type User } from "@/store/auth";

const TODAY = "2026-10-22";
const DEMAND: DemandContext = {
  key: "demand:7001:77",
  roles: ["Java Developer"],
  area: { id: 301, name: "Płatności" },
  source: "widział",
};

function renderDialog(manager: { id: number; name: string } | null) {
  mocks.get.mockImplementation(async (url: string) =>
    url.endsWith("/tech-map")
      ? { data: peopleTechMap(TODAY) }
      : { data: clientOrgWithHealth(TODAY) },
  );
  const onOpenChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ClientFeedbackDialog
        clientId={7001}
        clientName="Bank Przykładowy"
        manager={manager}
        open
        onOpenChange={onOpenChange}
        demand={DEMAND}
      />
    </QueryClientProvider>,
  );
  return { onOpenChange };
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.push.mockReset();
  mocks.showToast.mockReset();
  useAuthStore.setState({
    user: { id: 102, name: "Kamil Testowy", role: "delivery_lead", roles: ["delivery_lead"] } as unknown as User,
    hydrated: true,
  });
});

describe("ClientFeedbackDialog · popyt", () => {
  it("bez rozstrzygnięcia nic nie wysyła", async () => {
    renderDialog({ id: 8203, name: "Katarzyna Płatnicza" });
    expect(screen.getByText("Czego potrzebuje dział Płatności?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz rozmowę" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Zaznacz, co z potrzebą działu.");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("„Potrzeba potwierdzona”: rola, liczba osób, technologie z mapy działu i przejście na /jobs/new", async () => {
    mocks.post.mockResolvedValue({
      data: { id: 1, contract_ids: [], jobs_new_url: "/jobs/new?client=7001&hm=8203&skills=801&title=Java" },
    });
    const { onOpenChange } = renderDialog({ id: 8203, name: "Katarzyna Płatnicza" });
    fireEvent.click(screen.getByRole("radio", { name: "Potrzeba potwierdzona" }));
    expect(screen.getByLabelText(/Rola/)).toHaveValue("Java Developer");
    fireEvent.change(screen.getByLabelText("Ile osób"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Od kiedy"), { target: { value: "2026-12" } });
    fireEvent.click(await screen.findByRole("button", { name: "Kafka" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz i otwórz rekrutację" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [url, body] = mocks.post.mock.calls[0];
    expect(url).toBe("/api/care/clients/7001/feedback");
    expect(body).toMatchObject({
      contact_id: 8203,
      scores: [],
      demand: {
        key: "demand:7001:77",
        outcome: "confirmed",
        role: "Java Developer",
        headcount: 2,
        start_month: "2026-12",
        skill_ids: [803],
      },
    });
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith("/jobs/new?client=7001&hm=8203&skills=801&title=Java"),
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("bez menedżera idzie samo rozstrzygnięcie (bez contact_id); odmowa serwera zostaje w oknie", async () => {
    mocks.post.mockRejectedValue(
      Object.assign(new Error("HTTP 403"), {
        response: { status: 403, data: { detail: "Popyt rozstrzyga Delivery Lead klienta." } },
      }),
    );
    renderDialog(null);
    // Bez menedżera pola opinii są ukryte — zapisałyby się tylko z menedżerem.
    expect(screen.getByText(/Bez menedżera zapisze się tylko decyzja o popycie/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Co mówi klient")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Nieaktualne" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz rozmowę" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const body = mocks.post.mock.calls[0][1] as Record<string, unknown>;
    expect(body).not.toHaveProperty("contact_id");
    expect(body).not.toHaveProperty("note");
    expect(body).not.toHaveProperty("scores");
    expect(body.demand).toEqual({ key: "demand:7001:77", outcome: "stale" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Popyt rozstrzyga Delivery Lead klienta.");
  });

  it("„Nie teraz” zapisuje samo rozstrzygnięcie i nie nawiguje; menedżer z osób klienta", async () => {
    mocks.post.mockResolvedValue({ data: { id: 2, contract_ids: [] } });
    renderDialog(null);
    fireEvent.click(screen.getByRole("radio", { name: "Nie teraz" }));
    const picker = await screen.findByRole("option", { name: /Katarzyna Płatnicza/ });
    fireEvent.change(picker.closest("select")!, { target: { value: "8203" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz rozmowę" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post.mock.calls[0][1]).toMatchObject({
      contact_id: 8203,
      demand: { key: "demand:7001:77", outcome: "not_now" },
    });
    expect(mocks.push).not.toHaveBeenCalled();
  });
});

describe("jobsNewHref", () => {
  it("klient, menedżer, technologie i tytuł; puste pomija", () => {
    expect(jobsNewHref({ clientId: 12, hmId: 345, skillIds: [1, 2], title: "Java Developer" })).toBe(
      "/jobs/new?client=12&hm=345&skills=1,2&title=Java+Developer",
    );
    expect(jobsNewHref({ clientId: 12, hmId: null, skillIds: [], title: " " })).toBe(
      "/jobs/new?client=12",
    );
  });
});
