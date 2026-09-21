"use client";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";

type PackageDocument = { id: number; language: string; status: string; filename: string; approved_version_id: number | null };
type Package = { fingerprint: string; managed: boolean; ready: boolean; generic: boolean; reasons: string[]; required_languages: string[]; documents: PackageDocument[]; note_id: number | null; notes: { id: number; content: string }[]; can_retry: boolean; generation_status: string; effective_policy: { require_recommendation_note: boolean } };
export function CvPackagePanel({ id, onEdit, onDownload, onDownloadHtml, canWrite }: { id: number; onEdit: (doc: PackageDocument) => void; onDownload: (doc: PackageDocument) => void; onDownloadHtml?: (doc: PackageDocument) => void; canWrite: boolean }) {
  const [noteId, setNoteId] = useState<number | null | undefined>();
  const query = useQuery<Package>({ queryKey: ["cv-package", id, noteId], placeholderData: previous => previous, queryFn: async () => (await api.get(`/api/cv-generator/generated/${id}/package`, { params: { note_id: noteId ?? undefined } })).data, refetchInterval: 5000 });
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const data = query.data;
  useEffect(() => { setChecked(false); }, [data?.fingerprint]);
  async function act(action: "confirm" | "retry") {
    setBusy(true); setError("");
    try {
      await api.post(`/api/cv-generator/generated/${id}/package/${action}`, action === "confirm" ? { note_id: noteId === undefined ? data?.note_id : noteId, sources_checked: checked, expected_fingerprint: data?.fingerprint } : {});
      setChecked(false); await query.refetch();
    } catch (e) { setError(apiErrorMessage(e, "Nie udało się zaktualizować pakietu.")); }
    finally { setBusy(false); }
  }
  if (query.isError) return <p className="text-sm text-destructive">Nie udało się sprawdzić gotowości pakietu.</p>;
  if (!data?.managed) return null;
  return <div className="mt-3 space-y-2 rounded-md border border-border bg-muted/30 p-3 text-sm">
    <p className="font-medium">Pakiet {data.required_languages.map(x => x.toUpperCase()).join(" + ")} · {data.ready ? "Gotowy do wysłania" : "Szkic — niegotowy do wysłania"}{data.generic ? " · CV ogólne" : " · Dopasowanie do rekrutacji"}</p>
    {data.documents.map(doc => <div key={doc.id} className="flex flex-wrap items-center gap-2"><span>{doc.language.toUpperCase()} · {doc.status === "ready" ? (doc.approved_version_id ? "zatwierdzona wersja" : "plik wygenerowany") : doc.status === "failed" ? "błąd" : "generowanie"}</span>{doc.status === "ready" && <><Button size="sm" variant="outline" onClick={() => onDownload(doc)}>Pobierz {doc.language.toUpperCase()}</Button>{onDownloadHtml && <Button size="sm" variant="outline" onClick={() => onDownloadHtml(doc)}>HTML {doc.language.toUpperCase()}</Button>}{canWrite && <Button size="sm" variant="outline" onClick={() => onEdit(doc)}>Sprawdź i zatwierdź {doc.language.toUpperCase()}</Button>}</>}</div>)}
    {!data.ready && <ul className="list-disc pl-5 text-muted-foreground">{data.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>}
    {canWrite && <>
      {(data.effective_policy.require_recommendation_note || data.notes.length > 0) && <label className="block">Notatka rekomendacyjna
        <select className="mt-1 block w-full rounded-md border border-border bg-background p-2" value={noteId === undefined ? data.note_id ?? "" : noteId ?? ""} onChange={e => { setNoteId(e.target.value ? Number(e.target.value) : null); setChecked(false); }}><option value="">Wskaż istniejącą notatkę z tej rekrutacji</option>{data.notes.map(note => <option key={note.id} value={note.id}>#{note.id} · {note.content.replace(/<[^>]*>/g, "").slice(0, 180)}</option>)}</select>
        <span className="text-xs text-muted-foreground">Wybierz notatkę zawierającą rekomendację. Wybór nie publikuje jej klientowi.</span>
      </label>}
      <label className="flex items-start gap-2"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} />Sprawdziłem wszystkie wersje CV i wskazaną notatkę względem źródeł, a wymagany załącznik zgody jest czytelny i dotyczy tego zapytania.</label>
      <div className="flex gap-2"><Button size="sm" disabled={!checked || busy || query.isFetching} onClick={() => act("confirm")}>Potwierdź gotowość pakietu</Button>{data.can_retry && <Button size="sm" variant="outline" disabled={busy} onClick={() => act("retry")}>Ponów brakujący język</Button>}</div>
      {data.can_retry && <p className="text-xs text-muted-foreground">Ponowienie zużywa AI tylko dla brakującej wersji. Gotowa wersja zostaje zachowana.</p>}
    </>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
}
