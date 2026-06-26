/**
 * Shared types + helpers for the B2B CV generator surfaces.
 *
 * Single source of truth for the modal (CVGeneratorV2), the standalone page
 * (CVGeneratorStandaloneV2) and the B2B contract generator — previously each
 * kept its own copy of these utilities and they had already started to drift.
 */

export type RecruitmentOption = {
  stage_id: number;
  job_id: number;
  job_title: string;
  stage: string;
  has_champion: boolean;
  has_notes: boolean;
  has_cv: boolean;
  ready: boolean;
};

export const STAGE_LABELS: Record<string, string> = {
  new: "Nowy",
  contacted: "Kontakt",
  screening: "Screening",
  verified: "Zweryfikowany",
  interview: "Interview",
  client_review: "U klienta",
  cv_sent: "CV wysłane",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  active: "Aktywny",
  hired: "Zatrudniony",
  rejected: "Odrzucony",
  withdrawn: "Rezygnacja",
  on_hold: "Wstrzymany",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

export function parseDispositionFilename(
  disposition: string,
  fallback: string,
): string {
  // Prefer the RFC 5987 `filename*=UTF-8''<percent-encoded>` parameter — it
  // carries the real name including Polish characters (ł, ą, ż…). Fall back to
  // the ASCII `filename="…"` for responses that don't set the extended form.
  const extended = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (extended) {
    try {
      return decodeURIComponent(extended[1]);
    } catch {
      // Malformed percent-encoding — fall through to the plain parameter.
    }
  }
  const match = disposition.match(/filename="?([^";]+)"?/);
  return match ? match[1] : fallback;
}

export function parseWarningsHeader(header: unknown): string[] {
  if (typeof header !== "string") return [];
  try {
    const parsed = JSON.parse(header);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function extractErrorDetail(err: unknown): Promise<string> {
  if (typeof err !== "object" || err === null) return "";
  const anyErr = err as { response?: { data?: unknown } };
  const data = anyErr.response?.data;
  // With responseType: "blob" axios delivers error bodies as a Blob too, so the
  // backend's JSON {detail} must be read out of the Blob before it can surface.
  if (data instanceof Blob) {
    try {
      const txt = await data.text();
      const parsed = JSON.parse(txt);
      if (typeof parsed?.detail === "string") return parsed.detail;
      return txt;
    } catch {
      return "";
    }
  }
  if (typeof data === "string") return data;
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return "";
}
