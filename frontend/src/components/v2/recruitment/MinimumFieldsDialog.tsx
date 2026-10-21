"use client";

/**
 * Minimum dla Delivery Leada z Tablicy (decyzja Artura 21.10.2026).
 *
 * Strzałka albo przeciągnięcie na „Zweryfikowany”, gdy brakuje tylko pól
 * minimum (lokalizacja, tryb pracy, dostępność, „Dlaczego ten kandydat”, pola
 * dołożone przez klienta), nie otwiera całego panelu osoby: okno pyta o same
 * brakujące pola. Pola o osobie wpisują się z jej innej rekrutacji (D2).
 * Zapis idzie tym samym `PUT /api/screening-form` co formularz — tylko pola
 * karty, z odciskiem stanu.
 */

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useSaveScreeningForm, useScreeningFormState } from "@/lib/api/screeningForm";
import { CARD_FIELD_HINT } from "@/lib/recommendation-card";
import {
  cardValueCounts,
  carriedCaption,
  carriedPrefill,
  formDefaultsFromState,
  formFieldLabel,
  formQuestions,
  minimumMissingForForward,
} from "@/lib/screening-form";

const MULTILINE: ReadonlySet<string> = new Set(["recommendation", "motivation", "red_flags"]);

interface Props {
  open: boolean;
  candidateId: number;
  jobId: number;
  candidateName: string;
  /** „Zapisz i przesuń” (ruch czeka) albo „Zapisz” (wracamy do „Przesuń dalej”). */
  actionLabel: string;
  /** Pola zapisane — wołający przesuwa kartę albo wraca do swojego okna. */
  onDone: () => void;
  /** Cały formularz screeningu w panelu osoby. */
  onOpenFull: () => void;
  onClose: () => void;
}

export function MinimumFieldsDialog({
  open,
  candidateId,
  jobId,
  candidateName,
  actionLabel,
  onDone,
  onOpenFull,
  onClose,
}: Props) {
  const query = useScreeningFormState(candidateId, jobId, open);
  const state = query.data;
  const save = useSaveScreeningForm();
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  // Braki liczone raz, ze stanu z chwili otwarcia — wpisane pole nie znika z okna.
  const gaps = useMemo(() => {
    if (!state) return [];
    return minimumMissingForForward(state, formQuestions(state), formDefaultsFromState(state));
  }, [state]);
  const carried = useMemo(() => (state ? carriedPrefill(state) : {}), [state]);
  const present = useMemo(
    () => (state?.card?.required ?? []).filter((key) => !gaps.includes(key)),
    [state, gaps],
  );

  useEffect(() => {
    if (!state) return;
    setValues(Object.fromEntries(gaps.map((key) => [key, carried[key]?.raw ?? ""])));
    setError(null);
  }, [state, gaps, carried]);

  const complete = gaps.every((key) => cardValueCounts(key, values[key]));

  const submit = async () => {
    if (!state || !complete || save.isPending) return;
    setError(null);
    try {
      if (gaps.length > 0) {
        await save.mutateAsync({
          candidate_id: candidateId,
          job_id: jobId,
          expected_version: state.version,
          state_token: state.state_token,
          sheet: null,
          card: { fields: Object.fromEntries(gaps.map((key) => [key, values[key].trim()])) },
          rate: null,
          note_import: null,
        });
      }
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e, "Nie udało się zapisać pól. Spróbuj jeszcze raz albo otwórz cały screening."));
    }
  };

  const readOnly = state != null && !state.editable;

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{candidateName} → Zweryfikowany</DialogTitle>
          <DialogDescription>
            {gaps.length > 0
              ? `Delivery Lead potrzebuje jeszcze ${gaps.length === 1 ? "jednego pola" : `${gaps.length} pól`}. Reszta jest już w screeningu.`
              : "Minimum dla Delivery Leada jest już wpisane."}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          {query.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(query.error, "Nie udało się wczytać screeningu tej osoby.")}
            </p>
          ) : !state ? (
            <p className="text-sm text-muted-foreground">Wczytuję screening…</p>
          ) : readOnly ? (
            <p role="note" className="text-sm text-muted-foreground">
              {state.read_only_message ?? "Tego screeningu nie możesz teraz zmienić."}
            </p>
          ) : (
            <>
              {gaps.map((key) => {
                const id = `minimum-${key}`;
                const label = formFieldLabel(state, key);
                const hint = carried[key];
                const placeholder = CARD_FIELD_HINT[key] ?? undefined;
                return (
                  <div key={key} className="space-y-1" data-minimum-field={key}>
                    <Label htmlFor={id}>{label}</Label>
                    {MULTILINE.has(key) ? (
                      <Textarea
                        id={id}
                        rows={3}
                        value={values[key] ?? ""}
                        placeholder={placeholder}
                        onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
                      />
                    ) : (
                      <Input
                        id={id}
                        value={values[key] ?? ""}
                        placeholder={placeholder}
                        onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
                      />
                    )}
                    {hint && values[key] === hint.raw ? (
                      <p className="text-[11px] text-muted-foreground">{carriedCaption(hint)} — sprawdź</p>
                    ) : null}
                  </div>
                );
              })}
              {present.length > 0 ? (
                <ul className="space-y-0.5 border-t border-border pt-2 text-xs text-muted-foreground">
                  {present.map((key) => (
                    <li key={key}>
                      <span aria-hidden className="text-success">
                        ✓
                      </span>{" "}
                      {formFieldLabel(state, key)}
                    </li>
                  ))}
                </ul>
              ) : null}
              {error ? (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              ) : null}
            </>
          )}
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="ghost" size="sm" onClick={onOpenFull}>
            Otwórz cały screening
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            type="button"
            size="sm"
            loading={save.isPending}
            disabled={!state || readOnly || !complete}
            onClick={() => void submit()}
          >
            {actionLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
