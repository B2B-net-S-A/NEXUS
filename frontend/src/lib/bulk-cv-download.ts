export interface BulkCvDownloadResult {
  includedCount: number;
  skippedCount: number;
}

export class BulkCvDownloadError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "BulkCvDownloadError";
    this.status = status;
  }
}

function messageForStatus(status: number): string {
  if (status === 401 || status === 403) {
    return "Brak uprawnień do pobrania CV.";
  }
  if (status === 422 || status === 400) {
    return "Za dużo zaznaczonych kandydatów (max 200) lub lista jest pusta.";
  }
  if (status === 429) {
    return "Zbyt wiele pobrań w krótkim czasie — spróbuj ponownie za chwilę.";
  }
  return "Nie udało się pobrać CV. Spróbuj ponownie.";
}

export async function downloadBulkCvs(
  candidateIds: number[]
): Promise<BulkCvDownloadResult> {
  if (candidateIds.length === 0) {
    throw new BulkCvDownloadError("Nie wybrano kandydatów.", 400);
  }

  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "";
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  const res = await fetch(`${apiBase}/api/candidates/bulk-cv-download`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ candidate_ids: candidateIds }),
  });

  if (!res.ok) {
    throw new BulkCvDownloadError(messageForStatus(res.status), res.status);
  }

  const includedCount = Number(res.headers.get("X-Included-Count") ?? "0");
  const skippedCount = Number(res.headers.get("X-Skipped-Count") ?? "0");

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const today = new Date().toISOString().slice(0, 10);
  const a = document.createElement("a");
  a.href = url;
  a.download = `nexus-cvs-${today}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);

  return { includedCount, skippedCount };
}
