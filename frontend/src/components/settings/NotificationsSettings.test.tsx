import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  params: new URLSearchParams(),
  goToMine: null as null | (() => void),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mocks.params,
}));
vi.mock("@/components/settings/NotificationPreferencesPanel", () => ({
  NotificationPreferencesPanel: () => <div>ekran: moje</div>,
}));
vi.mock("@/components/settings/NotificationRoleMatrix", () => ({
  NotificationRoleMatrix: () => <div>ekran: kto co dostaje</div>,
}));
vi.mock("@/components/settings/NotificationDeliverySettings", () => ({
  default: ({ onGoToMine }: { onGoToMine?: () => void }) => (
    <div>
      ekran: maile
      <button type="button" onClick={onGoToMine}>
        tylko sobie
      </button>
    </div>
  ),
}));

import {
  NotificationsSettings,
  availableNotificationTabs,
} from "@/components/settings/NotificationsSettings";
import { useAuthStore, type User } from "@/store/auth";

function account(role: User["role"], access: User["effective_section_access"]): User {
  return {
    id: 1,
    email: "konto1@example.com",
    name: "Aniela Administrująca",
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    effective_section_access: access,
  };
}

const ADMIN = account("admin", { system_admin: "write", pipeline: "write" });
const RECRUITER = account("recruiter", { pipeline: "write" });

function renderScreen(
  user: User,
  defaultTab: "moje" | "role" | "maile" | "etapy",
  query = "",
) {
  mocks.params = new URLSearchParams(query);
  useAuthStore.setState({ user, hydrated: true });
  render(<NotificationsSettings defaultTab={defaultTab} />);
  return userEvent.setup();
}

function tabNames(): (string | null)[] {
  return screen.queryAllByRole("tab").map((tab) => tab.textContent);
}

beforeEach(() => {
  window.history.replaceState(null, "", "/settings?item=notifications");
});

describe("NotificationsSettings — zakładki według uprawnień", () => {
  it("administrator w Systemie widzi trzy zakładki — bez „Moje” (są w „Moje konto”, 21.10.2026)", () => {
    renderScreen(ADMIN, "role");
    expect(tabNames()).toEqual(["Kto co dostaje", "Maile", "Reguły etapów"]);
    expect(screen.getByRole("tab", { name: "Kto co dostaje" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("ekran: kto co dostaje")).toBeInTheDocument();
  });

  it("rekruter (bez zakładek firmowych) dostaje odesłanie do „Moje konto” — także z cudzym `?sub=`", () => {
    renderScreen(RECRUITER, "role", "sub=maile");
    expect(tabNames()).toEqual([]);
    expect(screen.queryByText("ekran: moje")).toBeNull();
    expect(screen.getByRole("link", { name: "Moje konto" })).toHaveAttribute(
      "href",
      "/settings?item=my-notifications",
    );
    expect(screen.queryByText("ekran: maile")).toBeNull();
    expect(screen.queryByText("ekran: kto co dostaje")).toBeNull();
  });

  it("Delivery Lead z zapisem w rekrutacjach dostaje „Moje” i „Reguły etapów”", () => {
    renderScreen(account("delivery_lead", { pipeline: "write" }), "moje", "sub=etapy");
    expect(tabNames()).toEqual(["Moje", "Reguły etapów"]);
    expect(screen.getByRole("link", { name: "Otwórz Procesy rekrutacyjne" })).toHaveAttribute(
      "href",
      "/settings?item=stages",
    );
  });

  it("lustro bramek: bez sekcji administracji admin nie ma zakładek firmowych", () => {
    expect(availableNotificationTabs(account("admin", { pipeline: "write" }))).toEqual([
      "moje",
      "etapy",
    ]);
    expect(availableNotificationTabs(account("delivery_lead", { pipeline: "read" }))).toEqual([
      "moje",
    ]);
    expect(availableNotificationTabs(null)).toEqual(["moje"]);
  });

  it("System › Powiadomienia firmy bez zakładki „Moje” (21.10.2026 — są w „Moje konto”)", () => {
    expect(
      availableNotificationTabs(account("admin", { pipeline: "write", system_admin: "write" }), {
        includeMine: false,
      }),
    ).toEqual(["role", "maile", "etapy"]);
    expect(availableNotificationTabs(null, { includeMine: false })).toEqual([]);
  });

  it("`?sub=` wybiera zakładkę, a nieznana wartość wraca do domyślnej", () => {
    renderScreen(ADMIN, "role", "sub=maile");
    expect(screen.getByText("ekran: maile")).toBeInTheDocument();
  });

  it("nieznane `?sub=` pokazuje zakładkę domyślną pozycji", () => {
    renderScreen(ADMIN, "moje", "sub=cos-innego");
    expect(screen.getByText("ekran: moje")).toBeInTheDocument();
  });

  it("kliknięcie zakładki zmienia ekran i zapisuje ją w adresie; domyślna nie zostawia `?sub=`", async () => {
    const user = renderScreen(ADMIN, "role");
    await user.click(screen.getByRole("tab", { name: "Maile" }));
    expect(screen.getByText("ekran: maile")).toBeInTheDocument();
    expect(window.location.search).toBe("?item=notifications&sub=maile");

    await user.click(screen.getByRole("tab", { name: "Kto co dostaje" }));
    expect(window.location.search).toBe("?item=notifications");
  });

  it("„tylko sobie” z zakładki Maile prowadzi do „Moje” tylko tam, gdzie jest ta zakładka", async () => {
    const user = renderScreen(ADMIN, "moje", "sub=maile");
    await user.click(screen.getByRole("button", { name: "tylko sobie" }));
    expect(screen.getByText("ekran: moje")).toBeInTheDocument();
    // „Moje” jest tu zakładką domyślną, więc adres jej nie niesie.
    expect(window.location.search).toBe("?item=notifications");
  });
});
