"use client";

/**
 * Chipy „✓ / nie znaleziono” w podglądzie osoby ze źródłem przy każdym „✓”
 * i oknem „Skąd” po kliknięciu (zgłoszenie DL z 09.11.2026, wariant B).
 *
 * „✓ angular” stał u osoby, która Angulara w CV nie ma — wziął się z pola
 * Traffita i notatki, a ekran tego nie mówił. Teraz przy „✓” stoi „CV,
 * profil, notatka”; bez CV dopisek jest żółty. Klik pokazuje cytaty, a „Pokaż
 * w CV” otwiera plik z lupą na tym słowie. Ocena dopasowania się nie zmienia.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import {
  candidateSearchApi,
  type RequirementEvidence,
  type RequirementEvidenceQuote,
  type RequirementEvidenceSource,
} from "@/lib/candidate-search-api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

const SOURCE_LABEL: Record<RequirementEvidenceSource, string> = {
  cv: "CV",
  profile: "profil",
  note: "notatka",
};

const EVIDENCE_STALE_MS = 5 * 60_000;

export function requirementEvidenceKey(jobId: number, candidateId: number, labels: readonly string[]) {
  return ["requirement-evidence", jobId, candidateId, [...labels].sort().join("|")] as const;
}

/** „CV, profil” — albo null, gdy źródeł jeszcze nie ma (ładowanie, błąd). */
export function sourceSuffix(evidence: RequirementEvidence | undefined): string | null {
  if (!evidence) return null;
  if (evidence.sources.length === 0) return "bez wzmianki";
  return evidence.sources.map((s) => SOURCE_LABEL[s]).join(", ");
}

export function lacksCv(evidence: RequirementEvidence | undefined): boolean {
  return Boolean(evidence) && !evidence!.sources.includes("cv");
}

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-");
  return y && m && d ? `${d}.${m}.${y}` : iso;
}

/** Cytat z podświetlonym słowem (albo nazwą, którą trafienie stoi w tekście). */
export function Quote({ quote, word }: { quote: RequirementEvidenceQuote; word: string }) {
  const needle = (quote.via ?? word).toLocaleLowerCase("pl");
  const text = quote.snippet;
  const at = text.toLocaleLowerCase("pl").indexOf(needle);
  return (
    <span>
      „
      {at < 0 ? (
        text
      ) : (
        <>
          {text.slice(0, at)}
          <mark className="rounded-sm bg-warning-muted px-0.5 text-foreground">
            {text.slice(at, at + needle.length)}
          </mark>
          {text.slice(at + needle.length)}
        </>
      )}
      ”
      {quote.via ? <span className="text-muted-foreground"> (jako „{quote.via}”)</span> : null}
    </span>
  );
}

function BoxLabel({ children }: { children: string }) {
  return (
    <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{children}</p>
  );
}

