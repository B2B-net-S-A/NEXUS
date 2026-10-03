import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import {
  addRecruiter,
  assignedByCaption,
  canRemoveRecruiter,
  claimJob,
  hasRecruiter,
  hasWorkingOwner,
  joinJob,
  proposedRecruiters,
  recruitersOf,
  recruitersSummary,
  removeRecruiter,
  workingRecruiters,
  type JobRecruiter,
  type RecruiterLike,
} from "@/lib/job-team";

vi.mock("@/lib/api", () => ({
  default: { post: vi.fn(), delete: vi.fn() },
}));

const apiPost = vi.mocked(api.post);
const apiDelete = vi.mocked(api.delete);

beforeEach(() => {
  vi.clearAllMocks();
  apiPost.mockResolvedValue({ data: {} } as never);
  apiDelete.mockResolvedValue({ data: {} } as never);
});

function person(partial: Partial<JobRecruiter> & { user_id: number }): JobRecruiter {
  return {
    name: `Osoba ${partial.user_id}`,
    via: "assignment",
    proposed: false,
    assigned_by_name: null,
    ...partial,
  };
}

const owner = person({ user_id: 1, name: "Marta Kowalska", via: "owner" });
const assigned = person({
  user_id: 2,
  name: "Jan Nowak",
  assigned_by_name: "Anna Lis",
});
const collaborator = person({ user_id: 3, name: "Ewa Zielińska", via: "collaborator" });
const proposal = person({ user_id: 4, name: "Piotr Wiśniewski", proposed: true });

describe("recruitersOf", () => {
  it("lista z serwera wygrywa z dotychczasowymi polami", () => {
    const job = {
      recruiters: [owner, proposal],
      primary_owner: { id: 9, name: "Stary Prowadzący" },
      collaborators: [{ id: 8, name: "Stary Współpracownik" }],
    };
    expect(recruitersOf(job)).toEqual([owner, proposal]);
  });

  it("pusta lista z serwera znaczy „nikt nie pracuje” — bez sięgania po stare pola", () => {
    expect(
      recruitersOf({ recruiters: [], primary_owner: { id: 9, name: "Stary Prowadzący" } }),
    ).toEqual([]);
  });

  it("bez pola składa listę z prowadzącego i ręcznych współpracowników", () => {
    const job = {
      primary_owner: { id: 1, name: "Marta Kowalska", role: "recruiter" },
      collaborators: [
        { id: 2, name: "Jan Nowak", role: "recruiter", source: "manual" },
        { id: 5, name: "Cała Kategoria", role: "recruiter", source: "auto_cc" },
        { id: 3, name: "  ", role: "delivery_lead" },
      ],
    };
    expect(recruitersOf(job)).toEqual([
      { user_id: 1, name: "Marta Kowalska", via: "owner", proposed: false, assigned_by_name: null },
      { user_id: 2, name: "Jan Nowak", via: "collaborator", proposed: false, assigned_by_name: null },
      { user_id: 3, name: "#3", via: "collaborator", proposed: false, assigned_by_name: null },
    ]);
  });

  it("w zapasie nieaktywne konto nie pracuje, a prowadzący nie dubluje się jako współpracownik", () => {
    const job = {
      primary_owner: { id: 1, name: "Była Prowadząca", is_active: false },
      collaborators: [
        { id: 2, name: "Aktywna", is_active: true },
        { id: 6, name: "Nieaktywny", is_active: false },
      ],
    };
    expect(recruitersOf(job).map((p) => [p.user_id, p.via])).toEqual([[2, "collaborator"]]);

    const doubled = {
      primary_owner: { id: 1, name: "Marta Kowalska" },
      collaborators: [{ id: 1, name: "Marta Kowalska" }],
    };
    expect(recruitersOf(doubled).map((p) => [p.user_id, p.via])).toEqual([[1, "owner"]]);
  });

  it("w zapasie osoba nie niesie roli pracy — podział rekruter / sourcer zniknął (02.10.2026)", () => {
    const [person] = recruitersOf({
      primary_owner: { id: 1, name: "X", role: "delivery_lead", roles: ["delivery_lead"] },
    });
    expect(person).not.toHaveProperty("role");
  });

  it("brak rekrutacji albo brak danych daje pustą listę", () => {
    expect(recruitersOf(null)).toEqual([]);
    expect(recruitersOf(undefined)).toEqual([]);
    expect(recruitersOf({})).toEqual([]);
    expect(recruitersOf({ recruiters: null, primary_owner: null, collaborators: null })).toEqual([]);
  });
});

