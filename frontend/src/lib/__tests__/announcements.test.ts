import { describe, expect, it } from "vitest"

import {
  audienceLabel,
  defaultVisibleUntil,
  publishedLabel,
  validateAnnouncement,
  type AnnouncementForm,
} from "@/lib/announcements"

// 28.10.2026 12:00 w Warszawie.
const NOW = new Date("2026-10-28T11:00:00Z")

function form(overrides: Partial<AnnouncementForm> = {}): AnnouncementForm {
  return {
    title: "Piątek: Daily o 9:30",
    body: "W piątek Daily wyjątkowo o 9:30.",
    visibleUntil: "2026-10-31",
    audience: "all",
    roles: [],
    pinned: false,
    important: false,
    ...overrides,
  }
}

describe("validateAnnouncement", () => {
  it("poprawny formularz nie ma błędów", () => {
    expect(validateAnnouncement(form(), NOW)).toEqual({})
    expect(validateAnnouncement(form({ visibleUntil: "2026-10-28" }), NOW)).toEqual({})
  })

  it("odmawia złego tytułu, pustej treści, HTML-a, daty i braku ról", () => {
    expect(validateAnnouncement(form({ title: "ab" }), NOW).title).toMatch(/Tytuł/)
    expect(validateAnnouncement(form({ body: "  " }), NOW).body).toMatch(/Treść/)
    expect(validateAnnouncement(form({ body: "<a href='x'>link</a>" }), NOW).body).toMatch(/HTML/)
    expect(validateAnnouncement(form({ body: "a < b, dzięki <3" }), NOW)).toEqual({})
    expect(validateAnnouncement(form({ visibleUntil: "2026-10-27" }), NOW).visibleUntil).toMatch(/przeszłości/)
    expect(validateAnnouncement(form({ visibleUntil: "2027-02-01" }), NOW).visibleUntil).toMatch(/90 dni/)
    expect(validateAnnouncement(form({ visibleUntil: "" }), NOW).visibleUntil).toMatch(/Wybierz/)
    expect(validateAnnouncement(form({ audience: "roles", roles: [] }), NOW).roles).toMatch(/rolę/)
  })
})

describe("etykiety", () => {
  it("odbiorcy i domyślny termin", () => {
    expect(audienceLabel([])).toBe("wszyscy")
    expect(audienceLabel(["recruiter", "delivery_lead"])).toBe("Rekruterzy, Delivery Leadzi")
    expect(defaultVisibleUntil(NOW)).toBe("2026-11-04")
  })

  it("kiedy opublikowano — dziś, wczoraj, data", () => {
    expect(publishedLabel("2026-10-28T08:05:00Z", NOW)).toBe("dziś 09:05")
    expect(publishedLabel("2026-10-27T16:41:00Z", NOW)).toBe("wczoraj 17:41")
    expect(publishedLabel("2026-10-20T10:00:00Z", NOW)).toBe("20.10")
  })
})
