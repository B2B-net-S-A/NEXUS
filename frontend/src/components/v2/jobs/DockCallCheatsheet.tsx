"use client";

/**
 * „Ściąga do rozmowy” w doku osoby (sekcja Screening, makieta v7 29.09.2026).
 *
 * Trzy rzeczy pod ręką, zanim rekruter zadzwoni: tekst na start (ok. 30 s),
 * odpowiedzi na typowe pytania kandydata i trzy pytania z profilu z tym, co
 * jest dobrą odpowiedzią i kiedy osoba odpada. Dane z tego samego
 * wyjaśnienia co blok „Po ludzku” w Podglądzie Championa.
 *
 * Gdy profil nie zna odpowiedzi, ściąga to mówi wprost i pozwala jednym
 * kliknięciem dopisać pytanie do „Do dopytania u klienta” (sekcja 8
 * Championa, notatka `ask_client`) — zwykłym zapisem profilu.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, RefreshCw } from "lucide-react";

import { useToast } from "@/components/Toast";
import { championApi, type ChampionProfile } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAutoRefreshPlainBrief,
  usePlainBrief,
  useRefreshPlainBrief,
  type CandidateQa,
  type PlainBrief,
} from "@/lib/api/plainKnowledge";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import { newInsight } from "@/lib/champion-insights";
import { copyTextToClipboard } from "@/lib/clipboard";

const SCREENING_IN_DOCK = 3;

export const MISSING_ANSWER_TEXT =
  "Profil tego nie mówi. Powiedz: „Sprawdzę i wrócę z odpowiedzią”.";

/** Zapas dla przeglądarek bez `navigator.clipboard` (HTTP, stara przeglądarka). */
function legacyCopy(text: string): boolean {
  if (typeof document === "undefined") return false;
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(area);
  return ok;
}

export async function copyWithFallback(text: string): Promise<boolean> {
  if (await copyTextToClipboard(text)) return true;
  return legacyCopy(text);
}

export function cheatsheetHasContent(brief: PlainBrief | undefined): boolean {
  if (!brief) return false;
  return Boolean(
    brief.pitch?.trim() || brief.candidate_qa.length > 0 || brief.screening_plain.length > 0,
  );
}

/** Dopisuje pytanie kandydata do „Do dopytania u klienta” (sekcja 8). */
function useAddAskClientNote(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (text: string) => {
      // Świeży profil — lista notatek to pełna podmiana, więc stara kopia
      // z cache skasowałaby notatkę dopisaną w międzyczasie przez kogoś innego.
      const current = await championApi.get(jobId).then((r) => r.data);
      const notes = (current.champion_profile as Partial<ChampionProfile> | null)?.insights ?? [];
      const insights = [...notes, newInsight("client", "ask_client", text)];
      return championApi.put(jobId, { insights } as unknown as ChampionProfile);
    },
    // Wyjaśnienia „po ludzku” nie unieważniamy: ściąga ma zostać na ekranie
    // w trakcie rozmowy, a nieaktualność pokaże następne otwarcie.
    onSuccess: () => invalidateChampionDependents(qc, jobId),
  });
}

function QaItem({ jobId, qa }: { jobId: number; qa: CandidateQa }) {
  const toast = useToast();
  const add = useAddAskClientNote(jobId);
  const [added, setAdded] = useState(false);
  const answer = qa.answer?.trim() || null;
  return (
    <li>
      <details className="group rounded-md border border-border" data-testid="cheatsheet-qa">
        <summary className="cursor-pointer list-none px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-muted/40 [&::-webkit-details-marker]:hidden">
          {qa.question}
          {!answer ? <span className="ml-1.5 font-normal text-muted-foreground">· brak w profilu</span> : null}
        </summary>
        <div className="space-y-1.5 border-t border-border px-2.5 py-2 text-xs">
          {answer ? (
            <>
              <p className="whitespace-pre-line text-foreground">{answer}</p>
              {qa.source ? (
                <span className="inline-flex rounded-full border border-border px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                  {qa.source}
                </span>
              ) : null}
            </>
          ) : (
            <>
              <p className="text-muted-foreground">{MISSING_ANSWER_TEXT}</p>
              {added ? (
                <p className="inline-flex items-center gap-1 text-success">
                  <Check className="h-3.5 w-3.5" aria-hidden="true" /> Dopisano do „Do dopytania”
                </p>
              ) : (
                <button
                  type="button"
                  disabled={add.isPending}
                  onClick={() =>
                    add.mutate(qa.question, {
                      onSuccess: () => {
                        setAdded(true);
                        toast.showSuccess("Dopisano do „Do dopytania u klienta”");
                      },
                      onError: (e) =>
                        toast.showError(apiErrorMessage(e, "Nie udało się dopisać pytania")),
                    })
                  }
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 font-medium text-foreground hover:bg-muted disabled:opacity-60"
                >
                  {add.isPending ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : null}
                  Dopisz do „Do dopytania”
                </button>
              )}
            </>
          )}
        </div>
      </details>
    </li>
  );
}

