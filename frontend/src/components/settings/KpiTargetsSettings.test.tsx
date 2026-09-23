import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  describeKpiEvent,
  parseTargetInput,
  type KpiTargetsMatrix,
} from "@/lib/api/kpiTargets";

import { KpiRoleTable, KpiUserTable } from "./KpiTargetsSettings";

const MATRIX: KpiTargetsMatrix = {
  kpis: [
    {
      kpi_id: "daily_first_verifications",
      title: "Weryfikacje dziś",
      description: "",
      period: "day",
      period_label: "dziennie",
      race_threshold: true,
    },
  ],
  roles: [
    {
      role: "recruiter",
      label: "Rekruter",
      targets: {
        daily_first_verifications: { catalog_default: 4, override: null, effective: 4 },
      },
    },
  ],
  users: [
    {
      user_id: 7,
      name: "Anna",
      roles: ["recruiter"],
      targets: {
        daily_first_verifications: { effective: 6, override: 6, source: "user" },
      },
    },
  ],
};

describe("parseTargetInput", () => {
  it("pusty tekst znaczy „przywróć”, liczba — cel, reszta — błąd", () => {
    expect(parseTargetInput("")).toBeNull();
    expect(parseTargetInput(" 12 ")).toBe(12);
    expect(parseTargetInput("-1")).toBe("invalid");
    expect(parseTargetInput("1.5")).toBe("invalid");
    expect(parseTargetInput("100001")).toBe("invalid");
  });
});

describe("describeKpiEvent", () => {
  it("mówi, kogo dotyczy zmiana i skąd dokąd", () => {
    expect(
      describeKpiEvent({
        id: 1,
        scope: "role",
        role: "recruiter",
        role_label: "Rekruter",
        subject_user_id: null,
        subject_name: null,
        kpi_id: "weekly_cvs_sent",
        kpi_title: "Rekomendacje w tygodniu",
        action: "reset",
        from_value: 18,
        to_value: null,
        actor_name: "Admin",
        created_at: null,
      }),
    ).toBe("rola Rekruter · Rekomendacje w tygodniu: 18 → katalog");
    expect(
      describeKpiEvent({
        id: 2,
        scope: "user",
        role: null,
        role_label: null,
        subject_user_id: 7,
        subject_name: "Anna",
        kpi_id: "monthly_placements",
        kpi_title: "Placementy",
        action: "set",
        from_value: null,
        to_value: 2,
        actor_name: null,
        created_at: null,
      }),
    ).toBe("Anna · Placementy: cel z ról → 2");
  });
});

describe("KpiRoleTable", () => {
  it("zapisuje zmienioną wartość po opuszczeniu pola i pokazuje katalog", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<KpiRoleTable data={MATRIX} busy={false} onSave={onSave} />);
    expect(screen.getByText("katalog: 4")).toBeInTheDocument();
    expect(screen.getByText(/próg wyścigu/)).toBeInTheDocument();
    const input = screen.getByLabelText("Weryfikacje dziś — Rekruter");
    fireEvent.change(input, { target: { value: "5" } });
    fireEvent.blur(input);
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith("recruiter", "daily_first_verifications", 5),
    );
  });

  it("nie zapisuje bez zmiany i odrzuca tekst", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<KpiRoleTable data={MATRIX} busy={false} onSave={onSave} />);
    const input = screen.getByLabelText("Weryfikacje dziś — Rekruter");
    fireEvent.blur(input);
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.blur(input);
    expect(await screen.findByRole("alert")).toHaveTextContent("liczbę całkowitą");
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("KpiUserTable", () => {
  it("osobisty cel da się przywrócić jednym kliknięciem", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<KpiUserTable data={MATRIX} busy={false} onSave={onSave} />);
    fireEvent.click(screen.getByLabelText("Przywróć: Weryfikacje dziś — Anna"));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(7, "daily_first_verifications", null),
    );
  });
});
