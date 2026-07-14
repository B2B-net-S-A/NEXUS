import type { GenerateJobOutput } from "@/lib/api";

export type MindyHistoryMessage = {
  role: "user" | "assistant";
  content: string;
};

export function hourlyPlnSalaryFields(
  salary: GenerateJobOutput["salary"],
): { min: string; max: string } | null {
  if (!salary || salary.period !== "hour" || salary.currency !== "PLN") return null;
  return {
    min: salary.min == null ? "" : String(salary.min),
    max: salary.max == null ? "" : String(salary.max),
  };
}

export function criteriaSaveState(input: {
  loading: boolean;
  saving: boolean;
  error: string | null;
  count: number;
  emptyConfirmed: boolean;
}): "blocked" | "confirm-empty" | "ready" {
  if (input.loading || input.saving || input.error) return "blocked";
  if (input.count === 0 && !input.emptyConfirmed) return "confirm-empty";
  return "ready";
}

export async function uopInputHash(text: string, language: string): Promise<string> {
  const clean = text.trim().slice(0, 6000);
  const payload = new TextEncoder().encode(`${language.toLowerCase()}:${clean}`);
  const digest = await crypto.subtle.digest("SHA-256", payload);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function normalizeMindyHistory(
  value: unknown,
  now = Date.now(),
): MindyHistoryMessage[] {
  if (!value || typeof value !== "object") return [];
  const candidate = value as { expiresAt?: unknown; messages?: unknown };
  if (typeof candidate.expiresAt !== "number" || candidate.expiresAt <= now) return [];
  if (!Array.isArray(candidate.messages)) return [];
  return candidate.messages
    .filter(
      (message): message is MindyHistoryMessage =>
        !!message &&
        typeof message === "object" &&
        ((message as MindyHistoryMessage).role === "user" ||
          (message as MindyHistoryMessage).role === "assistant") &&
        typeof (message as MindyHistoryMessage).content === "string",
    )
    .slice(-20);
}
