import { describe, expect, it } from "vitest";

import { hrConfig } from "@/app/preview/hr-fixtures";

import { approvalsAccess, visibleChips } from "../approvals-filter";

describe("Akceptacje: które części widzi osoba", () => {
  it("„Raporty godzin” bez zespołu (back office, 28.10.2026): same raporty godzin", () => {
    const access = approvalsAccess(
      hrConfig({ timesheets: true, payroll: true, leave_approver: false }),
    );
    expect(access.time).toBe(true);
    expect(access.leave).toBe(false);
    expect(visibleChips(access)).toEqual(["all", "time"]);
  });

  it("przełożony dalej widzi nieobecności i raporty godzin", () => {
    const access = approvalsAccess(
      hrConfig({ is_manager: true, direct_reports: 2, leave_approver: true }),
    );
    expect(visibleChips(access)).toEqual(["all", "leave", "time", "info"]);
  });

  it("odpowiedź bez pola `leave_approver` (starszy backend) nie chowa nieobecności", () => {
    expect(approvalsAccess(hrConfig({ people_admin: true })).leave).toBe(true);
  });
});
