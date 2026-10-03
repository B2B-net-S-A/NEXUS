import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import {
  COLLABORATOR_ROLES,
  collaboratorChanges,
  hasCollaboratorChanges,
  manualCollaboratorIds,
  manualCollaborators,
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

  it("cała kategoria (`auto_cc`) to nie osoby przy rekrutacji — zostają wyłącznie dopisani ręcznie", () => {
    expect(manualCollaborators(collaborators).map((c) => c.name)).toEqual([
      "Anna Ręczna",
      "Stary Wpis",
    ]);
  });

  it("role, które serwer przyjmuje jako osobę przy rekrutacji — bez Head of Recruitment i Finansów", () => {
    expect([...COLLABORATOR_ROLES]).toEqual([
      "admin",
      "delivery_lead",
      "recruiter",
    ]);
  });

  it("różnica dopisuje nowych, zdejmuje usuniętych i pomija pierwszego rekrutera", () => {
    expect(collaboratorChanges([1, 3], [3, 4, 9], 9)).toEqual({
      add: [4],
      remove: [1],
    });
    expect(collaboratorChanges([1], [1])).toEqual({ add: [], remove: [] });
  });

  it("`hasCollaboratorChanges` — czy jest co zapisywać", () => {
    expect(hasCollaboratorChanges({ add: [], remove: [] })).toBe(false);
    expect(hasCollaboratorChanges({ add: [4], remove: [] })).toBe(true);
    expect(hasCollaboratorChanges({ add: [], remove: [1] })).toBe(true);
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
      "zapisano 2 z 3 zmian na liście kolejnych osób (Nie masz uprawnień do edycji rekrutacji.)",
    );
  });

  it("gdy nie zapisała się żadna zmiana, mówi „nie zapisano kolejnych osób”", async () => {
    vi.mocked(api.post).mockRejectedValue({
      response: { status: 403, data: { detail: "Nie masz uprawnień do edycji rekrutacji." } },
    } as never);

    const failure = await saveCollaboratorChanges(5, { add: [4], remove: [] });

    expect(failure).toBe(
      "nie zapisano kolejnych osób (Nie masz uprawnień do edycji rekrutacji.)",
    );
  });

  it("bez zmian nic nie woła", async () => {
    expect(await saveCollaboratorChanges(5, { add: [], remove: [] })).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });
});
