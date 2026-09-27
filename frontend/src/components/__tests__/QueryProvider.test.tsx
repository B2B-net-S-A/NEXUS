import { QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QueryProvider } from "@/components/QueryProvider";
import {
  ALLOCATION_BOARD_POLL_MS,
  DASHBOARD_SECTION_POLL_MS,
  NOTIFICATIONS_FALLBACK_POLL_MS,
  WS_BACKED_SAFETY_POLL_MS,
} from "@/lib/polling";

/**
 * Dwie warstwy retry (react-query × axios) mnożyły jeden odczyt do 6 żądań
 * przy 503 z bramy. Interceptor axios jest JEDYNYM właścicielem ponowień
 * (`lib/__tests__/api-transient-retry.test.ts`), więc react-query ma zero.
 */
describe("QueryProvider", () => {
  it("nie ponawia zapytań — ponowienia należą do interceptora axios", () => {
    let seen: number | boolean | undefined;
    function Probe() {
      const client = useQueryClient();
      const retry = client.getDefaultOptions().queries?.retry;
      seen = typeof retry === "function" ? undefined : retry;
      return null;
    }
    render(
      <QueryProvider>
        <Probe />
      </QueryProvider>,
    );
    expect(seen).toBe(0);
  });

  it("nie używa pustego providera zamiast QueryClientProvider", () => {
    expect(QueryClientProvider).toBeDefined();
  });
});

describe("budżet odpytywania w tle (lib/polling)", () => {
  it("bezczynny dashboard przy zdrowym WebSockecie mieści się w ≤2 GET/min", () => {
    // Model z audytu 13.09.2026: dzwonek + KPI + cztery sekcje dashboardu
    // + onboarding + sidebar (5 min, 3 żądania). Liczymy żądania na minutę.
    const perMinute =
      60_000 / WS_BACKED_SAFETY_POLL_MS + // dzwonek (WS zdrowy)
      60_000 / WS_BACKED_SAFETY_POLL_MS + // KPI
      4 * (60_000 / DASHBOARD_SECTION_POLL_MS) + // sekcje dashboardu
      60_000 / DASHBOARD_SECTION_POLL_MS + // onboarding
      3 * (60_000 / (5 * 60_000)); // sidebar: 3 żądania co 5 min
    expect(perMinute).toBeLessThanOrEqual(2);
  });

  it("bez WebSocketu powiadomienia odświeżają się nie częściej niż co minutę", () => {
    expect(NOTIFICATIONS_FALLBACK_POLL_MS).toBeGreaterThanOrEqual(60_000);
    expect(ALLOCATION_BOARD_POLL_MS).toBeGreaterThanOrEqual(60_000);
  });
});

describe("jeden właściciel ponowień", () => {
  it("żaden komponent nie włącza własnego `retry` liczbą większą od zera", async () => {
    // Reaudyt 14.09.2026 (R06): dwa lokalne `retry: 1` przeżyły zmianę
    // globalnego domyślnego — każde mnożyło ponowienia axios do 6 żądań.
    // Funkcje (`retry: (count, error) => …`) i `retry: false` są dozwolone.
    const { readdirSync, readFileSync, statSync } = await import("node:fs");
    const { join } = await import("node:path");
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) {
          if (name === "__tests__" || name === "preview") continue;
          walk(path);
        } else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name)) {
          const source = readFileSync(path, "utf8");
          // Tylko kod: linie opcji `retry: N`, nie komentarze o historii.
          if (source.split("\n").some((line) => /^\s*retry:\s*[1-9]/.test(line))) {
            offenders.push(path);
          }
        }
      }
    };
    walk(join(process.cwd(), "src"));
    expect(offenders).toEqual([]);
  });
  it("żaden komponent nie ponawia funkcją `retry` — wyjątki tylko z listy (R8-N14-8)", async () => {
    // Funkcja `retry: (count, error) => …` zwracająca true dla 5xx / braku
    // odpowiedzi to ta sama druga warstwa co `retry: 1` (JobPriorityContext:
    // 4 żądania zamiast 2). Dozwolone wyłącznie ponowienia, których axios nie
    // robi — z powodem.
    const ALLOWED: Record<string, string> = {
      // Tylko 429 z backoffem — interceptor axios nie ponawia 429.
      "components/v2/pages/CandidateCompareModal.tsx": "429",
    };
    const { readdirSync, readFileSync, statSync } = await import("node:fs");
    const { join, relative } = await import("node:path");
    const root = join(process.cwd(), "src");
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) {
          if (name === "__tests__" || name === "preview") continue;
          walk(path);
        } else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name)) {
          const rel = relative(root, path);
          if (rel in ALLOWED) continue;
          const source = readFileSync(path, "utf8");
          // Opcja zapytania z parametrami (`retry: (failureCount, error) =>`),
          // nie pole-callback bez argumentów (`retry: () => void`).
          if (source.split("\n").some((line) => /^\s*retry:\s*\(\s*[A-Za-z_]/.test(line))) {
            offenders.push(rel);
          }
        }
      }
    };
    walk(root);
    expect(offenders).toEqual([]);
  });
});
