"use client";

/**
 * Nadawanie i zdejmowanie plakietek ostrzeżeń — jedyne miejsce, z którego
 * plakietka w ogóle powstaje.
 *
 * Bez tej kontrolki `user_performance_flags` zostaje pustą tabelą, a cała
 * warstwa ostrzeżeń wygląda na niewdrożoną, mimo że jest.
 *
 * Trzy reguły:
 *
 * 1. **Zdejmujemy, nie kasujemy.** Przycisk mówi „Zdejmij", bo backend
 *    wygasza wiersz (`is_active=false` + data i autor). Historia ocen jest
 *    tym, co czyni je sprawiedliwymi.
 * 2. **Jedna aktywna plakietka danego typu na osobę.** Egzekwuje to częściowy
 *    UNIQUE w bazie; tutaj po prostu nie oferujemy typu, który już wisi —
 *    przycisk gwarantowanie kończący się błędem to gorszy interfejs niż jego
 *    brak.
 * 3. **Ukrycie ≠ bramka.** Zapis stoi na `AdminUser` po stronie serwera;
 *    `isAdmin` tutaj oszczędza reszcie zespołu przycisku, który skończyłby
 *    się 403.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldAlert } from "lucide-react";

import { useAuthStore } from "@/store/auth";
import {
  insightsFlagsApi,
  performanceFlagsQueryKey,
  type PerformanceFlag,
  type PerformanceFlagTypeMeta,
} from "@/lib/insights-flags-api";

/** Treść błędu z serwera albo zapasowe zdanie po polsku. */
function errorText(error: unknown, fallback: string): string {
  const detail = (
    error as { response?: { data?: { detail?: unknown } } } | undefined
  )?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  return fallback;
}

interface Props {
  userId: number;
  /** Nazwisko do etykiet dostępności — wiersz bez konta ma `null`. */
  userName: string | null;
  /** Plakietki AKTYWNE tej osoby; puste = można nadać każdy typ. */
  flags: PerformanceFlag[];
  types: PerformanceFlagTypeMeta[];
}

/** Typy, których jeszcze nie ma na osobie — tylko te wolno zaproponować. */
export function assignableTypes(
  types: PerformanceFlagTypeMeta[],
  flags: PerformanceFlag[],
): PerformanceFlagTypeMeta[] {
  const taken = new Set(flags.map((f) => f.flag_type));
  return types.filter((t) => !taken.has(t.value));
}

export function InsightsFlagAdmin({ userId, userName, flags, types }: Props) {
  const user = useAuthStore((s) => s.user);
  const isAdmin =
    user?.role === "admin" || Boolean(user?.roles?.includes("admin"));

  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: performanceFlagsQueryKey });

  const createMutation = useMutation({
    mutationFn: (flagType: PerformanceFlagTypeMeta["value"]) =>
      insightsFlagsApi.create({
        user_id: userId,
        flag_type: flagType,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      setNote("");
      setError(null);
      setOpen(false);
      invalidate();
    },
    // Bez tej gałęzi nieudane nadanie plakietki nie robi NIC widocznego:
    // panel zostaje otwarty i pusty, więc odmowa serwera czyta się jako
    // „przycisk nie działa".
    onError: (e) => setError(errorText(e, "Nie udało się nadać ostrzeżenia.")),
  });

  const clearMutation = useMutation({
    mutationFn: (flagId: number) => insightsFlagsApi.clear(flagId),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e) => setError(errorText(e, "Nie udało się zdjąć ostrzeżenia.")),
  });

  if (!isAdmin) return null;

  const label = userName ?? `użytkownika #${userId}`;
  const available = assignableTypes(types, flags);
  const busy = createMutation.isPending || clearMutation.isPending;

  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`Zarządzaj ostrzeżeniami — ${label}`}
        className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
      >
        {busy ? (
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        ) : (
          <ShieldAlert className="h-3 w-3" aria-hidden="true" />
        )}
        Ostrzeżenia
      </button>

      {open && (
        <div className="mt-1 space-y-1 rounded-md border border-border bg-background p-2">
          {flags.map((flag) => (
            <div key={flag.id} className="flex items-center gap-2 text-[11px]">
              <span className="text-foreground">{flag.label}</span>
              <button
                type="button"
                className="rounded border border-border px-1.5 py-0.5 text-muted-foreground hover:bg-muted"
                onClick={() => clearMutation.mutate(flag.id)}
                disabled={busy}
              >
                Zdejmij
              </button>
            </div>
          ))}

          {available.length === 0 ? (
            // Komplet plakietek to WYNIK, nie usterka — mówimy to zdaniem,
            // zamiast zostawiać puste pole pod nagłówkiem.
            <p className="text-[11px] text-muted-foreground">
              Wszystkie typy ostrzeżeń są już nadane.
            </p>
          ) : (
            <>
              <input
                aria-label={`Komentarz do ostrzeżenia — ${label}`}
                placeholder="Komentarz (opcjonalny)"
                className="w-full rounded border border-border bg-background px-1.5 py-0.5 text-[11px]"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <div className="flex flex-wrap gap-1">
                {available.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    title={t.description}
                    className="rounded border border-border px-1.5 py-0.5 text-[11px] text-foreground hover:bg-muted"
                    onClick={() => createMutation.mutate(t.value)}
                    disabled={busy}
                  >
                    Nadaj: {t.label}
                  </button>
                ))}
              </div>
            </>
          )}

          {error && (
            <p role="alert" className="text-[11px] text-destructive">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
