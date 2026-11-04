/**
 * „Ludzie i technologie” (22.10.2026) — czyste funkcje zakładki: widok
 * z adresu (dawne zakładki przekierowują), kropki siły, karty działów
 * z mapy i drzewa (także bez drzewa — Finanse), liczby kompletności i jedna
 * propozycja automatu na pasek „Do zatwierdzenia”. Dane fikcyjne.
 */
import { describe, expect, it } from "vitest";

import {
  completeness,
  departmentCards,
  firstProposal,
  openProposalCount,
  peopleOutsideDepartments,
  peopleViewFrom,
  proposalReason,
  strengthDots,
  topSkillIds,
} from "@/components/care/client/people-tech-format";
import { clientOrgWithHealth, peopleTechMap } from "@/app/preview/hr-client-people/fixtures";
import { bankStructure, telecomStructure } from "@/app/preview/hr-client-structure/fixtures";

const TODAY = "2026-10-22";

describe("peopleViewFrom", () => {
  it("?view= wygrywa, dawne zakładki prowadzą do drzewa i mapy, reszta to Działy", () => {
    expect(peopleViewFrom("mapa", "ludzie")).toBe("mapa");
    expect(peopleViewFrom(null, "struktura")).toBe("drzewo");
    expect(peopleViewFrom(null, "technologie")).toBe("mapa");
    expect(peopleViewFrom("drzewo", "technologie")).toBe("drzewo");
    expect(peopleViewFrom("cokolwiek", "ludzie")).toBe("dzialy");
    expect(peopleViewFrom(null, null)).toBe("dzialy");
  });
});

describe("strengthDots", () => {
  it("kropki = liczba rodzajów źródeł, najwyżej trzy", () => {
    expect(strengthDots(0)).toBe("○○○");
    expect(strengthDots(1)).toBe("●○○");
    expect(strengthDots(2)).toBe("●●○");
    expect(strengthDots(3)).toBe("●●●");
    expect(strengthDots(4)).toBe("●●●");
  });
});

