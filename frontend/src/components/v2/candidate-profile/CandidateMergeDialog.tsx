"use client";

/**
 * „Scal z…” na profilu kandydata (admin + Head of Recruitment).
 *
 * Krok 1: wybór duplikatu — podpowiedzi z `check-duplicates` albo numer
 * profilu. Krok 2: porównanie pól (w konfliktach wybór wartości), liczniki
 * przenoszonych rekordów z serwera i potwierdzenie. Profil, na którym stoimy,
 * zostaje; wybrany duplikat znika, a wszystko, co na niego wskazywało,
 * przechodzi tutaj. Bez natywnego dialogu przeglądarki — potwierdzenie jest w oknie.
 */

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { apiErrorMessage } from "@/lib/api-error";
import {
  applyMerge,
  candidateMergeKeys,
  fetchDuplicateSuggestions,
  fetchMergePreview,
  planFromMergeConflict,
  referenceLabel,
  resultingValue,
  type MergeChoice,
  type MergePlan,
} from "@/lib/api/candidateMerge";

interface CandidateLike {
  id: number;
  name?: string | null;
  lastname?: string | null;
  email?: string | null;
  phone?: string | null;
  linkedin?: string | null;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidate: CandidateLike;
  /** Harness `/preview/candidate-merge`: okno otwarte od razu na porównaniu. */
  initialDuplicateId?: number | null;
}

function fullName(person: { name?: string | null; lastname?: string | null }): string {
  return `${person.name ?? ""} ${person.lastname ?? ""}`.trim() || "—";
}

