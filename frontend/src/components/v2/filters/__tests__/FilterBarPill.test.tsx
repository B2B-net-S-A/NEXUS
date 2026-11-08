import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FilterPill } from "@/components/v2/filters/FilterBarPill";

describe("FilterPill", () => {
  // `sr-only` to `position: absolute`. Pasek filtrów na telefonie przewija się
  // w poziomie (`overflow-x-auto`), a element absolutny bez pozycjonowanego
  // przodka liczy się od strony: wychodził z paska i dawał stronie 299 px
  // poziomego scrolla przy 360 px (E2E `responsive-preview`, 08.11.2026).
  it.each(["auto", "compact"] as const)(
    "pełna etykieta sr-only zostaje w pigułce (density=%s)",
    (density) => {
      render(
        <FilterPill label="Lata z technologią" shortLabel="Lata" icon={<i />} count={0} density={density}>
          <div />
        </FilterPill>,
      );

      const fullLabel = screen.getByText("Lata z technologią");
      expect(fullLabel.className).toContain("sr-only");
      expect(fullLabel.closest(".relative")).not.toBeNull();
    },
  );
});
