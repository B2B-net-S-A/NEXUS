import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * „Propozycje z bazy" (dawniej ranking C2 na stronie rekrutacji) dodają do
 * pipeline'u przez trasę bulk, którą dzielą z ręczną wyszukiwarką, sekcją
 * historyczną i szybkim dodawaniem. Backend przypina wynik `add_to_pipeline`
 * do rankingu WYŁĄCZNIE przez przegląd zadeklarowany przez wołającego — więc
 * każde dodanie z tego ekranu musi nieść pochodzenie wiersza (`source`)
 * i bieżący przegląd (`run_id`). Zgubione `run_id` niczego nie psuje na
 * ekranie; po cichu zamienia każde dodanie w nieprzypisane.
 *
 * Czyta ŹRÓDŁO: własność dotyczy tego, jakie argumenty niosą wywołania, a nie
 * renderowania. Zachowanie (które źródło dostaje który wiersz) pilnuje
 * `useJobProposals.test.tsx`.
 */
const SRC = path.resolve(process.cwd(), "src");
const read = (file: string) => fs.readFileSync(path.join(SRC, file), "utf-8");

describe("dodania z propozycji deklarują swoje pochodzenie", () => {
  const hook = read("components/v2/recruitment/useJobProposals.ts");

  it("każde dodanie bulk w segmencie propozycji idzie przez grupowanie po pochodzeniu", () => {
    const calls = [...hook.matchAll(/proposalsBulkApi\.add\(([\s\S]*?)\)\s*[;)]/g)];
    expect(calls.length).toBe(1);
    expect(hook).toContain("for (const group of groupAddsByOrigin(picked, autoRunId))");
    expect(hook).toContain("if (group.source) body.source = group.source;");
    expect(hook).toContain("if (group.runId) body.run_id = group.runId;");
  });

  it("wiersz z żywego przeglądu deklaruje `full_search` i run tego przeglądu", () => {
    expect(hook).toMatch(/origins\.includes\("run"\) && row\.runId\s*\?\s*\{ source: "full_search", runId: row\.runId \}/);
  });

  it("strona rekrutacji nie dodaje do pipeline'u z pominięciem tego hooka", () => {
    const page = read("app/jobs/[id]/page.tsx");
    expect(page).not.toContain("proposalsBulkApi.add(");
  });
});
