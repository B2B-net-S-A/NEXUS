"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";

// Wersje językowe jednego CV (PL / EN). Od 21.09.2026 bez „gotowości pakietu”:
// CV nie są wysyłane klientom przez NEXUS (rekruter pobiera plik), więc lista
// warunków wysyłki, wybór notatki rekomendacyjnej i ręczne potwierdzenie były
// tylko dodatkowymi krokami. Zostaje pobieranie, edycja i ponowienie języka.
type PackageDocument = { id: number; language: string; status: string; filename: string; approved_version_id: number | null };
type Package = { managed: boolean; required_languages: string[]; documents: PackageDocument[]; can_retry: boolean };
export function CvPackagePanel({ id, onEdit, onDownload, onDownloadHtml, canWrite }: { id: number; onEdit: (doc: PackageDocument) => void; onDownload: (doc: PackageDocument) => void; onDownloadHtml?: (doc: PackageDocument) => void; canWrite: boolean }) {
  const query = useQuery<Package>({ queryKey: ["cv-package", id], queryFn: async () => (await api.get(`/api/cv-generator/generated/${id}/package`)).data, refetchInterval: 5000 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const data = query.data;
  async function retry() {
    setBusy(true); setError("");
    try { await api.post(`/api/cv-generator/generated/${id}/package/retry`, {}); await query.refetch(); }
    catch (e) { setError(apiErrorMessage(e, "Nie udało się ponowić brakującej wersji.")); }
    finally { setBusy(false); }
  }
  if (query.isError) return <p className="text-sm text-destructive">Nie udało się wczytać wersji językowych CV.</p>;
  if (!data?.managed) return null;
  return <div className="mt-3 space-y-2 rounded-md border border-border bg-muted/30 p-3 text-sm">
    <p className="font-medium">Wersje CV: {data.required_languages.map(x => x.toUpperCase()).join(" + ")}</p>
    {data.documents.map(doc => <div key={doc.id} className="flex flex-wrap items-center gap-2"><span>{doc.language.toUpperCase()} · {doc.status === "ready" ? (doc.approved_version_id ? "zatwierdzona wersja" : "gotowe") : doc.status === "failed" ? "błąd" : "generowanie…"}</span>{doc.status === "ready" && <><Button size="sm" variant="outline" onClick={() => onDownload(doc)}>Pobierz {doc.language.toUpperCase()}</Button>{onDownloadHtml && <Button size="sm" variant="outline" onClick={() => onDownloadHtml(doc)}>HTML {doc.language.toUpperCase()}</Button>}{canWrite && <Button size="sm" variant="outline" onClick={() => onEdit(doc)}>Edytuj {doc.language.toUpperCase()}</Button>}</>}</div>)}
    {canWrite && data.can_retry && <div className="space-y-1"><Button size="sm" variant="outline" disabled={busy} onClick={retry}>Ponów brakujący język</Button><p className="text-xs text-muted-foreground">Ponowienie zużywa AI tylko dla brakującej wersji. Gotowa wersja zostaje zachowana.</p></div>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
}
