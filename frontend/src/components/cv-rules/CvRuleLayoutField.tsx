"use client";

/**
 * „Układ CV” w regule klienta (22.11.2026): domyślny układ nowych CV klienta —
 * Klasyczne (Word) albo Nowe CV (PDF). Rekruter może go zmienić przy CV, dopóki
 * CV nie poszło do klienta. Od 25.11.2026 Word Nowego CV też ma nowy wygląd
 * (strona 1 jak w PDF); klasyczny Word zostaje w „Więcej”.
 *
 * Dwa miejsca: pole formularza reguły (zapis z „Zapisz i włącz regułę”) i —
 * przy zasadach centralnych, gdy reguła jest tylko do odczytu — sekcja z własnym
 * zapisem (`PUT …/cv-rule/layout`), jak wzór „Karty przed CV”.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutTemplate, Loader2 } from "lucide-react";

import type { CvLayout } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cvRulesApi } from "@/lib/cv-rules";

const OPTIONS: ReadonlyArray<readonly [CvLayout, string, string]> = [
  ["classic", "Klasyczne (Word)", "Plik Word w szablonie B2B.net — jak dotąd."],
  [
    "new",
    "Nowe CV (PDF)",
    "PDF i Word w nowym układzie, z tej samej treści. Klasyczny Word zostaje w „Więcej” przy CV.",
  ],
];

export function CvRuleLayoutField({
  value,
  onChange,
  disabled = false,
  name = "cvrule-cv-layout",
}: {
  value: CvLayout;
  onChange: (value: CvLayout) => void;
  disabled?: boolean;
  name?: string;
}) {
  return (
    <fieldset className="space-y-1.5" data-testid="cvrule-cv-layout">
      <legend className="mb-1 text-xs font-medium">Układ CV</legend>
      {OPTIONS.map(([option, title, hint]) => (
        <label key={option} className="flex items-start gap-2 text-sm">
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
        Dotyczy nowych CV tego klienta. Rekruter zmieni układ przy CV, dopóki nie wyśle go klientowi.
      </p>
    </fieldset>
  );
}

const layoutRuleKey = (clientId: number) => ["cv-rule-layout", clientId] as const;

/** Sekcja „Układ CV” przy zasadach centralnych — zapis od razu, nowa wersja reguły. */
export function CvRuleLayoutSection({ clientId }: { clientId: number }) {
  const queryClient = useQueryClient();
  // Komunikat w sekcji, nie toast — edytor reguły działa też bez ToastProvidera.
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const query = useQuery({
    queryKey: layoutRuleKey(clientId),
    queryFn: () => cvRulesApi.get(clientId),
  });
  const save = useMutation({
    mutationFn: (next: CvLayout) => cvRulesApi.setLayout(clientId, next, query.data?.edit_revision ?? 0),
    onSuccess: (rule) => {
      queryClient.setQueryData(layoutRuleKey(clientId), rule);
      void queryClient.invalidateQueries({ queryKey: ["client-cv-rule", clientId] });
      void queryClient.invalidateQueries({ queryKey: ["cv-rule-history", clientId] });
      void queryClient.invalidateQueries({ queryKey: ["settings-cv-rules"] });
      setMessage({
        tone: "ok",
        text:
          rule.cv_layout === "new"
            ? `Zapisano (wersja ${rule.version}) — nowe CV tego klienta powstają jako Nowe CV (PDF).`
            : `Zapisano (wersja ${rule.version}) — nowe CV tego klienta powstają jako klasyczne (Word).`,
      });
    },
    onError: (error) => {
      setMessage({ tone: "error", text: apiErrorMessage(error, "Nie udało się zapisać układu CV.") });
      void query.refetch();
    },
  });

  if (!query.data?.new_layout_enabled) return null;
  return (
    <section className="rounded-lg border" data-testid="cvrule-layout-section">
      <header className="flex items-center gap-3 border-b bg-muted/40 px-4 py-3">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
          <LayoutTemplate className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold">Układ CV</p>
          <p className="text-xs text-muted-foreground">
            Spoza katalogu zasad centralnych. Zmiana obowiązuje od razu i trafia do historii reguły.
          </p>
        </div>
      </header>
      <div className="flex flex-col gap-3 p-4 text-sm">
        <CvRuleLayoutField
          name={`cvrule-cv-layout-${clientId}`}
          value={query.data.cv_layout === "new" ? "new" : "classic"}
          onChange={(next) => {
            setMessage(null);
            save.mutate(next);
          }}
          disabled={save.isPending}
        />
        {save.isPending ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
            <Loader2 className="size-3.5 animate-spin" aria-hidden /> Zapisuję układ…
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
