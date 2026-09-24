/**
 * Pobieranie wygenerowanego CV. Przy braku wymaganej zgody RODO serwer
 * odpowiada 409 `consent_required` z polskim komunikatem — oddajemy go
 * wołającemu, który pokazuje go w toaście zamiast ogólnego „nie udało się”.
 */

import api, { type GeneratedCvItem } from "@/lib/api";
import { downloadBlob, extractErrorDetail } from "@/lib/cv-generator";

import { htmlFilename } from "./cv-generator-form";

type DownloadTarget = Pick<GeneratedCvItem, "id" | "filename" | "approved_version_id">;

function fileUrl(item: DownloadTarget, format: "docx" | "html"): string {
  return item.approved_version_id
    ? `/api/cv-generator/generated/${item.id}/approved/${item.approved_version_id}/${format}`
    : `/api/cv-generator/generated/${item.id}/${format}`;
}

/** Pobiera DOCX; zwraca komunikat błędu albo `null` po sukcesie. */
export async function downloadGeneratedCv(
  item: DownloadTarget,
  format: "docx" | "html" = "docx",
): Promise<string | null> {
  try {
    const res = await api.get(fileUrl(item, format), { responseType: "blob" });
    downloadBlob(res.data as Blob, format === "html" ? htmlFilename(item.filename) : item.filename);
    return null;
  } catch (err) {
    return (
      (await extractErrorDetail(err)) ||
      (format === "html" ? "Nie udało się pobrać pliku HTML." : "Nie udało się pobrać CV.")
    );
  }
}
