"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Label } from "@/components/ui/label";

type CvSource = { id: number; filename: string; is_primary: boolean; uploaded_at: string | null };

export function useCvSourceSelection(candidateId: number | undefined, enabled: boolean) {
  const [choice, setChoice] = useState<{ candidateId: number; documentId: number } | null>(null);
  const query = useQuery({
    queryKey: ["cv-gen-sources", candidateId],
    queryFn: async () => {
      if (!candidateId) return [] as CvSource[];
      const res = await api.get<CvSource[]>(`/api/cv-generator/candidates/${candidateId}/cv-sources`);
      return res.data;
    },
    enabled: !!candidateId && enabled,
  });
  const selected = !query.isError && !query.isLoading && choice?.candidateId === candidateId
    ? query.data?.find((source) => source.id === choice?.documentId)
    : undefined;
  return {
    query, selected,
    choose: (value: string) => setChoice(value && candidateId ? { candidateId, documentId: Number(value) } : null),
  };
}

export function CvSourcePicker({ selection }: { selection: ReturnType<typeof useCvSourceSelection> }) {
  const id = useId();
  const { query, selected, choose } = selection;
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>Plik do generacji</Label>
      <select id={id} className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        value={selected?.id ?? ""} onChange={(event) => choose(event.target.value)}
        disabled={query.isLoading || query.isError}>
        <option value="">Wybierz źródłowe CV…</option>
        {(query.data ?? []).map((source) => (
          <option key={source.id} value={source.id}>
            {source.filename}{source.is_primary ? " · główne" : ""}
            {source.uploaded_at ? ` · ${new Date(source.uploaded_at).toLocaleDateString("pl-PL")}` : ""}
          </option>
        ))}
      </select>
      <p className="text-xs text-muted-foreground">
        {query.isError ? "Nie udało się pobrać plików CV. Odśwież stronę i spróbuj ponownie."
          : query.isLoading ? "Wczytywanie plików CV…"
          : !query.data?.length ? "Brak obsługiwanych plików PDF lub DOCX."
          : "Wybrany plik będzie źródłem faktów dla obu wersji językowych."}
      </p>
    </div>
  );
}
