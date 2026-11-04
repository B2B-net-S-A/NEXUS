import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { clientPlaybookEditHref } from "@/lib/client-playbooks";

// Runda 6 audytu (DL-02): Delivery Lead widzi profil wyłącznie klientów ze
// swojego portfela (#1843), a link „Edytuj kartę" ze strony rekrutacji i z
// Pomocy prowadził do `/clients/{id}?tab=zasady` — u cudzego klienta 403.
// Zapis karty jest org-wide, więc link prowadzi do edytora w Ustawieniach.

const SRC = path.resolve(__dirname, "../..");

describe("clientPlaybookEditHref", () => {
  it("prowadzi do edytora karty w Ustawieniach, nie do profilu klienta", () => {
    expect(clientPlaybookEditHref(42)).toBe("/settings/cv-rules?client=42&tab=playbook");
  });

  it.each([
    "components/ChampionProfileEditor.tsx",
    "components/v2/pages/HelpClientPlaybooksSection.tsx",
  ])("%s nie linkuje edycji karty do profilu klienta", (file) => {
    const source = readFileSync(path.join(SRC, file), "utf8");
    expect(source).not.toContain("?tab=zasady");
    expect(source).toContain("clientPlaybookEditHref(");
  });
});