describe("departmentCards", () => {
  it("z drzewem: menedżer naszych z „Podlega pod”, nasi z kropką, rekrutacje i „Szukają”", () => {
    const cards = departmentCards(peopleTechMap(TODAY), clientOrgWithHealth(TODAY));
    const payments = cards.find((card) => card.area.name === "Płatności");
    const data = cards.find((card) => card.area.name === "Data");
    if (!payments || !data) throw new Error("brak działów w danych");

    expect(data.managers.map((m) => [m.name, m.reportsTo])).toEqual([
      ["Piotr Menedżerski", "Zenon Dyrektorski"],
    ]);
    expect(data.consultantsCount).toBe(3);
    expect(payments.openJobs.map((job) => job.title)).toEqual([
      "Java Developer",
      "DevOps Engineer (OpenShift)",
    ]);
    // Otwarte rekrutacje i role z sygnału „klient zatrudnia”, bez powtórzeń.
    expect(payments.seeking).toEqual(["Java Developer", "DevOps Engineer (OpenShift)", "Java", "QA"]);
    // Luka po źródle, z osobą z działu do dopytania przy najbliższej rozmowie.
    expect(payments.gap).toBe("Komu podlega Katarzyna Płatnicza? — dopytać przy najbliższej rozmowie (Anna K.).");
    expect(data.gap).toMatch(/^Azure Data Factory znane tylko z rozmowy z konsultantem z \d\d\.\d{4} — dopytać przy najbliższej rozmowie \(/);
    expect(payments.base).toEqual({ skills: ["Java 17", "Spring Boot"], count: 212 });
    expect(payments.hiringSignals[0]?.roles).toEqual(["Java", "QA"]);
    expect(data.managers[0]).toMatchObject({ reportsToPosition: expect.any(String) });
    // Dział bez źródła z 18 miesięcy ma lukę, choć nie ma sygnału do karty.
    const cloud = cards.find((card) => card.area.name === "CI/CD i chmura");
    expect(cloud?.gap).toBe("Brak źródła technologii od 18 miesięcy — dopytać, na czym pracują.");
    expect(cloud?.hasSignal).toBe(false);
    // Remis siły (trzy rodzaje źródeł) — po nazwie.
    expect(topSkillIds(payments)).toEqual([801, 803, 802]);
  });

  it("bez drzewa (Finanse) menedżerowie i liczby naszych idą z mapy", () => {
    const cards = departmentCards(peopleTechMap(TODAY), null);
    const payments = cards.find((card) => card.area.name === "Płatności");
    expect(payments?.managers.map((m) => [m.name, m.reportsTo, m.consultantsCount])).toEqual([
      ["Katarzyna Płatnicza", null, 1],
    ]);
    expect(payments?.consultants).toEqual([]);
    expect(payments?.consultantsCount).toBe(1);
  });

  it("ludzie klienta bez działu to sekcja „Bez działu” drzewa", () => {
    expect(peopleOutsideDepartments(clientOrgWithHealth(TODAY)).map((p) => p.name)).toEqual([
      "Michał Liniowy",
    ]);
    expect(peopleOutsideDepartments(null)).toEqual([]);
  });
});

describe("completeness", () => {
  it("liczby nagłówka: nasi, działy z naszymi, z menedżerem, mapa z dnia, prośby", () => {
    const c = completeness(peopleTechMap(TODAY), clientOrgWithHealth(TODAY));
    expect(c).toEqual({
      consultants: 5,
      departmentsWithOurs: 2,
      departmentsTotal: 4,
      withManager: 4,
      mapOn: TODAY,
      requests: 2,
    });
  });

  it("bez drzewa: bez „z menedżerem” i bez próśb (nie wiemy, nie zero)", () => {
    const c = completeness(peopleTechMap(TODAY), null);
    expect(c.withManager).toBeNull();
    expect(c.requests).toBeNull();
    expect(c.consultants).toBe(5);
  });
});

describe("firstProposal", () => {
  it("najpierw menedżer konsultanta (pewne przed „do sprawdzenia”), potem „Podlega pod”", () => {
    const bank = bankStructure();
    expect(firstProposal(bank)).toMatchObject({ kind: "manager", row: { contract_id: 9405 } });
    expect(openProposalCount(bank)).toBe(2);
    const onlyOrg = { ...bank, managers: [] };
    expect(firstProposal(onlyOrg)).toMatchObject({
      kind: "reports_to",
      row: { contact: { name: "Katarzyna Płatnicza" } },
    });
  });

  it("pominięte i bez osoby nie trafiają na pasek", () => {
    const telecom = telecomStructure(TODAY);
    const first = firstProposal(telecom);
    expect(first?.row.skipped).toBeNull();
    expect(first?.row.proposal?.contact).toBeTruthy();
    const none = {
      ...telecom,
      managers: telecom.managers.map((row) => ({ ...row, proposal: null })),
      reports_to: [],
    };
    expect(firstProposal(none)).toBeNull();
  });
});

describe("proposalReason", () => {
  it("pasek mówi zdaniem: pewność i źródła bez powtórzeń", () => {
    expect(
      proposalReason("certain", {
        contact: { id: 1, name: "Iwona Zespołowa", position: null, area: null },
        sources: [{ source: "title_same_department", detail: null }],
      } as never),
    ).toBe("pewne: wyższe stanowisko w tym samym dziale");
    expect(
      proposalReason("uncertain", {
        contact: null,
        sources: [
          { source: "line_manager", detail: "Iwona" },
          { source: "line_manager", detail: "I. Zespołowa" },
          { source: "same_team", detail: null },
        ],
      } as never),
    ).toBe("do sprawdzenia: „Line Manager” na kontrakcie, menedżer kolegów z zespołu");
  });
});
