import { describe, expect, it } from "vitest";

import { parseSkillExpression } from "@/lib/skill-expression";
import fixture from "@/lib/__fixtures__/skill-expression-cases.json";

/**
 * Parytet parsera wyrażenia umiejętności między frontendem a backendem.
 *
 * Ten sam plik przypadków czyta `backend/tests/test_candidate_search_predicates.py`
 * (port w `app/services/candidate_search_predicates.py`). Lista i wyszukiwarka
 * muszą rozumieć wyrażenie identycznie — rozjazd jest niewidoczny z ekranu,
 * bo oba silniki odpowiadają 200 i zwracają „jakieś" wyniki.
 */
describe("skill-expression — wspólne przypadki z backendem", () => {
  it("plik przypadków nie jest pusty", () => {
    expect(fixture.cases.length).toBeGreaterThan(20);
  });

  for (const c of fixture.cases) {
    it(`parsuje ${JSON.stringify(c.expr)}`, () => {
      expect(parseSkillExpression(c.expr)).toEqual({
        must: c.must,
        anyGroups: c.anyGroups,
        none: c.none,
      });
    });
  }
});
