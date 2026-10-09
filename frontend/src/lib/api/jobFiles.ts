/**
 * Pliki rekrutacji (0427, 09.10.2026) — lustro `/api/jobs/{id}/files`
 * i `/api/job-intake/forms/{id}/files`.
 *
 * Delivery Lead dokłada pliki przy zakładaniu rekrutacji; do „Utwórz
 * i przekaż” wiszą na niedokończonym formularzu, a serwer przepina je na
 * rekrutację w transakcji tworzenia. Na stronie rekrutacji stoją w menu „⋯” →
 * „Pliki”. Oba miejsca mówią tym samym kształtem, więc mają jednego klienta.
 */
import api from "@/lib/api";
import { getAuthenticatedRequestHeaders } from "@/lib/session";

export type JobFileSource = "request" | "upload";

export interface JobFileItem {
  id: number;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  /** `request` = plik requestu klienta z kroku 1, `upload` = dodany ręcznie. */
  source: JobFileSource;
  uploaded_by: number | null;
  uploaded_by_name: string | null;
  created_at: string;
}

export interface JobFilesResponse {
  items: JobFileItem[];
  /** Tylko pliki rekrutacji: czy ta osoba może dodawać i usuwać. */
  can_edit?: boolean;
  max_files: number;
  max_file_bytes: number;
}

/** Czyje pliki: rekrutacji albo niedokończonego formularza „Nowa rekrutacja”. */
export type JobFilesOwner = { kind: "job"; id: number } | { kind: "form"; id: number };

/** Lustro `job_files.CONTENT_TYPES` na serwerze — serwer i tak sprawdza sam. */
export const JOB_FILE_EXTENSIONS = [
  ".pdf",
  ".doc",
  ".docx",
  ".xls",
  ".xlsx",
  ".ppt",
  ".pptx",
  ".txt",
  ".csv",
  ".png",
  ".jpg",
  ".jpeg",
  ".eml",
  ".msg",
] as const;
export const JOB_FILE_ACCEPT = JOB_FILE_EXTENSIONS.join(",");
export const JOB_FILE_MAX_BYTES = 20 * 1024 * 1024;
export const JOB_FILES_MAX = 20;
export const JOB_FILE_TYPES_TEXT =
  "PDF, Word, Excel, PowerPoint, TXT, CSV, PNG, JPG albo wiadomość (EML, MSG)";

const basePath = (owner: JobFilesOwner) =>
  owner.kind === "job"
    ? `/api/jobs/${owner.id}/files`
    : `/api/job-intake/forms/${owner.id}/files`;

export const jobFilesKey = (owner: JobFilesOwner) =>
  ["job-files", owner.kind, owner.id] as const;

export async function fetchJobFiles(owner: JobFilesOwner): Promise<JobFilesResponse> {
  const { data } = await api.get<JobFilesResponse>(basePath(owner));
  return { ...data, items: Array.isArray(data?.items) ? data.items : [] };
}

export async function uploadJobFile(
  owner: JobFilesOwner,
  file: File,
  source: JobFileSource = "upload",
): Promise<JobFileItem> {
  const body = new FormData();
  body.append("file", file);
  if (owner.kind === "form") body.append("source", source);
  const { data } = await api.post<JobFileItem>(basePath(owner), body, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120_000,
  });
  return data;
}

export async function deleteJobFile(owner: JobFilesOwner, fileId: number): Promise<void> {
  await api.delete(`${basePath(owner)}/${fileId}`);
}

/**
 * Treść pliku. Natywny `fetch`, nie axios — `responseType: blob` między
 * domenami zwracał status 0 (jak w `fetchDocumentBlob` podglądu CV).
 */
export async function fetchJobFileBlob(
  owner: JobFilesOwner,
  fileId: number,
  disposition: "attachment" | "inline" = "attachment",
): Promise<Blob> {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
  const res = await fetch(
    `${apiBase}${basePath(owner)}/${fileId}/content?disposition=${disposition}`,
    { method: "GET", headers: getAuthenticatedRequestHeaders() },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.blob();
}

export async function downloadJobFile(
  owner: JobFilesOwner,
  file: Pick<JobFileItem, "id" | "filename">,
): Promise<void> {
  const blob = await fetchJobFileBlob(owner, file.id, "attachment");
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.filename || `plik-${file.id}`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

/** Czy plik da się obejrzeć w oknie podglądu (PDF, Word, obraz). */
export function jobFilePreviewable(file: Pick<JobFileItem, "filename">): boolean {
  return [".pdf", ".docx", ".png", ".jpg", ".jpeg"].includes(extensionOf(file.filename));
}

/**
 * Powód, dla którego pliku nie da się dodać — to samo, co powie serwer, ale
 * przed wysłaniem 20 MB. `null` = można wysyłać.
 */
export function jobFileRefusal(file: Pick<File, "name" | "size">): string | null {
  if (!(JOB_FILE_EXTENSIONS as readonly string[]).includes(extensionOf(file.name)))
    return `„${file.name}”: tego typu pliku nie da się dodać. Dozwolone: ${JOB_FILE_TYPES_TEXT}.`;
  if (file.size === 0) return `„${file.name}”: plik jest pusty.`;
  if (file.size > JOB_FILE_MAX_BYTES)
    return `„${file.name}”: plik jest za duży — najwyżej ${JOB_FILE_MAX_BYTES / (1024 * 1024)} MB.`;
  return null;
}
