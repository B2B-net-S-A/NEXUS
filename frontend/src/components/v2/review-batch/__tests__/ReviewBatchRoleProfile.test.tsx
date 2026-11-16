/** Profil „Kogo szukamy” nad kartą w porcji (decyzja Artura 16.11.2026). */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  excludedLine,
  RoleProfileBlock,
  wantedLine,
} from "@/components/v2/review-batch/ReviewBatchRoleProfile";
import type { ReviewBatchRoleProfile } from "@/lib/api/reviewBatch";

const api = vi.hoisted(() => ({ put: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: { put: api.put, get: vi.fn() } }));
const toast = vi.hoisted(() => ({ showError: vi.fn(), showSuccess: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const profile: ReviewBatchRoleProfile = {
  job_id: 42,
  role: "tester",
  specialty: "automatyzacja",
  technology: "Java",
  level: "lider",
  saved: false,
  excluded: [
    { label: "Data Engineer", count: 3, source: "rejections" },
    { label: "Scrum Master", count: 0, source: "manual" },
  ],
  learning: [{ label: "DBA", count: 1, dismissed: false }],
  exclude_min: 3,
};

function renderBlock(compact: boolean) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <RoleProfileBlock profile={profile} compact={compact} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.put.mockReset();
  toast.showError.mockReset();
  toast.showSuccess.mockReset();
});

describe("profil „Kogo szukamy”", () => {
  it("składa linie z profilu", () => {
    expect(wantedLine(profile)).toBe("tester · automatyzacja · Java · lider");
    expect(wantedLine({ ...profile, role: null, specialty: null, technology: null, level: "dowolny" })).toBe(
      "rola nieustalona",
    );
    expect(excludedLine(profile)).toBe("Data Engineer (3× z odrzuceń), Scrum Master (ręcznie)");
    expect(excludedLine({ ...profile, excluded: [] })).toBeNull();
  });

  it("po pierwszej karcie rekrutacji to jedna linia", () => {
    renderBlock(true);
    const block = screen.getByTestId("review-role-profile");
    expect(block.querySelectorAll("p")).toHaveLength(1);
    expect(block).toHaveTextContent("Kogo szukamy: tester · automatyzacja · Java · lider · Nie proponujemy:");
  });

  it("„Popraw” zapisuje profil i listę, bez zdjętej pozycji", async () => {
    const user = userEvent.setup();
    api.put.mockResolvedValue({ data: { ...profile, saved: true } });
    renderBlock(false);
    await user.click(screen.getByTestId("review-role-profile-edit"));
    await user.click(screen.getByRole("button", { name: "Usuń Data Engineer" }));
    await user.type(screen.getByLabelText("Dodaj do „Nie proponujemy”"), "Tester manualny{Enter}");
    await user.click(screen.getByRole("radio", { name: "wykonawca" }));
    await user.click(screen.getByTestId("review-role-profile-save"));
    await vi.waitFor(() => expect(api.put).toHaveBeenCalled());
    expect(api.put).toHaveBeenCalledWith("/api/review-batch/jobs/42/profile", {
      role: "tester",
      specialty: "automatyzacja",
      technology: "Java",
      level: "wykonawca",
      excluded: ["Scrum Master", "Tester manualny"],
    });
    expect(toast.showSuccess).toHaveBeenCalled();
  });

  it("błąd zapisu mówi to po polsku i zostawia okno", async () => {
    const user = userEvent.setup();
    api.put.mockRejectedValue(new Error("boom"));
    renderBlock(false);
    await user.click(screen.getByTestId("review-role-profile-edit"));
    await user.click(screen.getByTestId("review-role-profile-save"));
    await vi.waitFor(() => expect(toast.showError).toHaveBeenCalled());
    expect(screen.getByTestId("review-role-profile-dialog")).toBeInTheDocument();
  });
});
