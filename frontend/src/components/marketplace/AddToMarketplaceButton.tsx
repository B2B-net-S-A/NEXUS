"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Store, X, Check, Loader2, Sparkles } from "lucide-react";
import { marketplaceApi } from "@/lib/api";
import { CandidateMatchesExpansion } from "./CandidateMatchesExpansion";

interface Props {
  candidateId: number;
  candidateName?: string;
  onAdded?: () => void;
  /** Controlled visibility. When provided, the parent owns the open state and
   *  usually hides the built-in trigger via `hideTrigger`. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Hide the built-in "Wrzuć na targ" trigger button — the parent supplies
   *  its own (e.g. a dropdown-menu item that flips `open`). */
  hideTrigger?: boolean;
}

function defaultUntil(): string {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return d.toISOString().slice(0, 10);
}

function formatPlDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function AddToMarketplaceButton({
  candidateId,
  candidateName,
  onAdded,
  open: controlledOpen,
  onOpenChange,
  hideTrigger = false,
}: Props) {
  const queryClient = useQueryClient();
  const [internalOpen, setInternalOpen] = useState(false);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;
  const setOpen = (value: boolean) => {
    onOpenChange?.(value);
    if (!isControlled) setInternalOpen(value);
  };
  const wasOpenRef = useRef(false);
  // "form" — pick expiry date + confirm; "results" — show AI-matched projects.
  const [step, setStep] = useState<"form" | "results">("form");
  const [until, setUntil] = useState<string>(defaultUntil());
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const res = await marketplaceApi.add(candidateId, {
        marketplace_until: until,
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["marketplace-candidates"] });
      // Surface what the candidate was added FOR: the AI-matched open projects.
      // CandidateMatchesExpansion (mounted in the results step) fetches them.
      setStep("results");
      onAdded?.();
    },
    onError: (err: unknown) => {
      const msg =
        err instanceof Error ? err.message : "Nie udało się dodać na targ";
      setError(msg);
    },
  });

  // When the parent opens the modal programmatically (controlled mode bypasses
  // openModal), reset to a fresh form on each closed→open transition so a prior
  // "results" step or stale error never leaks into the next open.
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setStep("form");
      setError(null);
      mutation.reset();
    }
    wasOpenRef.current = open;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const close = () => {
    setOpen(false);
    // Reset for the next open so we always start on the form step.
    setStep("form");
    setError(null);
    mutation.reset();
  };

  const openModal = () => {
    setStep("form");
    setError(null);
    mutation.reset();
    setOpen(true);
  };

  return (
    <>
      {!hideTrigger && (
        <button
          type="button"
          onClick={openModal}
          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg border border-teal-200 bg-teal-50 text-teal-700 hover:bg-teal-100 transition-colors"
        >
          <Store className="w-4 h-4" />
          Wrzuć na targ
        </button>
      )}

      {open && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 p-4">
          <div className="bg-card dark:bg-muted rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border shrink-0">
              <h2 className="text-lg font-bold text-foreground dark:text-foreground flex items-center gap-2">
                <Store className="w-5 h-5 text-teal-600" />
                Wrzuć na targ
              </h2>
              <button
                onClick={close}
                className="text-muted-foreground hover:text-muted-foreground"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {step === "form" ? (
              <div className="p-6 space-y-4 overflow-y-auto">
                <p className="text-sm text-muted-foreground dark:text-muted-foreground">
                  {candidateName ? (
                    <>
                      Kandydat <strong>{candidateName}</strong> zostanie dodany na
                      targ.
                    </>
                  ) : (
                    "Kandydat zostanie dodany na targ."
                  )}{" "}
                  AI od razu przeszuka otwarte projekty i pokaże te, do których
                  pasuje najlepiej — a następnie będzie monitorować nowe oferty i
                  alertować o dopasowaniach (score ≥ 70).
                </p>
                <div>
                  <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                    Ważne do (domyślnie +30 dni)
                  </label>
                  <input
                    type="date"
                    value={until}
                    onChange={(e) => setUntil(e.target.value)}
                    className="h-10 w-full px-3 border border-border dark:border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-card dark:bg-muted dark:text-foreground"
                    min={new Date().toISOString().slice(0, 10)}
                  />
                </div>
                {error && <p className="text-xs text-destructive">{error}</p>}
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={close}
                    className="h-10 px-4 text-sm text-muted-foreground hover:text-foreground rounded-lg"
                    disabled={mutation.isPending}
                  >
                    Anuluj
                  </button>
                  <button
                    type="button"
                    onClick={() => mutation.mutate()}
                    disabled={mutation.isPending}
                    className="inline-flex items-center gap-2 h-10 px-4 bg-teal-600 hover:bg-teal-700 disabled:opacity-60 text-white rounded-lg text-sm font-medium"
                  >
                    {mutation.isPending ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Sparkles className="w-4 h-4" />
                    )}
                    Dodaj i znajdź projekty
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-6 space-y-4 overflow-y-auto">
                <div className="flex items-center gap-2 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800/40 px-3 py-2 text-sm text-green-700 dark:text-green-300">
                  <Check className="w-4 h-4 shrink-0" />
                  <span>
                    Dodano na targ — ważne do{" "}
                    <strong>{formatPlDate(until)}</strong>.
                  </span>
                </div>

                <div>
                  <h3 className="font-medium text-foreground dark:text-foreground flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-purple-500" />
                    Projekty dopasowane przez AI
                  </h3>
                  <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-0.5">
                    AI przeszukał otwarte projekty i wybrał te, do których{" "}
                    {candidateName ? <strong>{candidateName}</strong> : "kandydat"}{" "}
                    pasuje najlepiej. Kliknij projekt, aby przejść do oferty.
                  </p>
                  <CandidateMatchesExpansion candidateId={candidateId} />
                </div>

                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    onClick={close}
                    className="h-10 px-4 text-sm font-medium text-white bg-teal-600 hover:bg-teal-700 rounded-lg"
                  >
                    Zamknij
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
