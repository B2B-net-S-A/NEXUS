/**
 * Authenticated open/download for contract documents.
 *
 * The backend endpoint `/api/contracts/{id}/documents/{docId}/download` is guarded
 * by a Bearer JWT. Opening that URL directly in a new tab (`<a target="_blank">`)
 * sends NO Authorization header — the token lives in localStorage, not a cookie —
 * so the backend answers 401 {"detail":"Not authenticated"} and the user just sees
 * a white page with that JSON. We instead fetch the bytes with the token attached
 * and hand the browser a same-origin blob URL.
 *
 * Native `fetch` (nie axios): axios `responseType: "blob"` cross-origin zwracał
 * status 0 na prod — patrz `FilePreviewModal.fetchDocumentBlob` (2026-05-25).
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface DownloadableDocument {
  id: number;
  filename: string;
  content_type?: string | null;
}

export async function fetchContractDocumentBlob(
  contractId: number,
  documentId: number,
): Promise<Blob> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const res = await fetch(
    `${API_BASE}/api/contracts/${contractId}/documents/${documentId}/download`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

function triggerDownload(url: string, filename: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/**
 * Open a contract document inline in a new tab. PDF/obraz renderują się w
 * przeglądarce; DOCX (którego przeglądarka nie renderuje inline) zostanie pobrany.
 * Rzuca przy błędzie — caller pokazuje komunikat.
 */
export async function openContractDocument(
  contractId: number,
  doc: DownloadableDocument,
): Promise<void> {
  // Otwórz kartę SYNCHRONICZNIE w geście kliknięcia (przed pierwszym await),
  // żeby ominąć popup-blocker; po pobraniu bajtów wskaż ją na blob URL.
  const win = typeof window !== "undefined" ? window.open("", "_blank") : null;
  try {
    const raw = await fetchContractDocumentBlob(contractId, doc.id);
    // Wymuś poprawny MIME — Blob bez typu (octet-stream) wymusiłby download
    // zamiast inline renderu PDF/obrazu.
    const blob = doc.content_type
      ? new Blob([raw], { type: doc.content_type })
      : raw;
    const url = URL.createObjectURL(blob);
    if (win) {
      win.location.href = url;
    } else {
      // Popup zablokowany — pobierz zamiast otwierać.
      triggerDownload(url, doc.filename);
    }
    // Nowa karta wciąż czyta blob — zwolnij dopiero po chwili.
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (e) {
    if (win) win.close();
    throw e;
  }
}

/** Download a contract document to disk (programmatic `<a download>`). */
export async function downloadContractDocument(
  contractId: number,
  doc: DownloadableDocument,
): Promise<void> {
  const blob = await fetchContractDocumentBlob(contractId, doc.id);
  const url = URL.createObjectURL(blob);
  triggerDownload(url, doc.filename);
  URL.revokeObjectURL(url);
}
