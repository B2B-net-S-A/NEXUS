"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Store, X, Check, Loader2 } from "lucide-react";
import { marketplaceApi } from "@/lib/api";

interface Props {
  candidateId: number;
  candidateName?: string;
  onAdded?: () => void;
}

function defaultUntil(): string {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return d.toISOString().slice(0, 10);
}

export function AddToMarketplaceButton({
  candidateId,
  candidateName,
  onAdded,
}: Props) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
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
      setOpen(false);
      onAdded?.();
    },
    onError: (err: unknown) => {
      const msg =
        err instanceof Error ? err.message : "Nie udało się dodać na targ";
      setError(msg);
    },
  });

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg border border-teal-200 bg-teal-50 text-teal-700 hover:bg-teal-100 transition-colors"
      >
        <Store className="w-4 h-4" />
        Wrzuć na targ
      </button>

      {open && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-700">
              <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 flex items-center gap-2">
                <Store className="w-5 h-5 text-teal-600" />
                Wrzuć na targ
              </h2>
              <button
                onClick={() => setOpen(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-gray-600 dark:text-gray-300">
                {candidateName ? (
                  <>
                    Kandydat <strong>{candidateName}</strong> zostanie dodany na targ.
                  </>
                ) : (
                  "Kandydat zostanie dodany na targ."
                )}
                {" "}
                AI będzie monitorować nowe oferty i alertować o dopasowaniach
                (score ≥ 70).
              </p>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                  Ważne do (domyślnie +30 dni)
                </label>
                <input
                  type="date"
                  value={until}
                  onChange={(e) => setUntil(e.target.value)}
                  className="h-10 w-full px-3 border border-gray-200 dark:border-gray-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-white dark:bg-gray-700 dark:text-gray-100"
                  min={new Date().toISOString().slice(0, 10)}
                />
              </div>
              {error && (
                <p className="text-xs text-red-600">{error}</p>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="h-10 px-4 text-sm text-gray-600 hover:text-gray-800 rounded-lg"
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
                    <Check className="w-4 h-4" />
                  )}
                  Dodaj
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