function show(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

/** Porównanie i liczniki — bez zapytań (używa go też harness `/preview`). */
export function MergePlanView({
  plan,
  choices,
  onChoose,
}: {
  plan: MergePlan;
  choices: Record<string, MergeChoice>;
  onChoose: (field: string, choice: MergeChoice) => void;
}) {
  const conflicts = plan.fields.filter((f) => f.conflict);
  // Nazwa grupy radiowej unikalna per instancja — dwa porównania na jednej
  // stronie (harness, okno nad profilem) nie mogą dzielić grupy.
  const groupId = useId();
  return (
    <div className="space-y-4 text-sm">
      {plan.blockers.length > 0 ? (
        <div role="alert" className="space-y-1 rounded-md border border-destructive/40 bg-destructive/5 p-3">
          <p className="flex items-center gap-2 font-medium text-destructive">
            <AlertTriangle className="h-4 w-4" aria-hidden /> Scalenie jest zablokowane
          </p>
          <ul className="list-disc pl-5">
            {plan.blockers.map((b) => (
              <li key={b.code}>{b.message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Porównanie pól profilu</caption>
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="py-1 pr-3 font-medium">Pole</th>
              <th className="py-1 pr-3 font-medium">Ten profil (#{plan.survivor_id})</th>
              <th className="py-1 pr-3 font-medium">Duplikat (#{plan.duplicate_id})</th>
              <th className="py-1 font-medium">Po scaleniu</th>
            </tr>
          </thead>
          <tbody>
            {plan.fields.map((field) => (
              <tr key={field.field} className="border-t border-border align-top">
                <td className="py-2 pr-3 font-medium">{field.label}</td>
                {(["survivor", "duplicate"] as const).map((side) => (
                  <td key={side} className="py-2 pr-3">
                    {field.conflict ? (
                      <label className="flex items-start gap-2">
                        <input
                          type="radio"
                          name={`${groupId}-merge-${field.field}`}
                          checked={(choices[field.field] ?? "survivor") === side}
                          onChange={() => onChoose(field.field, side)}
                          aria-label={`${field.label}: ${show(field[side])}`}
                        />
                        <span className="break-words">{show(field[side])}</span>
                      </label>
                    ) : (
                      <span className="break-words text-muted-foreground">{show(field[side])}</span>
                    )}
                  </td>
                ))}
                <td className="py-2 break-words">{show(resultingValue(field, choices))}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {conflicts.length === 0 ? (
          <p className="mt-1 text-xs text-muted-foreground">Pola się nie wykluczają — puste uzupełnią się z drugiego profilu.</p>
        ) : null}
      </div>

      <div className="space-y-1">
        <p className="font-medium">
          Przejdzie na ten profil: {plan.moved_rows} {plan.moved_rows === 1 ? "rekord" : "rekordów"}
        </p>
        {plan.references.length + plan.polymorphic.length > 0 ? (
          <ul className="grid grid-cols-1 gap-x-6 gap-y-0.5 text-xs text-muted-foreground sm:grid-cols-2">
            {plan.references.map((r) => (
              <li key={`${r.table}.${r.column}`}>
                {referenceLabel(r.table)}: {r.rows}
                {r.conflicts > 0 ? ` (w tym ${r.conflicts} zdublowanych — zostaje nowszy wpis)` : ""}
              </li>
            ))}
            {plan.polymorphic.map((p) => (
              <li key={p.table}>
                {referenceLabel(p.table)}: {p.rows}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">Duplikat nie ma powiązanych rekordów.</p>
        )}
      </div>
    </div>
  );
}

export function CandidateMergeDialog({
  open,
  onOpenChange,
  candidate,
  initialDuplicateId = null,
}: Props) {
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  const [duplicateId, setDuplicateId] = useState<number | null>(initialDuplicateId);
  const [manualId, setManualId] = useState("");
  const [choices, setChoices] = useState<Record<string, MergeChoice>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [override, setOverride] = useState<MergePlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  const suggestions = useQuery({
    queryKey: candidateMergeKeys.suggestions(candidate.id),
    queryFn: () => fetchDuplicateSuggestions(candidate),
    enabled: open && duplicateId === null,
  });
  const preview = useQuery({
    queryKey: candidateMergeKeys.preview(candidate.id, duplicateId),
    queryFn: () => fetchMergePreview(candidate.id, duplicateId!),
    enabled: open && duplicateId !== null,
    // Bez wymuszonego `staleTime: 0`: nieaktualny plan i tak odrzuci serwer
    // (409 z odciskiem niesie świeży plan), a harness zasiewa cache.
  });
  const plan = override ?? preview.data ?? null;

  const reset = () => {
    setDuplicateId(null);
    setManualId("");
    setChoices({});
    setConfirmed(false);
    setOverride(null);
    setError(null);
  };

  const merge = useMutation({
    mutationFn: (p: MergePlan) => applyMerge(candidate.id, p, choices),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.detail(candidate.id) });
      void queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      void queryClient.invalidateQueries({ queryKey: ["candidate-timeline"] });
      showSuccess(`Scalono profil #${result.duplicate_id} z tym profilem.`);
      reset();
      onOpenChange(false);
    },
    onError: (err) => {
      const fresh = planFromMergeConflict(err);
      if (fresh) {
        setOverride(fresh);
        setConfirmed(false);
        setError("Od podglądu dane się zmieniły — sprawdź porównanie jeszcze raz.");
        return;
      }
      setError(apiErrorMessage(err, "Nie udało się scalić profili."));
    },
  });

  const pick = (id: number) => {
    setDuplicateId(id);
    setChoices({});
    setConfirmed(false);
    setOverride(null);
    setError(null);
  };
  const manual = Number(manualId.trim());
  const manualValid = Number.isInteger(manual) && manual > 0 && manual !== candidate.id;

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      title="Scal z innym profilem"
      description={`Ten profil (${fullName(candidate)}, #${candidate.id}) zostaje. Wybrany duplikat zostanie usunięty, a jego notatki, dokumenty, procesy i historia przejdą tutaj.`}
      size="xl"
      footer={
        duplicateId === null ? (
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
        ) : (
          <>
            <Button variant="outline" onClick={reset}>
              <ArrowLeft className="mr-1 h-4 w-4" aria-hidden /> Wybierz inny
            </Button>
            <Button
              variant="primary"
              disabled={!plan || !plan.can_apply || !confirmed || merge.isPending || preview.isFetching}
              onClick={() => plan && merge.mutate(plan)}
            >
              {merge.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Scal profile
            </Button>
          </>
        )
      }
    >
      {duplicateId === null ? (
        <div className="space-y-4 text-sm">
          <div className="space-y-2">
            <p className="font-medium">Możliwe duplikaty</p>
            {suggestions.isError ? (
              <p role="alert" className="text-destructive">
                {apiErrorMessage(suggestions.error, "Nie udało się wyszukać duplikatów.")}
              </p>
            ) : suggestions.isSuccess ? (
              suggestions.data.length === 0 ? (
                <p className="text-muted-foreground">Nie znaleziono profili o tym samym e-mailu, telefonie, LinkedInie ani imieniu i nazwisku.</p>
              ) : (
                <ul className="divide-y divide-border rounded-md border border-border">
                  {suggestions.data.map((s) => (
                    <li key={s.candidate_id} className="flex items-center justify-between gap-3 px-3 py-2">
                      <span>
                        <span className="font-medium">{fullName(s)}</span>{" "}
                        <span className="text-muted-foreground">#{s.candidate_id}{s.email ? ` · ${s.email}` : ""}</span>
                      </span>
                      <Button size="sm" variant="outline" onClick={() => pick(s.candidate_id)}>
                        Porównaj
                      </Button>
                    </li>
                  ))}
                </ul>
              )
            ) : (
              <p className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Szukam duplikatów…
              </p>
            )}
          </div>
          <div className="flex items-end gap-2">
            <label className="space-y-1">
              <span className="block text-xs font-medium">Albo numer profilu</span>
              <input
                inputMode="numeric"
                value={manualId}
                onChange={(e) => setManualId(e.target.value)}
                className="h-9 w-40 rounded-md border border-input bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder="np. 12345"
              />
            </label>
            <Button variant="outline" disabled={!manualValid} onClick={() => pick(manual)}>
              Porównaj
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          {preview.isError && !override ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(preview.error, "Nie udało się porównać profili.")}
            </p>
          ) : plan ? (
            <>
              <MergePlanView
                plan={plan}
                choices={choices}
                onChoose={(field, choice) => setChoices((prev) => ({ ...prev, [field]: choice }))}
              />
              {plan.can_apply ? (
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                  <span>
                    Rozumiem, że profil #{plan.duplicate_id} ({fullName(plan.duplicate)}) zostanie usunięty, a jego dane przejdą na ten profil. Tej operacji nie da się cofnąć.
                  </span>
                </label>
              ) : null}
            </>
          ) : (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Porównuję profile…
            </p>
          )}
        </div>
      )}
    </AppModal>
  );
}
