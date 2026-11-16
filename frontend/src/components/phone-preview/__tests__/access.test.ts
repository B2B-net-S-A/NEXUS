import { describe, expect, it } from "vitest";

import { FIRMA_PERMISSION, FIRMA_ROLES } from "@/components/insights/InsightsView";
import { isBoardAllowedPath } from "@/lib/board-access";
import { startAllows } from "@/lib/novelties/logic";
import type { User } from "@/store/auth";

import { resultsKind, seesAllRecruitments, seesAttention, seesRecruitment, seesSearch, seesToday, seesWholeTeam, shortName } from "../access";
import { dialable, looksLikePhone } from "../contact";
import { isStartScreen } from "../usePhonePreviewRedirect";

const person = (role: string, extra: Partial<User> = {}) =>
  ({ id: 1, role, roles: [role], ...extra }) as unknown as User;

describe("Podgląd na telefonie: kto co widzi", () => {
  it("Firma ma te same bramki co zakładka Firma w Insights", () => {
    expect(FIRMA_PERMISSION).toBe("company_results");
    expect(FIRMA_ROLES).toEqual(["board"]);
    expect(resultsKind(person("board"))).toBe("company");
  });

  it("DL ma portfel, rekruter swój miesiąc, DL z rolą rekrutera dalej portfel", () => {
    expect(resultsKind(person("delivery_lead"))).toBe("portfolio");
    expect(resultsKind(person("recruiter"))).toBe("month");
    expect(resultsKind(person("recruiter", { roles: ["recruiter", "delivery_lead"] } as Partial<User>))).toBe("portfolio");
  });

  it("Finanse nie dostają sum firmy i startują bez zakładki Wyniki", () => {
    expect(resultsKind(person("finance"))).toBeNull();
    expect(resultsKind(null)).toBeNull();
  });

  it("cały zespół tylko admin i HoR, jak `_OVERSIGHT_ROLES` na serwerze", () => {
    expect(seesWholeTeam(person("admin"))).toBe(true);
    expect(seesWholeTeam(person("head_of_recruitment"))).toBe(true);
    expect(seesWholeTeam(person("delivery_lead"))).toBe(false);
    expect(seesWholeTeam(person("recruiter"))).toBe(false);
  });

  it("rekruter nie widzi „Do uwagi”, admin widzi", () => {
    expect(seesAttention(person("recruiter"))).toBe(false);
    expect(seesAttention(person("admin"))).toBe(true);
  });

  it("Finanse bez planu dnia i ze wszystkimi rekrutacjami, rekruter tylko ze swoimi", () => {
    expect(seesAllRecruitments(person("finance"))).toBe(true);
    expect(seesAllRecruitments(person("recruiter"))).toBe(false);
    expect(seesAllRecruitments(person("delivery_lead"))).toBe(false);
    expect(seesToday(person("finance"))).toBe(false);
    expect(seesToday(person("board"))).toBe(false);
    expect(seesToday(null)).toBe(false);
  });

  it("brak użytkownika nie otwiera rekrutacji", () => {
    expect(seesRecruitment(null)).toBe(false);
  });

  it("Szukaj mają ci, którzy dzwonią do kandydatów; Rada i Finanse nie", () => {
    expect(seesSearch(person("recruiter"))).toBe(true);
    expect(seesSearch(person("delivery_lead"))).toBe(true);
    expect(seesSearch(person("admin"))).toBe(true);
    expect(seesSearch(person("head_of_recruitment"))).toBe(true);
    expect(seesSearch(person("finance"))).toBe(false);
    expect(seesSearch(person("board"))).toBe(false);
    expect(seesSearch(null)).toBe(false);
  });
});

describe("Podgląd na telefonie: numer do wybrania", () => {
  it("zostawia same cyfry i plus z przodu", () => {
    expect(dialable("+48 507 988 829")).toBe("+48507988829");
    expect(dialable("(22) 123-45-67")).toBe("221234567");
  });

  it("za krótki albo pusty numer nie daje przycisku", () => {
    expect(dialable("123")).toBeNull();
    expect(dialable("brak")).toBeNull();
    expect(dialable(null)).toBeNull();
    expect(dialable("  ")).toBeNull();
  });

  it("rozpoznaje numer wklejony z połączeń, nie nazwisko ani mail", () => {
    expect(looksLikePhone("507 988 829")).toBe(true);
    expect(looksLikePhone("+48507988829")).toBe(true);
    expect(looksLikePhone("Kotow")).toBe(false);
    expect(looksLikePhone("jan600@example.com")).toBe(false);
    expect(looksLikePhone("12345")).toBe(false);
  });
});

describe("Podgląd na telefonie: wejście", () => {
  it("przenosi tylko z ekranu startowego, link z maila otwiera swój ekran", () => {
    expect(isStartScreen("/dashboard", person("recruiter"))).toBe(true);
    expect(isStartScreen("/jobs/123", person("recruiter"))).toBe(false);
    expect(isStartScreen("/insights", person("recruiter"))).toBe(false);
    expect(isStartScreen("/insights", person("board"))).toBe(true);
  });

  it("Rada i osoba przed Startem mogą otworzyć podgląd", () => {
    expect(isBoardAllowedPath("/podglad")).toBe(true);
    expect(isBoardAllowedPath("/podglad/zespol")).toBe(true);
    expect(startAllows("/podglad/dzis", false)).toBe(true);
  });
});

describe("shortName", () => {
  it("zostawia imię i pierwszą literę ostatniego nazwiska", () => {
    expect(shortName("Anna Nowak")).toBe("Anna N.");
    expect(shortName("Anna Maria Nowak-Kowalska")).toBe("Anna N.");
    expect(shortName("  Anna  ")).toBe("Anna");
    expect(shortName(null)).toBe("");
  });
});
