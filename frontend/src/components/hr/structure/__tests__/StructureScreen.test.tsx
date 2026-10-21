/**
 * Schemat struktury wg makiety 19.10.2026 (od 22.10.2026 widok „Schemat”
 * katalogu): schemat kart, przeciągnięcie karty = zmiana przełożonego (po
 * potwierdzeniu), „Do uporządkowania” jako sekcja „Struktura” w „Porządkach”
 * (`StructureTodoSection`). Dane fikcyjne.
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
import { StructureTodoSection } from "../StructureTodo";

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

  it("„Do uporządkowania” (sekcja „Porządków”) przyjmuje podpowiedź tą samą trasą", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <StructureTodoSection data={DATA} />
      </QueryClientProvider>,
    );
    const list = screen.getByRole("list", { name: "Do uporządkowania w strukturze" });
    expect(within(list).getByText(/podpowiedź: Kamil Testowy/)).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: "Przyjmij: Kamil T." }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/structure/reassign", {
        user_ids: [4],
        manager_user_id: 1,
      }),
    );
  });

  it("schemat bez własnego przełącznika i bez panelu bocznego; korzeń mówi o koordynatorze spoza pionu", async () => {
    const outside = person(5, "Piotr Finansowy", { division: "back_office", reports: 1 });
    const zofia = person(6, "Zofia Wzorcowa", {
      manager_user_id: 5,
      manager_name: "Piotr Finansowy",
      manager_state: "ok",
    });
    mocks.get.mockImplementation(async () => ({
      data: { ...DATA, people: [...DATA.people, outside, zofia], total: 6 },
    }));
    renderScreen();
    expect(await screen.findByTestId("org-card-6")).toHaveTextContent(
      "koordynator: Piotr Finansowy (Back office)",
    );
    expect(screen.queryByRole("button", { name: "Lista" })).toBeNull();
    expect(screen.queryByLabelText("Do uporządkowania")).toBeNull();
    expect(screen.getByRole("button", { name: "Headowie pionów" })).toBeInTheDocument();
  });

  it("duży zespół bez własnych ludzi stoi w kolumnie pod przełożonym, karty dalej przyjmują przeciąganie", async () => {
    // Prod 20.10.2026: kilkadziesiąt osób pod jedną — rząd miał 5384 px szerokości.
    const team = Array.from({ length: 12 }, (_, i) =>
      person(50 + i, `Członek ${String(i).padStart(2, "0")}`, {
        division: null,
        manager_user_id: 40,
        manager_name: "Lider Zespołu",
        manager_state: "ok",
      }),
    );
    const lead = person(40, "Lider Zespołu", { division: null, reports: 12 });
    mocks.get.mockImplementation(async () => ({
      data: { ...DATA, people: [...DATA.people, lead, ...team], total: 17 },
    }));
    renderScreen();
    const column = await screen.findByRole("list", { name: "Pod osobą Lider Zespołu: 12 osób" });
    expect(within(column).getAllByTestId(/^org-card-/)).toHaveLength(12);
    const transfer = dataTransfer();
    fireEvent.dragStart(screen.getByTestId("org-card-51"), { dataTransfer: transfer });
    fireEvent.dragOver(screen.getByTestId("org-card-1"), { dataTransfer: transfer });
    fireEvent.drop(screen.getByTestId("org-card-1"), { dataTransfer: transfer });
    expect(await screen.findByRole("dialog")).toHaveTextContent("Członek 01");
  });
});
