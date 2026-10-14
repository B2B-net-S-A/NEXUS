/**
 * Przekazanie Delivery Leadowi ze stopki edytora CV (decyzja D6 Artura,
 * 14.10.2026, „Droga rekrutera do DL”).
 *
 * Gdy karta stoi na „Zweryfikowany”, edytor CV ma w stopce pole „Uwaga dla
 * Delivery Leada”, linię stanu QC, „Zapisz” i „Zapisz i przekaż do DL →”.
 * Zapis jest ten sam co „Zapisz” (szkic, pola w nawiasach, zatwierdzenie
 * w tle), potem ruch karty na „QC CV” (`usePipelineMoveCore` u wołającego).
 * Wejście do „QC CV” nie ma bramki QC na serwerze — gdy QC ma jeszcze
 * blokady, przycisk zmienia się w „Przekaż mimo uwag…”: obejście z powodem
 * (`QcOverrideDialog`) to sygnał dla Delivery Leada, co zostało niepoprawione.
 *
 * Tu leży sama reguła (bez Reacta), żeby test sprawdzał ją wprost.
 */

import type { QcResult } from "@/lib/api/cvQc";
import { countForm, splitChecks, taskTitle, thingsLabel } from "@/lib/cv-qc";

/** Pole „Uwaga dla Delivery Leada” — lustro `StageMove.recruiter_remark` (max 2000). */
export const HANDOFF_REMARK_MAX = 2000;

/** Prop edytora CV: bez niego edytor wygląda jak dotąd (bez stopki przekazania). */
export interface CvEditorHandoff {
  /**
   * Ruch karty na „QC CV” z uwagą dla DL (pusta = bez uwagi). Woła się PO
   * zapisie szkicu. `true` = karta przeszła; `false` = odmowa, której powód
   * pokazał już wołający (rdzeń ruchu) — edytor zostaje otwarty.
   */
  onSaveAndHandOff: (remark: string) => Promise<boolean>;
  /**
   * Tryb doradczy QC, gdy wynik QC go nie podaje (starszy serwer). Wynik QC
   * (`advisory`, `can_override`) wygrywa — serwer wie, kto może przepuścić.
   */
  advisory?: boolean;
}

/** To, co edytor wie o QC treści (licznik panelu „Do poprawy”). */
export interface HandoffQcState {
  total: number;
  blocking: number;
  state: "loading" | "ready" | "failed";
  qc?: QcResult | null;
}

export type HandoffGate =
  /** Nic nie blokuje (albo QC już przepuszczone) — zwykłe przekazanie. */
  | { kind: "ready" }
  /** QC się liczy — przekazanie czeka na wynik. */
  | { kind: "waiting" }
  /** Blokady QC: przekazanie przez obejście z powodem. */
  | { kind: "override"; advisory: boolean; pending: string[] }
  /** Blokady QC, a ta osoba nie może przepuścić (poza trybem doradczym). */
  | { kind: "blocked" };

export interface HandoffGateOptions {
  /** Podgląd jako inny użytkownik — nikt nie przepuszcza (jak okno QC). */
  impersonating: boolean;
  /** Uprawnienie `recruitment_manage` — gdy wynik QC nie mówi `can_override`. */
  canManage: boolean;
  advisoryFallback?: boolean;
}

/**
 * Czy przekazanie idzie wprost, przez obejście, czy czeka. Awaria QC nie
 * blokuje: serwer nie bramkuje wejścia do „QC CV”, a Delivery Lead zobaczy
 * wynik QC w przeglądzie.
 */
export function handoffGate(count: HandoffQcState, options: HandoffGateOptions): HandoffGate {
  if (count.state === "loading") return { kind: "waiting" };
  const qc = count.qc ?? null;
  if (count.state !== "ready" || !qc) return { kind: "ready" };
  const cleared = qc.passed || qc.override != null;
  if (cleared || qc.blocking_failed <= 0) return { kind: "ready" };
  const canOverride = !options.impersonating && (qc.can_override ?? options.canManage);
  if (!canOverride) return { kind: "blocked" };
  return {
    kind: "override",
    advisory: qc.advisory ?? options.advisoryFallback ?? false,
    pending: splitChecks(qc.checks).tasks.map(taskTitle),
  };
}

/** Linia stanu w stopce: ile rzeczy do decyzji i czy coś blokuje wysyłkę. */
export function handoffStatus(count: HandoffQcState, gate: HandoffGate): string {
  if (gate.kind === "waiting") return "Sprawdzam CV…";
  if (count.state === "failed") return "QC nie odpowiada — Delivery Lead zobaczy wynik w przeglądzie";
  const things = count.total > 0 ? `${thingsLabel(count.total)} do decyzji` : "Nic do decyzji";
  if (gate.kind === "override" || gate.kind === "blocked") {
    const blocking = countForm(Math.max(1, count.blocking), ["blokuje", "blokują", "blokuje"]);
    return `${things} · ${blocking} wysyłkę`;
  }
  const overridden = count.qc?.override != null && !count.qc.passed && count.qc.blocking_failed > 0;
  return overridden ? `${things} · przepuszczone mimo uwag` : `${things} · nic nie blokuje wysyłki`;
}

/** Toast po udanym przekazaniu — imię, bez odmiany po rodzaju. */
export function handedOffMessage(candidateName: string, approving: boolean): string {
  const first = candidateName.trim().split(/\s+/)[0] || "Kandydat";
  return approving
    ? `${first} — przekazano Delivery Leadowi. Sprawdzamy treść CV w tle.`
    : `${first} — przekazano Delivery Leadowi.`;
}