describe("pracujący i propozycje", () => {
  const people = [owner, assigned, collaborator, proposal];

  it("rozdziela pracujących od propozycji automatu", () => {
    expect(workingRecruiters(people)).toEqual([owner, assigned, collaborator]);
    expect(proposedRecruiters(people)).toEqual([proposal]);
  });

  it("sama propozycja to jeszcze nie rekruter", () => {
    expect(hasRecruiter(people)).toBe(true);
    expect(hasRecruiter([proposal])).toBe(false);
    expect(hasRecruiter([])).toBe(false);
  });

  it("pracujący prowadzący to osoba `via: owner`, nie propozycja", () => {
    expect(hasWorkingOwner(people)).toBe(true);
    expect(hasWorkingOwner([assigned, collaborator])).toBe(false);
    expect(hasWorkingOwner([person({ user_id: 7, via: "owner", proposed: true })])).toBe(false);
  });

  it("przyjmuje osoby z pulpitu bez `via` i zachowuje ich typ", () => {
    const board = [
      { user_id: 7, name: "Anna Przykładowa", proposed: true, source: "auto" as const },
      { user_id: 8, name: "Bartek Testowy", proposed: false, source: "manual" as const },
    ];
    expect(workingRecruiters(board).map((p) => p.source)).toEqual(["manual"]);
    expect(proposedRecruiters(board).map((p) => p.source)).toEqual(["auto"]);
    expect(hasWorkingOwner(board)).toBe(false);
  });
});

describe("recruitersSummary", () => {
  it("pierwsza osoba skrócona, reszta jako „+N”, w podpowiedzi wszyscy", () => {
    expect(recruitersSummary([owner, assigned, collaborator, proposal])).toEqual({
      lead: "Marta K.",
      more: 2,
      names: ["Marta Kowalska", "Jan Nowak", "Ewa Zielińska"],
      proposedNames: ["Piotr Wiśniewski"],
      tooltip:
        "Rekruterzy: Marta Kowalska, Jan Nowak, Ewa Zielińska · Propozycja automatu: Piotr Wiśniewski",
    });
  });

  it("jedna osoba: liczba pojedyncza i bez „+N”", () => {
    expect(recruitersSummary([owner])).toEqual({
      lead: "Marta K.",
      more: 0,
      names: ["Marta Kowalska"],
      proposedNames: [],
      tooltip: "Rekruter: Marta Kowalska",
    });
  });

  it("same propozycje: nikt nie prowadzi, podpowiedź mówi o propozycjach", () => {
    const second = person({ user_id: 5, name: "Olga Lis", proposed: true });
    expect(recruitersSummary([proposal, second])).toEqual({
      lead: null,
      more: 0,
      names: [],
      proposedNames: ["Piotr Wiśniewski", "Olga Lis"],
      tooltip: "Propozycje automatu: Piotr Wiśniewski, Olga Lis",
    });
  });

  it("nikt: pusta podpowiedź", () => {
    expect(recruitersSummary([])).toEqual({
      lead: null,
      more: 0,
      names: [],
      proposedNames: [],
      tooltip: "",
    });
  });
});

describe("assignedByCaption", () => {
  it("skraca nazwisko osoby, która przydzieliła", () => {
    expect(assignedByCaption(assigned)).toBe("przydzielił(a) Anna L.");
  });

  it("nie wiadomo kto — bez podpisu", () => {
    expect(assignedByCaption(owner)).toBeNull();
    const fromBoard: RecruiterLike = { user_id: 7, name: "Anna", proposed: false };
    expect(assignedByCaption(fromBoard)).toBeNull();
  });
});

