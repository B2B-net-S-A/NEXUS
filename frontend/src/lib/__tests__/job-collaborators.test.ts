import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import {
  collaboratorChanges,
  collaboratorsSummary,
  manualCollaboratorIds,
  saveCollaboratorChanges,
} from "@/lib/job-collaborators";

vi.mock("@/lib/api", () => ({
  default: { post: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("job-collaborators", () => {
  const collaborators = [
    { id: 1, name: "Anna Ręczna", source: "manual" },
    { id: 2, name: "Cała Kategoria", source: "auto_cc" },
    { id: 3, name: "Stary Wpis" },
  ];

  it("ręczni = wszystko poza auto_cc (brak pola = ręczny)", () => {
    expect(manualCollaboratorIds(collaborators)).toEqual([1, 3]);
    expect(manualCollaboratorIds(null)).toEqual([]);
  });

  it("różnica dopisuje nowych, zdejmuje usuniętych i pomija prowadzącego", () => {
    expect(collaboratorChanges([1, 3], [3, 4, 9], 9)).toEqual({
      add: [4],
      remove: [1],
    });
    expect(collaboratorChanges([1], [1])).toEqual({ add: [], remove: [] });
  });

  it("„+N” i podpowiedź liczą tylko ręcznych", () => {
    expect(collaboratorsSummary(collaborators)).toEqual({
      count: 2,
      tooltip: "Współpracownicy: Anna Ręczna, Stary Wpis",
    });
    expect(collaboratorsSummary([])).toEqual({ count: 0, tooltip: "" });
  });

  it("zapis woła trasy i zgłasza częściową awarię po polsku", async () => {
    vi.mocked(api.post)
      .mockResolvedValueOnce({ data: {} } as never)
      .mockRejectedValueOnce({
        response: { status: 403, data: { detail: "Nie masz uprawnień do edycji rekrutacji." } },
      } as never);
    vi.mocked(api.delete).mockResolvedValue({ data: {} } as never);

    const failure = await saveCollaboratorChanges(5, { add: [4, 6], remove: [1] });

    expect(api.post).toHaveBeenCalledWith("/api/jobs/5/collaborators", { user_id: 4 });
    expect(api.delete).toHaveBeenCalledWith("/api/jobs/5/collaborators/1");
    expect(failure).toBe(
      "zapisano 2 z 3 zmian współpracowników (Nie masz uprawnień do edycji rekrutacji.)",
    );
  });

  it("bez zmian nic nie woła", async () => {
    expect(await saveCollaboratorChanges(5, { add: [], remove: [] })).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });
});
