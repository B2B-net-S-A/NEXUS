/**
 * Authenticated fetch → same-origin blob URL for backend file endpoints.
 *
 * Backend file endpoints (email attachments, CV snapshots, contract/candidate
 * documents…) are guarded by a Bearer JWT held in `localStorage` — NOT a cookie.
 * A raw `<a href>` / `<iframe src>` pointing straight at the backend therefore
 * sends NO `Authorization` header, so the backend answers
 * `401 {"detail":"Not authenticated"}` and the user sees a white page or an empty
 * preview. We instead fetch the bytes with the token attached and hand the
 * browser a same-origin blob URL.
 *
 * Native `fetch` (nie axios): axios `responseType: "blob"` cross-origin zwracał
 * status 0 na prod — patrz `FilePreviewModal.fetchDocumentBlob` (2026-05-25).
 * Ten moduł uogólnia ten sam wzorzec (był powielony w `FilePreviewModal` i
 * `contract-documents`) na dowolny endpoint plikowy backendu.
 */

import { getAccessToken } from "./session";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Fetch a backend file as a Blob with the Bearer JWT attached.
 *
 * `path` is relative to the API base (e.g. `/api/emails/1/attachments/2/download`)
 * or an absolute `http(s)://` URL.
 */
export async function fetchAuthenticatedBlob(path: string): Promise<Blob> {
  const token = getAccessToken();
  const url = /^https?:\/\//i.test(path) ? path : `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

export interface AuthenticatedDownload {
  blob: Blob;
  filename: string | null;
}

/**
 * POST JSON to a protected backend endpoint and return the generated file.
 * Native fetch is intentional; see the cross-origin axios caveat above.
 */
export async function postAuthenticatedDownload(
  path: string,
  payload: unknown,
): Promise<AuthenticatedDownload> {
  const token = getAccessToken();
  const url = /^https?:\/\//i.test(path) ? path : `${API_BASE}${path}`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `HTTP ${res.status}`);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  return {
    blob: await res.blob(),
    filename: encoded ? decodeURIComponent(encoded) : plain ?? null,
  };
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

/**
 * Open a backend file/HTML endpoint inline in a NEW TAB, with auth. Replaces
 * `window.open(rawBackendUrl)` — which sends no `Authorization` header and lands
 * on a white "Not authenticated" page. Used for printable HTML views
 * (`render-pdf` endpoints with an embedded `window.print()`) and inline PDFs.
 *
 * The tab is opened SYNCHRONOUSLY inside the click gesture (before the first
 * `await`) so the popup blocker doesn't kill it; once the bytes arrive we point
 * it at a same-origin blob URL. Pass `contentType` to force the MIME (e.g.
 * `"text/html"` so a print view renders + auto-prints instead of downloading).
 * Falls back to a download if the popup was blocked. Throws on fetch error so
 * the caller can surface a message.
 */
export async function openAuthenticatedFile(
  path: string,
  contentType?: string | null,
  fallbackFilename = "document",
): Promise<void> {
  const win = typeof window !== "undefined" ? window.open("", "_blank") : null;
  try {
    const raw = await fetchAuthenticatedBlob(path);
    const blob = contentType ? new Blob([raw], { type: contentType }) : raw;
    const url = URL.createObjectURL(blob);
    if (win) win.location.href = url;
    else downloadBlob(blob, fallbackFilename);
    // The new tab still reads the blob — revoke after a grace period.
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (e) {
    if (win) win.close();
    throw e;
  }
}
