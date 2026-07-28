import { AxiosError, AxiosHeaders } from "axios"
import { describe, expect, it } from "vitest"

import {
  extractPriorityWorkConflict,
  priorityCapacityFields,
  priorityWorkErrorMessage,
  type PriorityWorkConflict,
} from "@/lib/priority-work-api"

function axiosConflict(
  conflict: PriorityWorkConflict,
  nested = true,
): AxiosError {
  const headers = new AxiosHeaders()
  const config = { headers }
  return new AxiosError(
    "Request failed with status code 409",
    "ERR_BAD_REQUEST",
    config as never,
    null,
    {
      status: 409,
      statusText: "Conflict",
      headers,
      config: config as never,
      data: nested ? { detail: conflict } : conflict,
    },
  )
}

const CONFLICT: PriorityWorkConflict = {
  code: "PRIORITY_WORK_LOCKED",
  action: "open_process",
  job_id: 42,
  active_plan_id: 7,
  reason: "JOB_NOT_ASSIGNED",
  next_action: "CONTACT_HEAD_OF_RECRUITMENT",
  message: "Nie możesz dodać nowej osoby do tego requestu.",
}

describe("Priority Work conflict helpers", () => {
  it("extracts a FastAPI detail conflict", () => {
    expect(extractPriorityWorkConflict(axiosConflict(CONFLICT))).toEqual(
      CONFLICT,
    )
  })

  it("also accepts a direct structured response body", () => {
    expect(
      extractPriorityWorkConflict(axiosConflict(CONFLICT, false)),
    ).toEqual(CONFLICT)
  })

  it("adds an actionable next step to the backend message", () => {
    expect(priorityWorkErrorMessage(axiosConflict(CONFLICT))).toBe(
      "Nie możesz dodać nowej osoby do tego requestu. Skontaktuj się z Head of Recruitment, jeśli potrzebujesz wyjątku.",
    )
  })

  it("does not treat unrelated errors as Priority Work conflicts", () => {
    expect(priorityWorkErrorMessage(new Error("boom"))).toBeNull()
  })
})

describe("Priority Work capacity payload", () => {
  it("sends the calculated capacity and its reason when total differs from 12", () => {
    expect(
      priorityCapacityFields(
        [5, 4, 2],
        "Duże obciążenie aktywnym carry-over",
      ),
    ).toEqual({
      verification_capacity: 11,
      capacity_reason: "Duże obciążenie aktywnym carry-over",
    })
  })

  it("removes a stale exception reason when the standard capacity is restored", () => {
    expect(priorityCapacityFields([6, 4, 2], "stary powód")).toEqual({
      verification_capacity: 12,
      capacity_reason: null,
    })
  })
})
