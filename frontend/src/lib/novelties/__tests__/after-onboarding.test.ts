// Dokąd po „Zakończ onboarding” (22.11.2026): nowa osoba z Poligonem
// wymaganym lądowała na pulpicie, bo pulpit jest wolny od blokady Startu,
// i Poligon widziała dopiero po kliknięciu innego ekranu.

import { describe, expect, it } from "vitest";

import { afterOnboardingPath, type StartStatus } from "@/lib/novelties/logic";

function status(overrides: Partial<StartStatus> = {}): StartStatus {
  return {
    enforced: true,
    gate_on: true,
    done: 0,
    total: 3,
    items: [],
    redirect: "/poligon",
    ...overrides,
  };
}

describe("afterOnboardingPath", () => {
  it("prowadzi na Poligon, gdy blokada zatrzymuje nową osobę na Poligonie", () => {
    expect(afterOnboardingPath(status())).toBe("/poligon");
  });

  it("zostawia pulpit, gdy blokuje sam Start — pulpit jest dla Startu wolny", () => {
    expect(afterOnboardingPath(status({ redirect: "/start" }))).toBe("/");
    expect(afterOnboardingPath(status({ redirect: undefined }))).toBe("/");
  });

  it("zostawia pulpit, gdy nic nie blokuje albo stanu nie ma (awaria = brak blokady)", () => {
    expect(afterOnboardingPath(status({ enforced: false }))).toBe("/");
    expect(afterOnboardingPath(null)).toBe("/");
  });
});
