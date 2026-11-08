import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { LoadPanel, p0ByPerson } from "@/components/v2/request-board/LoadPanel"
import type { BoardRequest, LoadPerson } from "@/lib/api/requestAllocation"

// Liczba P0 w „Obłożeniu” (prośba Olafa, 06.11.2026): czerwona plakietka
// i najwięcej P0 na górze. Dane fikcyjne.

const TODAY = "2026-11-06"

function person(user_id: number, name: string, count: number, jobIds: number[]): LoadPerson {
  return {
    user_id,
    name,
    count,
    leave_until: null,
    requests: jobIds.map((job_id) => ({
      job_id,
      title: `Rekrutacja ${job_id}`,
      client_name: null,
      deadline: null,
      proposed: false,
    })),
  }
}

function request(job_id: number, people: { user_id: number; proposed?: boolean }[], p0: boolean): BoardRequest {
  return {
    job_id,
    title: `Rekrutacja ${job_id}`,
    client_name: null,
    category_id: 1,
    deadline: null,
    sent: 0,
    champion: false,
    people: people.map((p) => ({
      user_id: p.user_id,
      name: `Osoba ${p.user_id}`,
      proposed: p.proposed ?? false,
      source: "manual" as const,
    })),
    is_p0: p0,
    // Termin minął — P0 po terminie dalej się liczy (trwa do decyzji).
    p0_until: p0 ? "2026-11-06T08:00:00Z" : null,
  }
}

const load = [
  person(1, "Anna Przykładowa", 5, [10, 11]),
  person(2, "Bartek Testowy", 3, [12, 13]),
  person(3, "Celina Wzorcowa", 4, [14]),
]

const requests = [
  request(10, [{ user_id: 1 }], false),
  request(12, [{ user_id: 2 }, { user_id: 3, proposed: true }], true),
  request(13, [{ user_id: 2 }], true),
  request(14, [{ user_id: 3 }], true),
]

describe("p0ByPerson", () => {
  it("liczy P0, w których osoba pracuje, bez propozycji automatu", () => {
    const map = p0ByPerson(requests)
    expect(map.get(2)).toEqual([12, 13])
    expect(map.get(3)).toEqual([14])
    expect(map.has(1)).toBe(false)
  })

  it("bez danych tablicy — pusto", () => {
    expect(p0ByPerson(undefined).size).toBe(0)
  })
})

describe("LoadPanel z P0", () => {
  it("plakietka z liczbą P0 i najwięcej P0 na górze", () => {
    render(<LoadPanel load={load} today={TODAY} requests={requests} />)
    const rows = screen.getAllByRole("button", { expanded: false })
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Bartek Testowy"),
      expect.stringContaining("Celina Wzorcowa"),
      expect.stringContaining("Anna Przykładowa"),
    ])
    expect(within(rows[0]).getByTestId("load-p0")).toHaveTextContent("2")
    expect(within(rows[1]).getByTestId("load-p0")).toHaveTextContent("1")
    expect(within(rows[2]).queryByTestId("load-p0")).toBeNull()
  })

  it("bez P0 kolejność obłożenia zostaje", () => {
    render(<LoadPanel load={load} today={TODAY} requests={[]} />)
    const names = screen.getAllByRole("button", { expanded: false }).map((row) => row.textContent)
    expect(names[0]).toContain("Anna Przykładowa")
    expect(screen.queryByTestId("load-p0")).toBeNull()
  })

  it("rozwinięta osoba: rekrutacje P0 ze znacznikiem", async () => {
    render(<LoadPanel load={load} today={TODAY} requests={requests} />)
    await userEvent.click(screen.getByRole("button", { name: /Bartek Testowy/ }))
    expect(screen.getByRole("link", { name: /Rekrutacja 12/ })).toHaveTextContent("P0")
  })
})
