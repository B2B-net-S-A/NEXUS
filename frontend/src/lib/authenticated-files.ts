/**
 * Authenticated fetch → same-origin blob URL for backend file endpoints.
 *
 * Backend file endpoints (email attachments, CV snapshots, contract/candidate
 * documents…) are guarded by the HttpOnly browser session (with a temporary
 * read-only fallback for sessions created before the rollout). A raw `<a href>`
 * / `<iframe src>` cannot reliably carry that cross-origin context, so the backend answers
 * `401 {"detail":"Not authenticated"}` and the user sees a white page or an empty
 * preview. We instead fetch the bytes with the token attached and hand the
 * browser a same-origin blob URL.
 *
 * Native `fetch` (nie axios): axios `responseType: "blob"` cross-origin zwracał
 * status 0 na prod — patrz `FilePreviewModal.fetchDocumentBlob` (2026-05-25).
 * Ten moduł uogólnia ten sam wzorzec (był powielony w `FilePreviewModal` i
 * `contract-documents`) na dowolny endpoint plikowy backendu.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Fetch a backend file as a Blob with the Bearer JWT attached.
 *
 * `path` is relative to the API base (e.g. `/api/emails/1/attachments/2/download`)
 * or an absolute `http(s)://` URL.
 */
export async function fetchAuthenticatedBlob(path: string): Promise<Blob> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const isAbsolute = /^https?:\/\//i.test(path);
  const url = isAbsolute ? path : `${API_BASE}${path}`;
  // Absolute URLs may be third-party signed links. Never forward the legacy
  // Bearer token or ambient credentials outside the configured API origin.
  const pageOrigin =
    typeof window !== "undefined" ? window.location.origin : "http://localhost";
  const isBackendOrigin =
    new URL(url, pageOrigin).origin === new URL(API_BASE, pageOrigin).origin;
  const res = await fetch(url, {
    ...(isBackendOrigin ? { credentials: "include" as const } : {}),
    headers:
      isBackendOrigin && token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

/** Trigger a browser download of an in-memory blob (programmatic `<a download>`). */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** Fetch a backend file (with auth) and download it to disk. Throws on error. */
export async function downloadAuthenticatedFile(
  path: string,
  filename: string,
): Promise<void> {
  const blob = await fetchAuthenticatedBlob(path);
  downloadBlob(blob, filename);
}

/**
 * Fetch a backend file (with auth) and return a same-origin object URL suitable
 * for inline rendering (`<iframe src>` / `<img src>`). Pass `contentType` to
 * force the MIME type — a typeless blob defaults to `octet-stream`, which the
 * browser downloads instead of rendering inline.
 *
 * The caller owns the returned URL and MUST `URL.revokeObjectURL(url)` it when
 * done (e.g. in an effect cleanup) to avoid leaking memory.
 */
export async function fetchAuthenticatedObjectUrl(
  path: string,
  contentType?: string | null,
): Promise<string> {
  const raw = await fetchAuthenticatedBlob(path);
  const blob = contentType ? new Blob([raw], { type: contentType }) : raw;
  return URL.createObjectURL(blob);
}
