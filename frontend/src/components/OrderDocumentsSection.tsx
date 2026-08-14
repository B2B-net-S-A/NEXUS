"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList, Download, ExternalLink, Loader2 } from "lucide-react";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { OrderDocumentItem } from "@/lib/api/dlPortal";
import { downloadOrderDocument, openOrderDocument } from "@/lib/order-documents";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { formatDate } from "@/lib/utils";

function formatBytes(n: number | null | undefined): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props {
  contractId?: number;
  candidateId?: number;
}

/**
 * Read-only sekcja „Dokumenty zamówień" — pliki PO zamówień (ten sam plik co w
 * zakładce Zamówienia, `ClientOrder.file_path`, bez kopii). Widoczna w
 * Dokumentach kontraktu (`contractId`) oraz w Plikach osoby (`candidateId`).
 * Renderuje się tylko gdy są pliki; pusty wynik lub 403 (brak dostępu do
 * klienta — PO są poufne) → nic nie pokazujemy.
 */
export function OrderDocumentsSection({ contractId, candidateId }: Props) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string>("");

  const { data, error: queryError, refetch } = useQuery<OrderDocumentItem[]>({
    queryKey: ["order-documents", contractId ?? null, candidateId ?? null],
    queryFn: async () => {
      if (contractId != null) {
        return dlPortalApi
          .listContractOrderDocuments(contractId)
          .then((r) => r.data.documents);
      }
      if (candidateId != null) {
        return dlPortalApi
          .listCandidateOrderDocuments(candidateId)
          .then((r) => r.data.documents);
      }
      return [];
    },
    enabled: contractId != null || candidateId != null,
    retry: false, // 403 (brak dostępu do klienta) → nie ponawiaj, po prostu ukryj
  });

  const status = (queryError as { response?: { status?: number } } | null)?.response
    ?.status;
  // 403 = ta rola nie ma dostępu do zamówień klienta (PO zawiera stawki) —
  // sekcja po prostu nie istnieje dla niej i ciche ukrycie jest poprawne.
  // Każda INNA awaria musi być widoczna: `return null` na 500 kasowałby całą
  // sekcję dokumentów bez śladu, co czyta się jak „plików nie ma".
  if (queryError && status !== 403) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać dokumentów zamówień."
        onRetry={() => refetch()}
      />
    );
  }

  const docs = data ?? [];
  if (docs.length === 0) return null;

  const handleOpen = async (d: OrderDocumentItem) => {
    setBusyId(d.order_id);
    setError("");
    try {
      await openOrderDocument(d);
    } catch {
      setError(`Nie udało się otworzyć pliku zamówienia „${d.title}".`);
    } finally {
      setBusyId(null);
    }
  };

  const handleDownload = async (d: OrderDocumentItem) => {
    setBusyId(d.order_id);
    setError("");
    try {
      await downloadOrderDocument(d);
    } catch {
      setError(`Nie udało się pobrać pliku zamówienia „${d.title}".`);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="bg-card dark:bg-muted rounded-2xl shadow-xs overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <ClipboardList className="w-4 h-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">Dokumenty zamówień</h3>
        <span className="text-xs text-muted-foreground">
          (PDF-y przypięte do zamówień)
        </span>
      </div>
      {error && <div className="text-sm text-destructive px-4 py-2">{error}</div>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted dark:bg-muted/40 text-xs uppercase text-muted-foreground">
            <tr>
              <th className="text-left px-4 py-2">Zamówienie</th>
              <th className="text-left px-4 py-2">Plik</th>
              {/* Kolumna „Typ" istnieje, żeby wiersz czytał się jak dokument
                  kontraktu określonego rodzaju — tak samo jak w głównej tabeli
                  Dokumentów wyżej. Wartość jest stała z definicji: sekcja
                  listuje wyłącznie pliki zamówień, więc nie potrzebuje pola
                  z serwera. */}
              <th className="text-left px-4 py-2">Typ</th>
              <th className="text-left px-4 py-2">Rozmiar</th>
              <th className="text-left px-4 py-2">Dodano</th>
              <th className="text-right px-4 py-2">Akcje</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.order_id} className="border-t border-border">
                <td className="px-4 py-2">
                  <button
                    type="button"
                    onClick={() => handleOpen(d)}
                    disabled={busyId === d.order_id}
                    className="text-primary hover:underline text-left disabled:opacity-60"
                    title="Otwórz"
                  >
                    {d.title}
                  </button>
                </td>
                <td className="px-4 py-2 text-muted-foreground truncate max-w-[16rem]">
                  {d.filename ?? "—"}
                </td>
                <td className="px-4 py-2">Zamówienie</td>
                <td className="px-4 py-2 text-muted-foreground">
                  {formatBytes(d.size_bytes)}
                </td>
                <td className="px-4 py-2 text-xs text-muted-foreground">
                  {formatDate(d.uploaded_at ?? d.created_at)}
                  {d.uploaded_by_email && (
                    <span className="block opacity-70">{d.uploaded_by_email}</span>
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  <div className="inline-flex gap-1">
                    <button
                      type="button"
                      onClick={() => handleOpen(d)}
                      disabled={busyId === d.order_id}
                      className="p-1.5 rounded hover:bg-muted text-muted-foreground disabled:opacity-50"
                      title="Otwórz"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDownload(d)}
                      disabled={busyId === d.order_id}
                      className="p-1.5 rounded hover:bg-muted text-muted-foreground disabled:opacity-50"
                      title="Pobierz"
                    >
                      {busyId === d.order_id ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Download className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