function EvidenceBox({
  skill,
  evidence,
  onClose,
  onShowInCv,
}: {
  skill: string;
  evidence: RequirementEvidence;
  onClose: () => void;
  onShowInCv: (term: string) => void;
}) {
  const nothing = evidence.sources.length === 0;
  return (
    <div
      className="space-y-2 rounded-md border border-border bg-card p-2.5 text-xs"
      role="region"
      aria-label={`Skąd ✓ ${skill}`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-foreground">Skąd „✓ {skill}”</p>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
          aria-label="Zamknij źródła"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
      <div className="space-y-1">
        <BoxLabel>CV</BoxLabel>
        {evidence.cv ? (
          <div className="flex items-start justify-between gap-2">
            <p className="min-w-0 text-foreground">
              <Quote quote={evidence.cv} word={skill} />
            </p>
            <button
              type="button"
              onClick={() => onShowInCv(evidence.cv?.via ?? skill)}
              className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[11px] text-primary hover:bg-muted"
            >
              Pokaż w CV
            </button>
          </div>
        ) : (
          <p className="font-medium text-warning-muted-foreground">
            W tekście CV tego słowa nie ma — zapytaj w rozmowie.
          </p>
        )}
      </div>
      {evidence.notes.length > 0 ? (
        <div className="space-y-1">
          <BoxLabel>Notatki</BoxLabel>
          {evidence.notes.map((note) => (
            <p key={note.id} className="text-foreground">
              <span className="text-muted-foreground">
                {[formatDate(note.date), note.author].filter(Boolean).join(" · ") || "Notatka"} —{" "}
              </span>
              <Quote quote={note} word={skill} />
            </p>
          ))}
          {evidence.notes_more > 0 ? (
            <p className="text-muted-foreground">+{evidence.notes_more} kolejne — w notatkach w profilu</p>
          ) : null}
        </div>
      ) : null}
      {evidence.profile.length > 0 ? (
        <div className="space-y-1">
          <BoxLabel>Profil</BoxLabel>
          {evidence.profile.map((item) => (
            <p key={item.where} className="text-foreground">
              <span className="text-muted-foreground">{item.where} — </span>
              <Quote quote={item} word={skill} />
            </p>
          ))}
        </div>
      ) : null}
      {nothing ? (
        <p className="text-muted-foreground">
          Ocena uznała to wymaganie po wariancie nazwy z listy umiejętności, ale dosłownej wzmianki nie ma ani w
          CV, ani w profilu, ani w notatkach — zapytaj w rozmowie.
        </p>
      ) : null}
    </div>
  );
}

export function RequirementEvidenceChips({
  jobId,
  candidateId,
  matched,
  gaps,
  onShowInCv,
}: {
  jobId: number;
  candidateId: number;
  matched: readonly string[];
  gaps: readonly string[];
  onShowInCv: (term: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const evidence = useQuery({
    queryKey: requirementEvidenceKey(jobId, candidateId, matched),
    queryFn: ({ signal }) =>
      candidateSearchApi.requirementEvidence(jobId, candidateId, [...matched], signal),
    enabled: matched.length > 0,
    staleTime: EVIDENCE_STALE_MS,
  });
  const items = evidence.data?.items ?? {};
  const openEvidence = open ? items[open] : undefined;

  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap gap-1.5" aria-label="Wymagania must-have" data-tour="person-preview.requirement-sources">
        {matched.map((skill) => {
          const item = items[skill];
          const suffix = sourceSuffix(item);
          const noCv = lacksCv(item);
          const isOpen = open === skill;
          return (
            <li key={`met-${skill}`}>
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : skill)}
                aria-expanded={isOpen}
                disabled={!item}
                title={item ? "Pokaż, skąd to wiemy" : undefined}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md bg-success-muted px-2 py-0.5 text-xs text-success-muted-foreground",
                  item && "hover:underline",
                  isOpen && "outline outline-2 outline-primary",
                )}
              >
                <Check className="h-3 w-3" aria-hidden />
                {skill}
                {suffix ? (
                  <>
                    {" "}
                    <span className={noCv ? "font-medium text-warning-muted-foreground" : "opacity-70"}>
                      · {suffix}
                    </span>
                  </>
                ) : null}
              </button>
            </li>
          );
        })}
        {gaps.map((skill) => (
          <li
            key={`gap-${skill}`}
            className="rounded-md bg-warning-muted px-2 py-0.5 text-xs text-warning-muted-foreground"
          >
            {skill} — nie znaleziono
          </li>
        ))}
      </ul>
      {evidence.isError ? (
        <p role="alert" className="text-xs text-muted-foreground">
          {apiErrorMessage(evidence.error, "Nie wczytano źródeł „✓”.")}{" "}
          <button type="button" className="text-primary hover:underline" onClick={() => void evidence.refetch()}>
            Spróbuj ponownie
          </button>
        </p>
      ) : null}
      {open && openEvidence ? (
        <EvidenceBox
          skill={open}
          evidence={openEvidence}
          onClose={() => setOpen(null)}
          onShowInCv={onShowInCv}
        />
      ) : null}
    </div>
  );
}
