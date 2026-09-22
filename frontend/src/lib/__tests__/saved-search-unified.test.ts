import { describe, expect, it } from "vitest";

import fixture from "@/lib/__fixtures__/saved-search-unified-cases.json";
import {
  buildUnifiedPayload,
  listEngineGaps,
  readSavedSearch,
  unifiedToListParams,
  unifiedToSearchBody,
  withRequestFlags,
  withSemanticsMarker,
} from "@/lib/saved-search-unified";

/**
 * Parytet adaptera zapisanych wyszukiwań z backendem
 * (`backend/app/services/saved_search_payload.py`). Ten sam plik przypadków
 * czyta `backend/tests/test_saved_search_payload.py` — skaner alertów i UI
 * muszą czytać stare zapisy identycznie, inaczej alert liczy inny zbiór niż
 * ten, który rekruter widzi po kliknięciu powiadomienia.
 */
type Case = (typeof fixture.cases)[number] & {
  list_params?: unknown;
  search_body?: unknown;
  list_engine_gaps?: string[];
  payload?: Record<string, unknown>;
};

describe("saved-search-unified — wspólne przypadki z backendem", () => {
  it("plik przypadków obejmuje oba formaty legacy", () => {
    const origins = new Set(fixture.cases.map((c) => c.origin));
    expect(origins.has("candidates_list")).toBe(true);
    expect(origins.has("search_request")).toBe(true);
  });

  for (const c of fixture.cases as Case[]) {
    it(c.name, () => {
      const read = readSavedSearch(c.filters);
      expect(read.format).toBe(c.format);
      expect(read.origin).toBe(c.origin);
      expect(read.request).toEqual(c.request);
      if (!read.request || !read.origin) return;

      expect(unifiedToListParams(read.request)).toEqual(c.list_params);
      expect(unifiedToSearchBody(read.request)).toEqual(c.search_body);
      expect(listEngineGaps(read.request)).toEqual(c.list_engine_gaps);

      const payload = buildUnifiedPayload(
        c.filters as Record<string, unknown>,
        read.origin,
        read.request,
      );
      expect(payload).toEqual(c.payload);
      // v3 czyta się z powrotem do tego samego żądania
      const again = readSavedSearch(payload);
      expect(again).toEqual({
        format: "unified",
        origin: read.origin,
        request: read.request,
      });
    });
  }

  it("flagi neutralizujące trafiają do querystringu listy (CAND-06)", () => {
    const req = { hide_unknown: true, location_scope: "location_only" } as never;
    expect(withRequestFlags("loc=gdansk", req)).toBe(
      "loc=gdansk&hu=1&ls=location_only",
    );
    expect(withRequestFlags("loc=gdansk&hu=1", req)).toBe(
      "loc=gdansk&hu=1&ls=location_only",
    );
    expect(withRequestFlags("q=python", {} as never)).toBe("q=python");
  });

  it("znacznik semantyki dopisuje się raz", () => {
    expect(withSemanticsMarker("q=python")).toBe("q=python&sv=2");
    expect(withSemanticsMarker("q=python&sv=2")).toBe("q=python&sv=2");
  });
});
