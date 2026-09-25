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
    urls.push(api.getUri(config));
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
  it("pyta listę kandydatów powtarzanymi parametrami, z wierszami i wykluczeniami", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <SearchRequirementsEditor
          rows={[["Java"], ["Kafka", "RabbitMQ"]]}
          exclude={["junior"]}
          onChange={() => undefined}
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
});