describe("canRemoveRecruiter", () => {
  const nobody = { canStaff: false, canDecide: false, canEdit: false };

  it("propozycję odrzuca tylko osoba rozstrzygająca propozycje", () => {
    expect(canRemoveRecruiter(proposal, { ...nobody, canDecide: true })).toBe(true);
    // Delivery Lead przydziela ludzi, ale propozycji automatu nie rozstrzyga.
    expect(canRemoveRecruiter(proposal, { ...nobody, canStaff: true, canEdit: true })).toBe(false);
  });

  it("współpracownika zdejmuje każdy, kto redaguje rekrutację", () => {
    expect(canRemoveRecruiter(collaborator, { ...nobody, canEdit: true })).toBe(true);
    expect(canRemoveRecruiter(collaborator, { ...nobody, canStaff: true })).toBe(true);
    expect(canRemoveRecruiter(collaborator, { ...nobody, canDecide: true })).toBe(false);
  });

  it("prowadzącego i osobę z przypisaniem zdejmują tylko role przydzielające", () => {
    for (const target of [owner, assigned]) {
      expect(canRemoveRecruiter(target, { ...nobody, canStaff: true })).toBe(true);
      expect(canRemoveRecruiter(target, { ...nobody, canEdit: true, canDecide: true })).toBe(false);
    }
  });

  it("osoba z pulpitu bez `via` — tylko role przydzielające", () => {
    const fromBoard: RecruiterLike = { user_id: 7, name: "Anna", proposed: false };
    expect(canRemoveRecruiter(fromBoard, { ...nobody, canEdit: true })).toBe(false);
    expect(canRemoveRecruiter(fromBoard, { ...nobody, canStaff: true })).toBe(true);
  });

  it("bez uprawnień nic nie zdejmuje", () => {
    for (const target of [owner, assigned, collaborator, proposal]) {
      expect(canRemoveRecruiter(target, nobody)).toBe(false);
    }
  });
});

describe("removeRecruiter", () => {
  it("rola przydzielająca zdejmuje przez pulpit — każdą osobę, także współpracownika", async () => {
    await removeRecruiter(12, owner, { canStaff: true });
    await removeRecruiter(12, collaborator, { canStaff: true });
    expect(apiDelete).toHaveBeenNthCalledWith(1, "/api/request-board/jobs/12/people/1");
    expect(apiDelete).toHaveBeenNthCalledWith(2, "/api/request-board/jobs/12/people/3");
  });

  it("bez roli przydzielającej zdejmuje tylko współpracownika, trasą współpracowników", async () => {
    await removeRecruiter(12, collaborator, { canStaff: false });
    expect(apiDelete).toHaveBeenCalledTimes(1);
    expect(apiDelete).toHaveBeenCalledWith("/api/jobs/12/collaborators/3");
  });

  it("bez roli przydzielającej nie rusza prowadzącego ani przypisania — i nic nie wysyła", async () => {
    await expect(removeRecruiter(12, owner, { canStaff: false })).rejects.toThrow(
      "Tę osobę może zdjąć admin, Delivery Lead albo Head of Recruitment.",
    );
    await expect(removeRecruiter(12, assigned, { canStaff: false })).rejects.toThrow();
    await expect(
      removeRecruiter(12, { user_id: 7 }, { canStaff: false }),
    ).rejects.toThrow();
    expect(apiDelete).not.toHaveBeenCalled();
  });

  it("błąd serwera wraca do wołającego", async () => {
    const failure = { response: { status: 403, data: { detail: "Brak uprawnień." } } };
    apiDelete.mockRejectedValueOnce(failure as never);
    await expect(removeRecruiter(12, owner, { canStaff: true })).rejects.toBe(failure);
  });
});

describe("addRecruiter", () => {
  it("rola przydzielająca przy rekrutacji bez prowadzącego ustawia prowadzącego", async () => {
    await expect(
      addRecruiter(12, 7, { canStaff: true, hasWorkingOwner: false }),
    ).resolves.toBe("owner");
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost).toHaveBeenCalledWith("/api/jobs/12/owner", { user_id: 7 });
  });

  it("gdy prowadzący już pracuje, kolejna osoba dochodzi jako współpracownik", async () => {
    await expect(
      addRecruiter(12, 7, { canStaff: true, hasWorkingOwner: true }),
    ).resolves.toBe("collaborator");
    expect(apiPost).toHaveBeenCalledWith("/api/jobs/12/collaborators", { user_id: 7 });
  });

  it("bez roli przydzielającej zawsze współpracownik — także bez prowadzącego", async () => {
    await expect(
      addRecruiter(12, 7, { canStaff: false, hasWorkingOwner: false }),
    ).resolves.toBe("collaborator");
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost).toHaveBeenCalledWith("/api/jobs/12/collaborators", { user_id: 7 });
  });
});

describe("claimJob i joinJob", () => {
  it("przejęcie woła trasę claim bez ciała", async () => {
    await claimJob(12);
    expect(apiPost).toHaveBeenCalledWith("/api/jobs/12/claim");
  });

  it("dołączenie dopisuje zalogowaną osobę jako współpracownika", async () => {
    await joinJob(12, 44);
    expect(apiPost).toHaveBeenCalledWith("/api/jobs/12/collaborators", { user_id: 44 });
  });
});
