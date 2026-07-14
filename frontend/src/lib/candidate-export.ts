import api from "@/lib/api";
import {
  filtersToApiCriteria,
  type CandidateFilters,
} from "@/lib/url-filters";

export type CandidateExportFormat = "csv" | "xlsx";
export type CandidateExportScope = "filtered" | "selected";

export interface CandidateExportRequest {
  format: CandidateExportFormat;
  scope: CandidateExportScope;
  filters: Record<string, unknown>;
  candidate_ids: number[];
  limit: number;
}

export function buildCandidateExportRequest(
  filters: CandidateFilters,
  format: CandidateExportFormat,
  scope: CandidateExportScope,
  selectedIds: Iterable<number> = [],
): CandidateExportRequest {
  const normalizedFilters = filtersToApiCriteria(filters);
  return {
    format,
    scope,
    filters: scope === "filtered" ? normalizedFilters : {},
    candidate_ids:
      scope === "selected" ? Array.from(new Set(selectedIds)) : [],
    limit: 100_000,
  };
}

function filenameFromDisposition(
  disposition: string | undefined,
  fallback: string,
): string {
  if (!disposition) return fallback;
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) return decodeURIComponent(encoded);
  return disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? fallback;
}

export async function downloadCandidateExport(
  request: CandidateExportRequest,
): Promise<void> {
  const response = await api.post<Blob>("/api/candidates/export", request, {
    responseType: "blob",
  });
  const fallback = `kandydaci-${new Date().toISOString().slice(0, 10)}.${request.format}`;
  const filename = filenameFromDisposition(
    response.headers["content-disposition"],
    fallback,
  );
  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
