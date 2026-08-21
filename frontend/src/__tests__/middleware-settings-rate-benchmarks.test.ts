/**
 * `/settings/rate-benchmarks` — bramka routingu.
 *
 * Kafelek „Stawki rynkowe" w Ustawieniach → Zaawansowane deklaruje
 * `["admin", "delivery_lead"]`, a strona wpuszcza wyłącznie admina (jak zapisy
 * w backendzie: `AdminUser` na POST/PATCH/DELETE/import). Dopóki trasa nie
 * miała wpisu w middleware, Delivery Lead klikający własny kafelek dostawał
 * powłokę aplikacji z PUSTYM obszarem treści — stan nieodróżnialny od zwiechy,
 * zgłaszany jako „aplikacja się wysypała", a nie „nie mam uprawnień".
 *
 * Regresja byłaby cicha (nic nie pada, ekran po prostu znów robi się biały),
 * stąd osobny test.
 */
import { describe, expect, it } from "vitest"
import { NextRequest } from "next/server"

import { middleware } from "@/middleware"

const BASE = "https://nexus.dynaminds.pl"
const HOUR = 3600
const now = () => Math.floor(Date.now() / 1000)

function makeToken(payload: Record<string, unknown>): string {
  const b64url = (o: unknown) =>
    Buffer.from(JSON.stringify(o))
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "")
  // Podpis nieistotny — middleware go nie weryfikuje (edge runtime).
  return `${b64url({ alg: "HS256", typ: "JWT" })}.${b64url(payload)}.sig`
}

const token = (role: string) =>
  makeToken({ role, roles: [role], exp: now() + HOUR })

/** Dokąd middleware kieruje: "pass" = przepuszcza, inaczej ścieżka docelowa. */
function destination(pathname: string, jwt?: string): string {
  const res = middleware(
    new NextRequest(new URL(pathname, BASE), {
      headers: jwt ? { cookie: `nexus_access=${jwt}` } : {},
    }),
  )
  const location = res.headers.get("location")
  if (!location) return "pass"
  return new URL(location).pathname
}

describe("middleware — /settings/rate-benchmarks", () => {
  it("wpuszcza admina", () => {
    expect(destination("/settings/rate-benchmarks", token("admin"))).toBe("pass")
  })

  it("odbija Delivery Leada na /403, a nie na pusty ekran", () => {
    expect(destination("/settings/rate-benchmarks", token("delivery_lead"))).toBe(
      "/403",
    )
  })

  it("odbija pozostałe role operacyjne", () => {
    for (const role of ["recruiter", "tac", "finance", "head_of_recruitment"]) {
      expect(destination("/settings/rate-benchmarks", token(role)), role).toBe(
        "/403",
      )
    }
  })

  it("bez tokenu kieruje na /login z parametrem powrotu", () => {
    expect(destination("/settings/rate-benchmarks")).toBe("/login")
  })
})
