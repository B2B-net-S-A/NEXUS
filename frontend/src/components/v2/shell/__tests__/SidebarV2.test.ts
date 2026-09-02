import { describe, expect, it } from "vitest";

import { visibleNavSections } from "@/components/v2/shell/SidebarV2";
import type { UserRole } from "@/store/auth";

// Czysta funkcja zamiast renderu — sidebar ciągnie `next/navigation`,
// react-query, `api` i `useUiStore`, a przedmiotem testu jest wyłącznie zbiór
// pozycji, które dana rola w ogóle dostaje.
function hrefs(role: UserRole): string[] {
  return visibleNavSections(
    { role, roles: [role] },
    { contactQueueEnabled: false },
  )
    .flatMap((section) => section.items.map((item) => item.href))
    .sort();
}

describe("visibleNavSections", () => {
  // Sedno naprawy: `finance` dostawała OSOBNE, czteropozycyjne drzewo
  // (Dashboard · Finanse · Pomoc · Ustawienia), mimo że każda lista `roles`
  // w `NAV_SECTIONS` już ją wymienia — menu było jedyną warstwą odcinającą
  // rolę, którą backend przepuszcza wszędzie tam, gdzie recruitera.
  it("finance ma pełne moduły business-read i własny moduł Finanse", () => {
    const finance = hrefs("finance");
    const recruiter = hrefs("recruiter");

    expect(finance).toEqual(
      expect.arrayContaining([
        "/candidates",
        "/jobs",
        "/clients",
        "/my-clients",
        "/order-mail",
        "/my-relationships",
        "/contracts",
        "/cortex",
        "/insights",
        "/finance",
      ]),
    );
    expect(recruiter).not.toContain("/contracts");
    expect(recruiter).toContain("/cortex");
  });

  it("moduł Finanse zostaje zamknięty przed rolami operacyjnymi", () => {
    // Usunięcie rozgałęzienia nie może zadziałać w drugą stronę: `/finance`
    // ma `roles: ["admin", "finance"]`, więc recruiter go nie widzi.
    expect(hrefs("recruiter")).not.toContain("/finance");
    expect(hrefs("admin")).toContain("/finance");
  });

  it.each([
    "sourcer",
    "recruiter",
    "tac",
    "head_of_recruitment",
  ] as UserRole[])("%s nie widzi sekcji Delivery ani Finansów", (role) => {
    const visible = hrefs(role);
    expect(visible).toEqual(
      expect.arrayContaining(["/candidates", "/jobs", "/insights", "/cortex"]),
    );
    for (const route of [
      "/clients",
      "/my-clients",
      "/order-mail",
      "/my-relationships",
      "/contracts",
      "/finance",
    ]) {
      expect(visible).not.toContain(route);
    }
  });

  it("TCM widzi biznes bez Finansów, a Delivery bez akcji zapisu", () => {
    const tcm = hrefs("talent_community_manager");
    expect(tcm).toEqual(
      expect.arrayContaining([
        "/candidates",
        "/jobs",
        "/clients",
        "/my-clients",
        "/order-mail",
        "/my-relationships",
        "/contracts",
        "/insights",
        "/cortex",
      ]),
    );
    expect(tcm).not.toContain("/finance");
  });

  it("Delivery Lead widzi Delivery, ale nie globalny moduł Finansów", () => {
    const dl = hrefs("delivery_lead");
    expect(dl).toEqual(
      expect.arrayContaining([
        "/clients",
        "/my-clients",
        "/order-mail",
        "/contracts",
      ]),
    );
    expect(dl).not.toContain("/finance");
  });

  it("viewer `user` nie dostaje powierzchni kandydackich", () => {
    const viewer = hrefs("user");

    expect(viewer).not.toContain("/candidates");
    expect(viewer).not.toContain("/clients");
    expect(viewer).toContain("/jobs");
    expect(viewer).toContain("/insights");
    expect(viewer).not.toContain("/cortex");
    expect(viewer).not.toContain("/finance");
  });

  it("nie zwraca sekcji bez ani jednej widocznej pozycji", () => {
    for (const role of ["user", "finance", "recruiter"] as UserRole[]) {
      for (const section of visibleNavSections(
        { role, roles: [role] },
        { contactQueueEnabled: false },
      )) {
        expect(section.items.length).toBeGreaterThan(0);
      }
    }
  });

  it("kolejka telefonów wisi na fladze funkcji, nie tylko na roli", () => {
    const withQueue = visibleNavSections(
      { role: "recruiter", roles: ["recruiter"] },
      { contactQueueEnabled: true },
    ).flatMap((s) => s.items.map((i) => i.href));

    expect(withQueue).toContain("/candidates/contact-queue");
    const tcmWithQueue = visibleNavSections(
      {
        role: "talent_community_manager",
        roles: ["talent_community_manager"],
      },
      { contactQueueEnabled: true },
    ).flatMap((s) => s.items.map((i) => i.href));
    expect(tcmWithQueue).toContain("/candidates/contact-queue");
    expect(hrefs("recruiter")).not.toContain("/candidates/contact-queue");
  });
});
