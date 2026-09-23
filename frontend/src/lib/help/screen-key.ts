/**
 * Adres → klucz przewodnika ekranu Jarvisa (`backend/app/data/screen_guides`).
 *
 * Czysta funkcja (bez Reacta), więc stare `?tab=` rekrutacji i kontraktów
 * trafiają we właściwy klucz tak samo jak w samych ekranach — reużywa ich
 * parserów zamiast powtarzać reguły. Lista kluczy jest lustrem
 * `SCREEN_KEYS` w backendzie (pilnuje `screen-key.test.ts`).
 */

import { resolveContractsView } from "@/lib/clients-workspace";
import { readJobDetailUrlState } from "@/lib/job-detail-routing";

export const SCREEN_KEYS = [
  "jobs.list",
  "jobs.board",
  "jobs.proposals",
  "jobs.person",
  "job.champion",
  "candidates.list",
  "candidate.profile",
  "calendar",
  "client.orders",
  "contracts.order_mail",
  "contracts.b2b_generator",
  "finance",
] as const;

export type ScreenKey = (typeof SCREEN_KEYS)[number];

const RECORD = /^\/(jobs|candidates|clients)\/(\d+)\/?$/;

export function screenKeyFor(pathname: string | null | undefined, search?: string | null): ScreenKey | null {
  const path = (pathname || "/").replace(/\/+$/, "") || "/";
  const params = new URLSearchParams(search ? (search.startsWith("?") ? search.slice(1) : search) : "");

  if (path === "/jobs") return "jobs.list";
  if (path === "/candidates" || path === "/talent-radar") return "candidates.list";
  if (path === "/calendar") return "calendar";
  if (path === "/finance") return "finance";
  if (path === "/contracts/b2b-generator") return "contracts.b2b_generator";
  if (path === "/contracts") {
    return resolveContractsView(params.get("view")) === "order-mail" ? "contracts.order_mail" : null;
  }

  const record = RECORD.exec(path);
  if (!record) return null;
  const [, kind] = record;
  if (kind === "candidates") return "candidate.profile";
  if (kind === "clients") return params.get("tab") === "zamowienia" ? "client.orders" : null;

  // /jobs/{id}: ta sama reguła co strona rekrutacji (stare ?tab= w cenie).
  const state = readJobDetailUrlState(params);
  if (state.view === "champion") return "job.champion";
  if (params.get("candidate")) return "jobs.person";
  if (state.view === "people" && (state.segment === "proposals" || state.segment === "shortlist")) {
    return "jobs.proposals";
  }
  return "jobs.board";
}
