import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { JobRecruitmentPath } from "@/components/v2/jobs/JobRecruitmentPath";
import type { NearestStep, PathStep } from "@/lib/job-recruitment-path";

const STEPS: PathStep[] = [
  { key: "order", label: "Zlecenie", state: "missing", detail: "brakuje 5 — uzupełnij" },
  { key: "candidates", label: "Kandydaci", state: "active", detail: "15 w procesie · 17 propozycji" },
  { key: "cv", label: "CV do klienta", state: "active", detail: "1 w QC · 0 wysłanych" },
  { key: "interviews", label: "Rozmowy", state: "todo", detail: "brak zaplanowanych" },
  { key: "contract", label: "Umowa", state: "done", detail: "obsada 1 / 1" },
];

const NEAREST: NearestStep = {
  rule: "order",
  sentence: "Uzupełnij zlecenie (brakuje 5)",
  cta: "Otwórz zlecenie",
  action: { kind: "order" },
};

describe("JobRecruitmentPath", () => {
  it("pięć kroków w kolejności, stan w nazwie dostępnej, klik zgłasza krok", async () => {
    const onStepClick = vi.fn();
    render(
      <JobRecruitmentPath steps={STEPS} nearest={null} onStepClick={onStepClick} onNearestClick={vi.fn()} />,
    );
    const list = screen.getByRole("list", { name: "Ścieżka rekrutacji" });
    expect(list.querySelectorAll("li")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Zlecenie: brak — brakuje 5 — uzupełnij" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Umowa: gotowe/ })).toHaveAttribute("data-state", "done");
    expect(screen.getByRole("button", { name: /^Rozmowy: przed nami/ })).toBeTruthy();
    await userEvent.click(screen.getByTestId("path-step-cv"));
    expect(onStepClick).toHaveBeenCalledWith("cv");
    // Bez reguły — brak pola „Najbliższy krok" (nic zamiast zdania o niczym).
    expect(screen.queryByTestId("job-nearest-step")).toBeNull();
  });

  it("„Najbliższy krok”: jedno zdanie i przycisk", async () => {
    const onNearestClick = vi.fn();
    render(
      <JobRecruitmentPath steps={STEPS} nearest={NEAREST} onStepClick={vi.fn()} onNearestClick={onNearestClick} />,
    );
    const box = screen.getByTestId("job-nearest-step");
    expect(box).toHaveTextContent("Najbliższy krok");
    expect(box).toHaveTextContent("Uzupełnij zlecenie (brakuje 5)");
    await userEvent.click(screen.getByRole("button", { name: "Otwórz zlecenie" }));
    expect(onNearestClick).toHaveBeenCalledWith(NEAREST);
  });
});
