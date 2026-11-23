// Ocena potencjału: czyste pomocniki widoku (testowane w sales-potential.test.tsx).

import type { Potential, PotentialVerdict } from "@/lib/api/sales-potential";

export const VERDICT_VARIANT: Record<PotentialVerdict, "neutral" | "warning" | "success"> = {
  NISKI: "neutral",
  ŚREDNI: "warning",
  WYSOKI: "success",
};

export const KIND_LABEL = {
  list: "list referencyjny",
  realizacja: "opisana realizacja",
  logo: "tylko logo",
} as const;

/** „2026-03” → „03.2026”, „2026-03-14” → „14.03.2026”. */
export function eventDate(value: string): string {
  const [year, month, day] = value.split("-");
  if (!year || !month) return value;
  return day ? `${day}.${month}.${year}` : `${month}.${year}`;
}

export function wordCount(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

export type PotentialView =
  | "off"
  | "empty"
  | "running"
  | "assessing"
  | "failed"
  | "ready";

/** Co pokazać na karcie: nic, przycisk, „bot szuka”, „piszę ocenę”, błąd albo ocenę. */
export function potentialView(data: Potential | undefined): PotentialView {
  if (!data || !data.enabled) return "off";
  const { run, result } = data;
  const newerRun = run && result && new Date(run.started_at) > new Date(result.created_at);
  if (run?.status === "started" && (!result || newerRun)) return "running";
  if (!result) return run?.status === "failed" || run?.status === "expired" ? "failed" : "empty";
  if (result.state === "pending") return "assessing";
  if (result.state === "failed" && !result.assessment) return "failed";
  return "ready";
}

export const FAILURE_TEXT: Record<string, string> = {
  no_knowledge: "Baza wiedzy jest pusta, więc ocena nie powstała. Uzupełnij ją w Sprzedaż → Leady → Boty → Baza wiedzy.",
  no_model: "Model oceny nie jest podłączony. Daj znać administratorowi.",
  model: "Model nie napisał oceny. Research zostaje poniżej; spróbuj odświeżyć.",
};

export function failureText(data: Potential | undefined): string {
  const error = data?.result?.error;
  if (error && FAILURE_TEXT[error]) return FAILURE_TEXT[error];
  if (!data?.result && data?.run) return "Bot nie odesłał researchu. Spróbuj ponownie za chwilę.";
  return "Ocena się nie udała. Spróbuj odświeżyć.";
}
