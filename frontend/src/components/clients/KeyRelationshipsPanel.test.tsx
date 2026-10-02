import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";
import {
  permissionSnapshot,
  sectionSnapshot,
} from "@/test/fixtures/permission-snapshot";

import { KeyRelationshipsPanel } from "./KeyRelationshipsPanel";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get },
}));

vi.mock("@/components/KeyRelationshipDialog", () => ({
  KeyRelationshipDialog: () => <div>Edytor relacji</div>,
}));

function signIn(
  role: string,
  options: { granted?: Permission[]; realUser?: unknown } = {},
) {
  useAuthStore.setState({
    user: {
      id: 5,
      email: `${role}@example.com`,
      name: role,
      role,
      roles: [role],
      // Bez `granted` profil liczy się z domyślnych uprawnień roli.
      ...(options.granted
        ? {
            effective_action_access: permissionSnapshot(...options.granted),
            effective_section_access: sectionSnapshot(options.granted),
          }
        : {}),
    },
    realUser: options.realUser ?? null,
    hydrated: true,
  } as never);
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <KeyRelationshipsPanel />
    </QueryClientProvider>,
  );
}

const ORG_HEADING = { name: "Kluczowe relacje w organizacji" };
const OWN_HEADING = { name: "Moje kluczowe relacje" };
const update = () => screen.queryByRole("button", { name: "Aktualizuj" });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({
    data: [
      {
        contact_id: 9,
        name: "Anna Kowalska",
        position: "Hiring Manager",
        email: "anna@example.com",
        phone: "+48 500 000 000",
        client_id: 3,
        client_name: "Klient Testowy",
        is_decision_maker: true,
        relationship_strength: "champion",
        relationship_notes: "Kluczowa relacja",
        last_personal_touchpoint_at: null,
        last_contacted_at: null,
        days_since_personal_touchpoint: null,
      },
    ],
  });
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("KeyRelationshipsPanel — czyje relacje widać", () => {
  it.each(["finance", "talent_community_manager", "admin"])(
    "%s czyta relacje całej organizacji — nagłówek mówi to wprost",
    async (role) => {
      signIn(role);
      renderPage();

      expect(await screen.findByRole("heading", ORG_HEADING)).toBeInTheDocument();
      expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
      expect(screen.getByText("Klient Testowy")).toBeInTheDocument();
    },
  );

  it("konto z rolą Delivery Leada widzi własne relacje", async () => {
    signIn("delivery_lead");
    renderPage();

    expect(await screen.findByRole("heading", OWN_HEADING)).toBeInTheDocument();
    expect(
      screen.getByText(/Osoby u klientów, z którymi masz zbudowaną relację/),
    ).toBeInTheDocument();
  });

  it("rekruter z nadanym podglądem Delivery czyta relacje organizacji, nie „moje”", async () => {
    signIn("recruiter", { granted: ["delivery_view"] });
    renderPage();

    expect(await screen.findByRole("heading", ORG_HEADING)).toBeInTheDocument();
  });

  it("pusta lista organizacji i pusta lista własna mówią co innego", async () => {
    mocks.get.mockResolvedValue({ data: [] });
    signIn("finance");
    const first = renderPage();
    expect(
      await screen.findByText("W organizacji nie ma jeszcze oznaczonych kluczowych relacji."),
    ).toBeInTheDocument();
    first.unmount();

    signIn("delivery_lead");
    renderPage();
    expect(
      await screen.findByText(/Nie masz jeszcze oznaczonych żadnych kluczowych relacji/),
    ).toBeInTheDocument();
  });
});

describe("KeyRelationshipsPanel — „Aktualizuj” za edycją klientów albo własną relacją", () => {
  it("Finanse i Talent Community Manager (podgląd bez edycji klientów) nie aktualizują", async () => {
    signIn("finance");
    const first = renderPage();
    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    expect(update()).not.toBeInTheDocument();
    first.unmount();

    signIn("talent_community_manager");
    renderPage();
    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    expect(update()).not.toBeInTheDocument();
    expect(screen.queryByText("Edytor relacji")).not.toBeInTheDocument();
  });

  it("administrator (ma edycję klientów) aktualizuje relacje organizacji", async () => {
    signIn("admin");
    renderPage();

    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    fireEvent.click(update() as HTMLElement);
    expect(screen.getByText("Edytor relacji")).toBeInTheDocument();
  });

  it("rekruter z nadaną edycją klientów aktualizuje relacje", async () => {
    signIn("recruiter", { granted: ["clients_edit"] });
    renderPage();

    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    expect(update()).toBeInTheDocument();
  });

  it("Delivery Lead aktualizuje własną relację także z wyłączoną edycją klientów", async () => {
    // Lista „moich” relacji zawiera wyłącznie kontakty, których konto jest
    // właścicielem — pola relacji właściciel zmienia bez edycji klientów.
    signIn("delivery_lead", { granted: ["delivery_view"] });
    renderPage();

    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    expect(update()).toBeInTheDocument();
  });

  it("w podglądzie jako inny użytkownik nie ma „Aktualizuj”", async () => {
    signIn("delivery_lead", { realUser: { id: 1, role: "admin", roles: ["admin"] } });
    renderPage();

    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    expect(update()).not.toBeInTheDocument();
  });
});

describe("KeyRelationshipsPanel — odmowa", () => {
  it("403 nazywa brakujące uprawnienie zamiast „Czy jesteś zalogowany?” (UAT A-B04)", async () => {
    signIn("recruiter");
    mocks.get.mockRejectedValue({ response: { status: 403 } });
    renderPage();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(
      screen.getByText(/wymagają uprawnienia „Klienci, kontrakty i zamówienia: podgląd”/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Twojej roli/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Czy jesteś zalogowany/)).not.toBeInTheDocument();
  });
});
