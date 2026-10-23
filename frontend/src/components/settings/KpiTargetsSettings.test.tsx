import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  describeKpiEvent,
  parseTargetInput,
  type KpiTargetsMatrix,
} from "@/lib/api/kpiTargets";

import {
  KpiExceptions,
  KpiRoleTiles,
  KpiTargetsSettings,
} from "./KpiTargetsSettings";

const hooks = vi.hoisted(() => ({ matrix: null as unknown }));

vi.mock("@/lib/api/kpiTargets", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/kpiTargets")>();
  const idle = { isPending: false, mutateAsync: vi.fn() };
  return {
    ...actual,
    useKpiTargets: () => ({
      isError: false,
      isSuccess: true,
      data: hooks.matrix,
      refetch: vi.fn(),
    }),
    useSaveRoleDefault: () => idle,
    useSaveUserTarget: () => idle,
    useKpiTargetHistory: () => ({ isSuccess: true, data: [] }),
  };
});

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

describe("KpiRoleTiles", () => {
  it("zapisuje zmienioną wartość po opuszczeniu pola i pokazuje katalog", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<KpiRoleTiles data={MATRIX} busy={false} onSave={onSave} />);
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
    render(<KpiRoleTiles data={MATRIX} busy={false} onSave={onSave} />);
    const input = screen.getByLabelText("Weryfikacje dziś — Rekruter");
    fireEvent.blur(input);
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.blur(input);
    expect(await screen.findByRole("alert")).toHaveTextContent("liczbę całkowitą");
    expect(onSave).not.toHaveBeenCalled();
  });

  it("nieudane „Przywróć” zostawia w polu obowiązujący cel (audyt 22.10, F75)", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("403"));
    const withOverride: KpiTargetsMatrix = {
      ...MATRIX,
      roles: [
        {
          ...MATRIX.roles[0],
          targets: {
            daily_first_verifications: { catalog_default: 4, override: 12, effective: 12 },
          },
        },
      ],
    };
    render(<KpiRoleTiles data={withOverride} busy={false} onSave={onSave} />);
    fireEvent.click(screen.getByLabelText("Przywróć: Weryfikacje dziś — Rekruter"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się przywrócić celu.");
    const input = screen.getByLabelText("Weryfikacje dziś — Rekruter");
    expect(input).toHaveValue("12");
    fireEvent.blur(input);
    expect(onSave).toHaveBeenCalledTimes(1);
  });
});

const BOLEK = {
  user_id: 8,
  name: "Bolek",
  roles: ["recruiter" as const],
  targets: {
    daily_first_verifications: { effective: 4, override: null, source: "role" as const },
  },
};
const WITH_BOLEK: KpiTargetsMatrix = { ...MATRIX, users: [...MATRIX.users, BOLEK] };

describe("KpiExceptions — wyjątki zamiast tabeli wszystkich osób (20.10.2026)", () => {
  it("pokazuje tylko osoby z osobistym celem, z celem roli obok", () => {
    render(<KpiExceptions data={WITH_BOLEK} busy={false} onSave={vi.fn()} />);
    expect(screen.getByLabelText("Weryfikacje dziś — Anna")).toHaveValue("6");
    expect(screen.queryByLabelText("Weryfikacje dziś — Bolek")).not.toBeInTheDocument();
    const row = screen.getByLabelText("Weryfikacje dziś — Anna").closest("tr")!;
    expect(row).toHaveTextContent("4");
  });

  it("„Usuń” zdejmuje wyjątek — osoba wraca do celu roli", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<KpiExceptions data={MATRIX} busy={false} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Usuń wyjątek: Weryfikacje dziś — Anna" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(7, "daily_first_verifications", null),
    );
  });

  it("„Usuń” z błędem zapisu mówi o nim w wierszu", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("Network Error"));
    render(<KpiExceptions data={MATRIX} busy={false} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Usuń wyjątek: Weryfikacje dziś — Anna" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się usunąć wyjątku.");
    expect(alert.closest("tr")).toBe(
      screen.getByLabelText("Weryfikacje dziś — Anna").closest("tr"),
    );
  });

  it("„Dodaj wyjątek” zapisuje cel wybranej osoby", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<KpiExceptions data={WITH_BOLEK} busy={false} onSave={onSave} />);
    fireEvent.change(screen.getByLabelText("Osoba"), { target: { value: "8" } });
    expect(screen.getByLabelText("Cel osoby")).toHaveAttribute("placeholder", "4");
    fireEvent.change(screen.getByLabelText("Cel osoby"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj wyjątek" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(8, "daily_first_verifications", 7),
    );
  });

  it("bez osoby albo z pustym celem nic nie zapisuje i mówi dlaczego", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<KpiExceptions data={WITH_BOLEK} busy={false} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Dodaj wyjątek" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wybierz osobę");
    fireEvent.change(screen.getByLabelText("Osoba"), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj wyjątek" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("liczbę całkowitą");
    expect(onSave).not.toHaveBeenCalled();
  });

  it("bez wyjątków mówi, że wszystkich obowiązuje cel roli", () => {
    render(
      <KpiExceptions data={{ ...MATRIX, users: [BOLEK] }} busy={false} onSave={vi.fn()} />,
    );
    expect(screen.getByText(/Nikt nie ma wyjątku/)).toBeInTheDocument();
  });
});

describe("KpiTargetsSettings — nota o progu wyścigu (R4-15)", () => {
  it("mówi, że zmiana progu działa w wyścigu od następnego miesiąca", () => {
    // Progi wyścigu z nagrodą są migawką miesiąca (`monthly_race_thresholds`),
    // więc nota „działa od razu dla bieżącego miesiąca” obiecywała coś, czego
    // silnik nie robi (audyt 25.09.2026).
    hooks.matrix = MATRIX;
    render(<KpiTargetsSettings />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/od następnego miesiąca/);
    expect(note).not.toHaveTextContent(/od razu/);
    expect(note).not.toHaveTextContent(/dla bieżącego miesiąca/);
  });
});
