"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, AlertTriangle } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  type PublicProfileFinding,
  careerLinkQueryKey,
  careerLinksApi,
  findingsFromAboutError,
} from "@/lib/api/careerLinks";

/** Limit „O mnie” — ten sam co `ABOUT_MAX` w `api/career_links.py`. */
export const ABOUT_MAX = 280;

/**
 * „O mnie” na stronie rekrutera (etap 6, makieta 6d): dwa zdania pod imieniem.
 * Serwer odmawia zapisu z nazwiskiem, kontaktem, klientem, kwotą albo kodem
 * zgłoszenia (ta sama kontrola co opis rekrutacji) — znaleziska są tu listą.
 */
export function RecruiterAbout({ slug, about }: { slug: string; about: string | null }) {
  const qc = useQueryClient();
  const { showSuccess } = useToast();
  const [draft, setDraft] = useState(about ?? "");
  const [touched, setTouched] = useState(false);
  const [findings, setFindings] = useState<PublicProfileFinding[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Tekst idzie za serwerem, dopóki użytkownik go nie edytuje.
  useEffect(() => {
    if (!touched) setDraft(about ?? "");
  }, [about, touched]);

  const saved = (about ?? "").trim();
  const dirty = draft.trim() !== saved;
  const tooLong = draft.trim().length > ABOUT_MAX;

  const mutation = useMutation({
    mutationFn: () => careerLinksApi.saveCareerAbout(slug, draft.trim()),
    onSuccess: () => {
      setTouched(false);
      setFindings([]);
      setError(null);
      showSuccess(draft.trim() ? "Zapisano „O mnie”." : "Usunięto „O mnie”.");
      qc.invalidateQueries({ queryKey: careerLinkQueryKey() });
    },
    onError: (err) => {
      const found = findingsFromAboutError(err);
      setFindings(found ?? []);
      setError(found ? null : apiErrorMessage(err, "Nie udało się zapisać „O mnie”."));
    },
  });

  return (
    <section className="space-y-2" aria-labelledby="career-about-label">
      <label id="career-about-label" htmlFor="career-about" className="text-sm font-semibold text-foreground">
        O mnie
      </label>
      <p id="career-about-hint" className="text-xs text-muted-foreground">
        Najwyżej dwa zdania pod Twoim imieniem na stronie. Bez nazwiska, kontaktu, klienta
        i stawek — sprawdzam to przy zapisie.
      </p>
      <Textarea
        id="career-about"
        value={draft}
        rows={3}
        placeholder="Np. Szukam ludzi do projektów w bankowości — głównie Java i chmura. Odzywam się w ciągu dwóch dni roboczych."
        onChange={(e) => {
          setTouched(true);
          setFindings([]);
          setError(null);
          setDraft(e.target.value);
        }}
        aria-describedby="career-about-hint career-about-count"
        invalid={tooLong || findings.length > 0}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          id="career-about-count"
          className={tooLong ? "text-xs text-destructive" : "text-xs text-muted-foreground"}
        >
          {draft.trim().length}/{ABOUT_MAX} znaków
        </span>
        <Button
          size="sm"
          onClick={() => mutation.mutate()}
          disabled={!dirty || tooLong || mutation.isPending}
          loading={mutation.isPending}
        >
          Zapisz „O mnie”
        </Button>
      </div>
      {findings.length > 0 ? (
        <ul className="space-y-1.5" data-testid="career-about-findings">
          {findings.map((f, i) => (
            <li
              key={`${f.code}-${i}`}
              role="alert"
              className="flex items-start gap-2 rounded-md border border-warning/25 bg-warning-muted px-2.5 py-2 text-sm text-warning-muted-foreground"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {f.message}
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {error}
        </p>
      ) : null}
    </section>
  );
}
