/**
 * Authenticated open/download for order (PO) documents.
 *
 * Ten sam plik co PO zamówienia (``ClientOrder.file_path``), pobierany istniejącym
 * ``GET /api/clients/{clientId}/orders/{orderId}/file`` (Bearer JWT). Bezpośrednie
 * otwarcie URL-a w nowej karcie nie wysyła nagłówka Authorization (token żyje w
 * localStorage, nie w cookie) → 401. Dlatego pobieramy bajty z tokenem i dajemy
 * przeglądarce same-origin blob URL. Wzorzec jak ``contract-documents.ts``.
 */

import { getAccessToken } from "./session";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface OrderDocumentRef {
  order_id: number;
  client_id: number;
  filename: string | null;
  content_type: string | null;
}

export async function fetchOrderDocumentBlob(
  clientId: number,
  orderId: number,
): Promise<Blob> {
  const token = getAccessToken();
  const res = await fetch(
    `${API_BASE}/api/clients/${clientId}/orders/${orderId}/file`,
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

/** Otwórz PO inline w nowej karcie (PDF/obraz renderują się; DOCX pobierze). */
export async function openOrderDocument(doc: OrderDocumentRef): Promise<void> {
  // Otwórz kartę SYNCHRONICZNIE w geście kliknięcia (przed pierwszym await),
  // żeby ominąć popup-blocker; po pobraniu bajtów wskaż ją na blob URL.
  const win = typeof window !== "undefined" ? window.open("", "_blank") : null;
  try {
    const raw = await fetchOrderDocumentBlob(doc.client_id, doc.order_id);
    const blob = doc.content_type
      ? new Blob([raw], { type: doc.content_type })
      : raw;
    const url = URL.createObjectURL(blob);
    const name = doc.filename || `zamowienie-${doc.order_id}.pdf`;
    if (win) {
      win.location.href = url;
    } else {
      triggerDownload(url, name);
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (e) {
    if (win) win.close();
    throw e;
  }
}

/** Pobierz PO na dysk. */
export async function downloadOrderDocument(
  doc: OrderDocumentRef,
): Promise<void> {
  const blob = await fetchOrderDocumentBlob(doc.client_id, doc.order_id);
  const url = URL.createObjectURL(blob);
  triggerDownload(url, doc.filename || `zamowienie-${doc.order_id}.pdf`);
  // Odroczony revoke — natychmiastowy po click() bywa wyścigiem (przeglądarka
  // może jeszcze nie zacząć czytać bloba), analogicznie do openOrderDocument.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
