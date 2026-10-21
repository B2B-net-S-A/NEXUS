/**
 * Rola „Rada nadzorcza” (0490, decyzja Artura 21.10.2026): jeden ekran —
 * Insights, domyślnie widok Firma. Menu, lądowanie po zalogowaniu i lista
 * dozwolonych tras (to samo czyta middleware).
 */
import { describe, expect, it } from "vitest";
import { BOARD_HOME, isBoardAllowedPath } from "@/lib/board-access";
import { visibleNavEntries } from "@/lib/nav-registry";
import { isBoardOnly, postLoginDestination } from "@/store/auth";

const board = {
  role: "board" as const,
  roles: ["board" as const],
  profile_completed: true,
  force_password_change: false,
};

describe("menu Rady nadzorczej", () => {
  it("ma tylko Insights, Pomoc i Ustawienia konta", () => {
    const ids = visibleNavEntries(board, { contactQueueEnabled: true }).map(
      (entry) => entry.id,
    );
    expect(ids).toEqual(["insights", "help", "settings"]);
  });

  it("kartoteka w „Ludziach” nie dokłada „Mój czas” ani „Ludzi”", () => {
    const hr = { myTime: true, people: true, equipment: true, care: true };
    const ids = visibleNavEntries(board, { contactQueueEnabled: true, hr }).map(
      (entry) => entry.id,
    );
    expect(ids).toEqual(["insights", "help", "settings"]);
  });
});

describe("lądowanie Rady nadzorczej", () => {
  it("pulpit, strona główna i ekrany pracy prowadzą do kokpitu Firma", () => {
    expect(BOARD_HOME).toBe("/insights?tab=firma");
    expect(postLoginDestination(board)).toBe(BOARD_HOME);
    expect(postLoginDestination(board, "/dashboard")).toBe(BOARD_HOME);
    expect(postLoginDestination(board, "/jobs/12")).toBe(BOARD_HOME);
  });

  it("jawny adres raportu Insights zostaje", () => {
    expect(postLoginDestination(board, "/insights?tab=raporty&report=rok-do-roku")).toBe(
      "/insights?tab=raporty&report=rok-do-roku",
    );
  });

  it("wymuszona zmiana hasła wygrywa", () => {
    expect(postLoginDestination({ ...board, force_password_change: true })).toBe(
      "/profile?force_password_change=1",
    );
  });
});

describe("trasy Rady nadzorczej", () => {
  it.each(["/insights", "/insights/x", "/profile", "/settings", "/help", "/help/a"])(
    "%s jest dozwolone",
    (path) => expect(isBoardAllowedPath(path)).toBe(true),
  );

  it.each(["/", "/dashboard", "/settings/api-keys", "/jobs", "/insightsx", "/my-time"])(
    "%s nie jest dozwolone",
    (path) => expect(isBoardAllowedPath(path)).toBe(false),
  );

  it("rozpoznaje wyłącznie konto z samą rolą Rady", () => {
    expect(isBoardOnly(board)).toBe(true);
    expect(isBoardOnly({ role: "admin", roles: ["admin"] })).toBe(false);
    expect(isBoardOnly(null)).toBe(false);
  });
});
