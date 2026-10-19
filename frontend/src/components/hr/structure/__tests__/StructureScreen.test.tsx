/**
 * „Ludzie → Struktura” wg makiety 19.10.2026: schemat kart, przeciągnięcie
 * karty = zmiana przełożonego (ta sama trasa co lista, po potwierdzeniu),
 * panel „Do uporządkowania”, przełącznik na listę. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { hrConfig } from "@/app/preview/hr-fixtures";
import type { HrStructure, StructurePerson } from "@/lib/api/hr-structure";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), toast: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: vi.fn() } }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: mocks.toast }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { StructureScreen } from "../StructureScreen";

function person(id: number, name: string, extra: Partial<StructurePerson> = {}): StructurePerson {
  return {
    user_id: id,
    name,
    email: `osoba${id}@example.com`,
    job_title: "Rekruterka",
    department: null,
    employment_type: "b2b",
    employment_status: "active",
    division: "front_office",
    manager_user_id: null,
    manager_name: null,
    manager_state: "none",
    reports: 0,
    leaving: null,
    m365_hint: null,
    suggested_manager: null,
    ...extra,
  };
}

const kamil = person(1, "Kamil Testowy", { reports: 1, job_title: "Delivery Lead" });
const marta = person(2, "Marta Fikcyjna", {
  reports: 1,
  manager_user_id: 1,
  manager_name: "Kamil Testowy",
  manager_state: "ok",
});
const ewa = person(3, "Ewa Makietowa", {
  manager_user_id: 2,
  manager_name: "Marta Fikcyjna",
  manager_state: "ok",
});
const kacper = person(4, "Kacper Nowicjusz", {
  suggested_manager: { user_id: 1, name: "Kamil Testowy" },
});

const DATA: HrStructure = {
  people: [kamil, marta, ewa, kacper],
  outside_managers: [],
  divisions: [
    { key: "front_office", label: "Front office", head_user_id: 1, head_name: "Kamil Testowy", head_active: true },
    { key: "back_office", label: "Back office", head_user_id: null, head_name: null, head_active: false },
  ],
  total: 4,
  without_manager: 1,
  inactive_manager: 0,
  m365_mismatches: 0,
} as HrStructure;

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StructureScreen config={hrConfig({ people_admin: true })} />
    </QueryClientProvider>,
  );
}

function dataTransfer() {
  const store = new Map<string, string>();
  return {
    setData: (type: string, value: string) => store.set(type, value),
    getData: (type: string) => store.get(type) ?? "",
    effectAllowed: "",
    dropEffect: "",
  };
}

describe("StructureScreen — schemat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/hr/structure") return { data: DATA };
      throw new Error(`nieoczekiwane ${url}`);
    });
    mocks.post.mockResolvedValue({ data: { changed: [3], unchanged: [] } });
  });

  it("przeciągnięcie karty na inną zmienia przełożonego dopiero po potwierdzeniu", async () => {
    renderScreen();
    const ewaCard = await screen.findByTestId("org-card-3");
    const kamilCard = screen.getByTestId("org-card-1");
    const transfer = dataTransfer();
    fireEvent.dragStart(ewaCard, { dataTransfer: transfer });
    fireEvent.dragOver(kamilCard, { dataTransfer: transfer });
    fireEvent.drop(kamilCard, { dataTransfer: transfer });

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Ewa Makietowa: koordynator — Kamil Testowy (było: Marta Fikcyjna)");
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Zmień" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/structure/reassign", {
        user_ids: [3],
        manager_user_id: 1,
      }),
    );
  });

  it("upuszczenie przełożonego na własnego podwładnego nic nie robi (pętla)", async () => {
    renderScreen();
    const kamilCard = await screen.findByTestId("org-card-1");
    const ewaCard = screen.getByTestId("org-card-3");
    const transfer = dataTransfer();
    fireEvent.dragStart(kamilCard, { dataTransfer: transfer });
    fireEvent.drop(ewaCard, { dataTransfer: transfer });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("„Do uporządkowania” przyjmuje podpowiedź tą samą trasą", async () => {
    renderScreen();
    const panel = await screen.findByLabelText("Do uporządkowania");
    expect(within(panel).getByText(/podpowiedź: Kamil Testowy/)).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "Przyjmij: Kamil T." }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/structure/reassign", {
        user_ids: [4],
        manager_user_id: 1,
      }),
    );
  });

  it("„Lista” wraca do widoku z zaznaczaniem", async () => {
    renderScreen();
    await screen.findByTestId("org-card-1");
    fireEvent.click(screen.getByRole("button", { name: "Lista" }));
    expect(screen.getByRole("checkbox", { name: "Zaznacz: Ewa Makietowa" })).toBeInTheDocument();
    expect(screen.queryByTestId("org-card-1")).toBeNull();
  });
});