export function DockCallCheatsheet({ jobId }: { jobId: number }) {
  const toast = useToast();
  const query = usePlainBrief(jobId);
  const refresh = useRefreshPlainBrief(jobId);
  useAutoRefreshPlainBrief(jobId, query.data, refresh);

  if (query.isLoading) return null;
  if (query.isError) {
    return (
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground" role="alert">
        Nie udało się wczytać ściągi do rozmowy.
        <button
          type="button"
          onClick={() => void query.refetch()}
          className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
        >
          <RefreshCw className="h-3 w-3" aria-hidden="true" /> Ponów
        </button>
      </p>
    );
  }
  const brief = query.data;
  if (!brief || !cheatsheetHasContent(brief)) {
    return refresh.isPending ? (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> Przygotowuję ściągę do rozmowy…
      </p>
    ) : null;
  }

  const pitch = brief.pitch?.trim() || null;
  const questions = brief.screening_plain.slice(0, SCREENING_IN_DOCK);

  const copyPitch = async () => {
    if (!pitch) return;
    if (await copyWithFallback(pitch)) toast.showSuccess("Skopiowano");
    else toast.showError("Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie");
  };

  return (
    <section
      className="space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-2.5"
      aria-label="Ściąga do rozmowy"
      data-testid="dock-call-cheatsheet"
    >
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Ściąga do rozmowy
      </p>

      {pitch ? (
        <div className="space-y-1.5 rounded-md border border-border bg-card p-2.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] font-semibold text-muted-foreground">Na start · ok. 30 sekund</p>
            <button
              type="button"
              onClick={() => void copyPitch()}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] font-medium text-foreground hover:bg-muted"
              data-testid="cheatsheet-copy"
            >
              <Copy className="h-3 w-3" aria-hidden="true" /> Kopiuj
            </button>
          </div>
          <p className="whitespace-pre-line text-xs leading-relaxed text-foreground" data-testid="cheatsheet-pitch">
            {pitch}
          </p>
        </div>
      ) : null}

      {brief.candidate_qa.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold text-muted-foreground">Kandydat pyta</p>
          <ul className="space-y-1">
            {brief.candidate_qa.map((qa) => (
              <QaItem key={qa.key} jobId={jobId} qa={qa} />
            ))}
          </ul>
        </div>
      ) : null}

      {questions.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold text-muted-foreground">
            Zadaj {questions.length} {questions.length === 1 ? "pytanie" : "pytania"} z profilu
          </p>
          <ol className="space-y-1.5">
            {questions.map((q, i) => (
              <li
                key={q.question_id || i}
                className="rounded-md border border-border bg-card p-2 text-xs"
                data-testid="cheatsheet-question"
              >
                <p className="font-medium text-foreground">
                  {i + 1}. {q.question}
                </p>
                {q.good?.trim() ? (
                  <p className="mt-1 text-foreground">
                    <span className="font-semibold text-success">Dobrze:</span> {q.good}
                  </p>
                ) : null}
                {q.reject?.trim() ? (
                  <p className="mt-0.5 text-foreground">
                    <span className="font-semibold text-destructive">Odpada:</span> {q.reject}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}
