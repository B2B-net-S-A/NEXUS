import { describe, expect, it } from "vitest"

import type { BoardTasksResponse } from "@/lib/api/boardTasks"
import {
  canCustomizeBoardPanel,
  canHidePanel,
  effectiveHiddenPanels,
  withoutHiddenPanels,
} from "@/lib/dashboard-panels"

const head = { role: "head_of_recruitment" as const }
const admin = { role: "admin" as const }
const recruiter = { role: "recruiter" as const }

function tasks(): BoardTasksResponse {
  return {
    cpro_to_send: [{ stage_id: 1 } as never],
    cpro_sent: [{ stage_id: 2 } as never],
    window_days: 14,
    allocation_proposals: [{ job_id: 1 } as never],
    can_decide_proposals: true,
    new_job_leads: [{ job_id: 2 } as never],
    prep_attention: [{ event_id: 3 } as never],
    can_set_cpro_sender: true,
  }
}

describe("listy nad pulpitem", () => {
  it("„CV w drodze” usuwa każdy, resztę tylko Head of Recruitment i admin", () => {
    expect(canHidePanel(recruiter, "cv_in_transit")).toBe(true)
    expect(canHidePanel(recruiter, "new_job_leads")).toBe(false)
    expect(canHidePanel(head, "new_job_leads")).toBe(true)
    expect(canHidePanel(admin, "allocation_proposals")).toBe(true)
    expect(canCustomizeBoardPanel(head)).toBe(true)
    expect(canCustomizeBoardPanel(admin)).toBe(true)
    expect(canCustomizeBoardPanel(recruiter)).toBe(false)
  })

  it("klucz bez prawa do ukrycia nie chowa listy", () => {
    const stored = ["new_job_leads", "cv_in_transit", "nieznany"]
    expect([...effectiveHiddenPanels(recruiter, stored)]).toEqual(["cv_in_transit"])
    expect([...effectiveHiddenPanels(head, stored)]).toEqual(["cv_in_transit", "new_job_leads"])
  })

  it("ukryta lista wygląda dla panelu jak pusta", () => {
    const data = tasks()
    const out = withoutHiddenPanels(data, new Set(["allocation_proposals", "cpro"]))
    expect(out.allocation_proposals).toEqual([])
    expect(out.cpro_to_send).toEqual([])
    expect(out.cpro_sent).toEqual([])
    expect(out.can_set_cpro_sender).toBe(false)
    expect(out.new_job_leads).toHaveLength(1)
    expect(out.prep_attention).toHaveLength(1)
    // Odpowiedź z serwera zostaje nietknięta (cache react-query).
    expect(data.allocation_proposals).toHaveLength(1)
  })

  it("bez ukrytych list zwraca tę samą odpowiedź", () => {
    const data = tasks()
    expect(withoutHiddenPanels(data, new Set())).toBe(data)
  })
})
