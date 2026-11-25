"use client";

/**
 * „Format pliku” w regule klienta (25.11.2026): w jakim pliku klient chce CV —
 * Word, PDF albo oba. Główny przycisk pobrania w karcie „CV do klienta”,
 * edytorze i wyniku generatora idzie za tym polem. „Bez wymagań” = jak dotąd
 * (plik idzie za układem CV).
 *
 * Dwa miejsca, jak „Układ CV”: pole formularza reguły (zapis z „Zapisz i włącz
 * regułę”) i — przy zasadach centralnych — sekcja z własnym zapisem
 * (`PUT …/cv-rule/file-format`). W przeciwieństwie do układu nie zależy od
 * flagi „Nowego CV”: klasyczne CV też ma PDF.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileType2, Loader2 } from "lucide-react";

import { apiErrorMessage } from "@/lib/api-error";
import { CV_FILE_FORMAT_LABEL, type CvFileFormat } from "@/lib/cv-file-format";
import { cvRulesApi } from "@/lib/cv-rules";

type Choice = "" | CvFileFormat;

const OPTIONS: ReadonlyArray<readonly [Choice, string, string]> = [
  ["", "Bez wymagań", "Jak dotąd: Word przy klasycznym CV, PDF przy Nowym CV."],
  ["docx", "Word", "Rekruter pobiera najpierw plik Word; PDF zostaje w „Więcej”."],
  ["pdf", "PDF", "Rekruter pobiera najpierw PDF; Word zostaje w „Więcej”."],
  ["both", "Word i PDF", "Oba pliki na wierzchu — klient chce dostać oba."],
];

export function CvRuleFileFormatField({
  value,
  onChange,
  disabled = false,
  name = "cvrule-cv-file-format",
}: {
  value: Choice;
  onChange: (value: Choice) => void;
  disabled?: boolean;
  name?: string;
}) {
  return (
    <fieldset className="space-y-1.5" data-testid="cvrule-cv-file-format">
      <legend className="mb-1 text-xs font-medium">Format pliku dla klienta</legend>
      {OPTIONS.map(([option, title, hint]) => (
        <label key={option || "none"} className="flex items-start gap-2 text-sm">
          <input
            type="radio"
            name={name}
            value={option}
            className="mt-1"
            checked={value === option}
            disabled={disabled}
            onChange={() => onChange(option)}
          />
          <span>
            {title}
            <span className="block text-xs text-muted-foreground">{hint}</span>
          </span>
        </label>
      ))}
      <p className="text-xs text-muted-foreground">
        Przy Nowym CV plik Word ma nowy wygląd (strona 1 jak w PDF, dalej stanowiska do edycji); klasyczny Word zostaje w „Więcej”.
      </p>
    </fieldset>
  );
}

/** Fakt w pasku reguły. */
export function cvFileFormatFact(value: Choice | null | undefined): string {
  return value ? CV_FILE_FORMAT_LABEL[value] : "Bez wymagań";
}

const formatRuleKey = (clientId: number) => ["cv-rule-file-format", clientId] as const;

/** Sekcja „Format pliku” przy zasadach centralnych — zapis od razu, nowa wersja reguły. */
export function CvRuleFileFormatSection({ clientId }: { clientId: number }) {
  const queryClient = useQueryClient();
  // Komunikat w sekcji, nie toast — edytor reguły działa też bez ToastProvidera.
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const query = useQuery({
    queryKey: formatRuleKey(clientId),
    queryFn: () => cvRulesApi.get(clientId),
  });
  const save = useMutation({
    mutationFn: (next: Choice) =>
      cvRulesApi.setFileFormat(clientId, next || null, query.data?.edit_revision ?? 0),
    onSuccess: (rule) => {
      queryClient.setQueryData(formatRuleKey(clientId), rule);
      void queryClient.invalidateQueries({ queryKey: ["cv-rule-layout", clientId] });
      void queryClient.invalidateQueries({ queryKey: ["client-cv-rule", clientId] });
      void queryClient.invalidateQueries({ queryKey: ["cv-rule-history", clientId] });
      void queryClient.invalidateQueries({ queryKey: ["settings-cv-rules"] });
      setMessage({
        tone: "ok",
        text: `Zapisano (wersja ${rule.version}) — format pliku: ${cvFileFormatFact(rule.cv_file_format)}.`,
      });
    },
    onError: (error) => {
      setMessage({ tone: "error", text: apiErrorMessage(error, "Nie udało się zapisać formatu pliku.") });
      void query.refetch();
    },
  });

  if (!query.data) return null;
  return (
    <section className="rounded-lg border" data-testid="cvrule-file-format-section">
      <header className="flex items-center gap-3 border-b bg-muted/40 px-4 py-3">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
          <FileType2 className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold">Format pliku dla klienta</p>
          <p className="text-xs text-muted-foreground">
            Spoza katalogu zasad centralnych. Zmiana obowiązuje od razu i trafia do historii reguły.
          </p>
        </div>
      </header>
      <div className="flex flex-col gap-3 p-4 text-sm">
        <CvRuleFileFormatField
          name={`cvrule-cv-file-format-${clientId}`}
          value={query.data.cv_file_format ?? ""}
          onChange={(next) => {
            setMessage(null);
            save.mutate(next);
          }}
          disabled={save.isPending}
        />
        {save.isPending ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
            <Loader2 className="size-3.5 animate-spin" aria-hidden /> Zapisuję format pliku…
          </p>
        ) : null}
        {message ? (
          <p
            role={message.tone === "error" ? "alert" : "status"}
            className={message.tone === "error" ? "text-xs text-destructive" : "text-xs text-muted-foreground"}
          >
            {message.text}
          </p>
        ) : null}
      </div>
    </section>
  );
}
