import { describe, expect, it } from "vitest"

import {
  ALL_TEAM_FILTERS,
  DEFAULT_TEAM_FILTERS,
  describeTeamFilters,
  isFiltered,
  parseStoredTeamFilters,
  teamFilterQuery,
} from "@/lib/team-filters"

describe("team filters", () => {
  it("starts from recruiters and all clients", () => {
    expect(DEFAULT_TEAM_FILTERS).toEqual({ role: "recruiter", clientId: null, clientName: null })
    expect(isFiltered(DEFAULT_TEAM_FILTERS)).toBe(true)
    expect(isFiltered(ALL_TEAM_FILTERS)).toBe(false)
  })

  it("sends only what differs from the whole team", () => {
    expect(teamFilterQuery(undefined)).toEqual({})
    expect(teamFilterQuery(ALL_TEAM_FILTERS)).toEqual({})
    expect(teamFilterQuery({ role: "recruiter", clientId: 7 })).toEqual({
      role: "recruiter",
      client_id: 7,
    })
    expect(teamFilterQuery({ role: "all", clientId: 7 })).toEqual({ client_id: 7 })
  })

  it("names the filter for the heading", () => {
    expect(describeTeamFilters({ role: "recruiter", clientId: 7, clientName: "Nordea" })).toBe(
      "Rekruterzy · Nordea",
    )
    expect(describeTeamFilters({ role: "all", clientId: 7, clientName: "Nordea" })).toBe("Nordea")
    expect(describeTeamFilters(ALL_TEAM_FILTERS)).toBe("")
  })

  it("restores a stored choice and refuses a broken one", () => {
    expect(
      parseStoredTeamFilters(
        JSON.stringify({ role: "delivery_lead", clientId: 3, clientName: "Orlen" }),
      ),
    ).toEqual({ role: "delivery_lead", clientId: 3, clientName: "Orlen" })
    // Nieznana rola, zepsuty JSON i dziwny klient nie mogą przejść do zapytania.
    expect(parseStoredTeamFilters(JSON.stringify({ role: "sourcer" }))).toBeNull()
    expect(parseStoredTeamFilters("{")).toBeNull()
    expect(parseStoredTeamFilters(null)).toBeNull()
    expect(
      parseStoredTeamFilters(JSON.stringify({ role: "recruiter", clientId: -1, clientName: "x" })),
    ).toEqual({ role: "recruiter", clientId: null, clientName: null })
  })
})
