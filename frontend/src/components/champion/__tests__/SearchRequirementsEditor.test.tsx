import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { api } from "@/lib/api";
import { SearchRequirementsEditor } from "@/components/champion/SearchRequirementsEditor";

/**
 * Licznik „~N osób w bazie” na PRAWDZIWEJ instancji `api` — widać adres,
 * który naprawdę poszedłby do serwera. Z formą `status[]=` / `q_any_group[]=`
 * FastAPI nie widzi filtrów i liczba obejmuje całą bazę (przegląd 25.09.2026).
 */

let urls: string[] = [];
let previousAdapter: typeof api.defaults.adapter;

beforeEach(() => {
  urls = [];
  previousAdapter = api.defaults.adapter;
  api.defaults.adapter = async (config) => {
    const url = api.getUri(config);
    if (url.includes("/keywords/classify")) {
      const q = new URL(url, "http://x").searchParams.get("q") ?? "";
      return {
        data: { skills: [], as_requirements: ["Java", "Kafka RabbitMQ"].includes(q) },
        status: 200,
        statusText: "OK",
        headers: {},
        config,
      };
    }
    urls.push(url);
    return {
      data: { items: [], total: 42 },
      status: 200,
      statusText: "OK",
      headers: {},
      config,
    };
  };
});

afterEach(() => {
  api.defaults.adapter = previousAdapter;
});

describe("SearchRequirementsEditor — liczba osób w bazie", () => {
  it("pyta listę kandydatów powtarzanymi parametrami: obowiązkowe wiersze krytycznych i wykluczenia", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <SearchRequirementsEditor
          rows={[["Java"], ["Kafka", "RabbitMQ"]]}
          exclude={["junior"]}
          onChange={() => undefined}
          critical={{
            stored: ["Java", "Kafka lub RabbitMQ"],
            decided: true,
            effective: ["Java", "Kafka lub RabbitMQ"],
            source: "dl",
            suggested: [],
            search_rows: [["Java"], ["Kafka", "RabbitMQ"]],
          }}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("~42 osoby w bazie")).toBeInTheDocument();
    const url = decodeURIComponent(urls.at(-1) ?? "");
    expect(url).toContain("/api/candidates?");
    expect(url).not.toContain("[]");
    expect(url).toContain("status=active&status=passive");
    expect(url).toContain("q_any_group=Java&q_any_group=Kafka|RabbitMQ");
    expect(url).toContain("q_none=junior");
    expect(url).toContain("page_size=1");
  });

  it("obowiązkowe są tylko umiejętności krytyczne — ta sama reguła co „Szukaj w bazie” (jobSearchPlan)", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <SearchRequirementsEditor
          rows={[["Java"], ["Kafka"], ["bankowość"]]}
          exclude={[]}
          onChange={() => undefined}
          critical={{
            stored: ["Java"],
            decided: true,
            effective: ["Java"],
            source: "dl",
            suggested: [],
            search_rows: [["Java", "J2EE"]],
          }}
        />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText(
        "~42 osoby ma umiejętności krytyczne; 2 wiersze tylko podnoszą w kolejności",
      ),
    ).toBeInTheDocument();
    const url = decodeURIComponent(urls.at(-1) ?? "");
    // Wiersz krytycznej dostaje warianty nazwy z serwera; „Kafka” — choć to
    // technologia — nie jest krytyczna, więc nie wycina.
    expect(url).toContain("q_any_group=Java|J2EE");
    expect(url).not.toContain("Kafka");
    expect(url).not.toContain("bankowość");
  });

  it("bez krytycznych nic nie jest obowiązkowe — cała baza", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <SearchRequirementsEditor
          rows={[["Java"]]}
          exclude={[]}
          onChange={() => undefined}
          critical={{
            stored: [],
            decided: true,
            effective: [],
            source: "none",
            suggested: [],
            search_rows: [],
          }}
        />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("Cała baza (~42 osoby); 1 wiersz tylko podnosi w kolejności"),
    ).toBeInTheDocument();
    expect(decodeURIComponent(urls.at(-1) ?? "")).not.toContain("q_any_group");
  });
});
