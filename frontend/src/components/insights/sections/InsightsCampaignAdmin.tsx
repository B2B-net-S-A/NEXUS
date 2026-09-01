"use client";

/**
 * Zarządzanie kampanią rekrutacyjną — jedyne miejsce, z którego baner
 * w ogóle powstaje.
 *
 * Bez tego panelu backend kampanii jest martwy: `GET /active` zwraca `null`,
 * baner się nie renderuje i cała funkcja wygląda na niewdrożoną, mimo że
 * jest. Tabela + formularz w jednym miejscu, bo kampanii jest kilka na rok
 * i osobny ekran ustawień byłby dla nich pustą podróżą.
 *
 * Trzy rzeczy, których ten panel nie robi i nie może zacząć robić:
 *
 * 1. **Nie udaje bramki.** Ukrycie przycisku nie jest zabezpieczeniem — zapis
 *    stoi na `AdminUser` po stronie serwera. Warunek `isAdmin` tutaj oszczędza
 *    reszcie zespołu przycisku, który i tak skończyłby się 403.
 * 2. **Nie „naprawia" odwróconego okna po cichu.** Data końca przed startem
 *    jest odrzucana z komunikatem; przestawienie ich miejscami zapisałoby
 *    kampanię, której nikt nie zaplanował (CHECK w bazie i tak by to odbił,
 *    ale komunikat po polsku jest lepszy niż 500).
 * 3. **Nie zarządza aktywnością na dwóch kampaniach naraz.** Serwer gasi
 *    pozostałe przy każdym włączeniu — panel to POKAZUJE (znacznik przy
 *    aktywnej), zamiast pozwalać kliknąć dwie i zgadywać, która wygra.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Megaphone, Plus, Trash2 } from "lucide-react";

import { useAuthStore } from "@/store/auth";
import {
  insightsCampaignApi,
  insightsCampaignQueryKeys,
  type InsightsCampaignListItem,
} from "@/lib/insights-campaign-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";

const EMPTY_FORM = {
  name: "",
  emoji: "",
  start_date: "",
  end_date: "",
  target_net: "0",
};

type FormState = typeof EMPTY_FORM;

/** Komunikat albo `null`, gdy formularz da się wysłać. */
export function validateCampaignForm(form: FormState): string | null {
  if (!form.name.trim()) return "Kampania musi mieć nazwę.";
  if (!form.start_date || !form.end_date) return "Podaj obie daty kampanii.";
  if (form.end_date < form.start_date) {
    return "Data końca jest wcześniejsza niż data startu.";
  }
  const target = Number(form.target_net);
  if (!Number.isFinite(target) || !Number.isInteger(target) || target < 0) {
    return "Cel netto musi być liczbą całkowitą nie mniejszą niż zero.";
  }
  return null;
}

function errorText(error: unknown, fallback: string): string {
  const detail = (
    error as { response?: { data?: { detail?: unknown } } } | undefined
  )?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  return fallback;
}

export function InsightsCampaignAdmin() {
  const user = useAuthStore((s) => s.user);
  const isAdmin =
    user?.role === "admin" || Boolean(user?.roles?.includes("admin"));

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const listQuery = useQuery({
    queryKey: insightsCampaignQueryKeys.list(),
    queryFn: () => insightsCampaignApi.list(),
    // Lista jest admin-only; dla reszty zespołu nie ma po co ruszać sieci.
    enabled: isAdmin && open,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: insightsCampaignQueryKeys.list(),
    });
    // Baner czyta INNY klucz — bez tego zmiana zapisuje się w bazie i nie
    // pokazuje na ekranie aż do przeładowania strony.
    void queryClient.invalidateQueries({
      queryKey: insightsCampaignQueryKeys.active(),
    });
  };

  const createMutation = useMutation({
    mutationFn: () =>
      insightsCampaignApi.create({
        name: form.name.trim(),
        emoji: form.emoji.trim() || null,
        start_date: form.start_date,
        end_date: form.end_date,
        target_net: Number(form.target_net),
        is_active: true,
      }),
    onSuccess: () => {
      setForm(EMPTY_FORM);
      setFormError(null);
      invalidate();
    },
    onError: (error) =>
      setFormError(errorText(error, "Nie udało się zapisać kampanii.")),
  });

  // Obie mutacje raportują błąd w to samo miejsce co formularz. Bez tego
  // nieudane przełączenie banera nie robi NIC widocznego — panel wygląda
  // dokładnie tak jak przed kliknięciem, więc awaria czyta się jako
  // „przycisk nie działa", a nie jako „serwer odmówił".
  const toggleMutation = useMutation({
    mutationFn: (campaign: InsightsCampaignListItem) =>
      insightsCampaignApi.update(campaign.id, {
        is_active: !campaign.is_active,
      }),
    onSuccess: () => {
      setFormError(null);
      invalidate();
    },
    onError: (error) =>
      setFormError(errorText(error, "Nie udało się przełączyć banera.")),
  });

  const deleteMutation = useMutation({
    mutationFn: (campaign: InsightsCampaignListItem) =>
      insightsCampaignApi.remove(campaign.id),
    onSuccess: () => {
      setFormError(null);
      invalidate();
    },
    onError: (error) =>
      setFormError(errorText(error, "Nie udało się usunąć kampanii.")),
  });

  const viewState = resolveViewState({
    isLoading: listQuery.isPending,
    isSuccess: listQuery.isSuccess,
    isError: listQuery.isError,
    error: listQuery.error,
    isEmpty: (listQuery.data?.campaigns.length ?? 0) === 0,
  });

  const campaigns = useMemo(
    () => listQuery.data?.campaigns ?? [],
    [listQuery.data],
  );

  if (!isAdmin) return null;

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-sm font-medium text-foreground"
        aria-expanded={open}
      >
        <Megaphone className="h-4 w-4 text-primary" aria-hidden="true" />
        Kampanie rekrutacyjne
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          {open ? "Zwiń" : "Zarządzaj"}
        </span>
      </button>

      {open && (
        <div className="mt-4 space-y-4">
          {viewState === "loading" ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Wczytuję kampanie…
            </div>
          ) : isBlockingViewState(viewState) ? (
            <SectionError
              label="Kampanie"
              error={listQuery.error}
              onRetry={() => void listQuery.refetch()}
            />
          ) : campaigns.length === 0 ? (
            // „Brak kampanii" to normalny stan świata, nie usterka — dlatego
            // zdanie, a nie pudełko błędu.
            <p className="text-xs text-muted-foreground">
              Nie ma jeszcze żadnej kampanii. Załóż pierwszą poniżej.
            </p>
          ) : (
            <ul className="divide-y divide-border/60 text-sm">
              {campaigns.map((c) => (
                <li
                  key={c.id}
                  className="flex flex-wrap items-center gap-2 py-2"
                >
                  <span className="text-foreground">
                    {c.emoji ? `${c.emoji} ` : ""}
                    {c.name}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {c.start_date} → {c.end_date} · cel {c.target_net}
                  </span>
                  {c.is_active && (
                    <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                      aktywna
                    </span>
                  )}
                  <span className="ml-auto flex items-center gap-2">
                    <button
                      type="button"
                      className="rounded-md border border-border px-2 py-1 text-xs text-foreground hover:bg-muted"
                      onClick={() => toggleMutation.mutate(c)}
                      disabled={toggleMutation.isPending}
                    >
                      {c.is_active ? "Wyłącz baner" : "Pokaż baner"}
                    </button>
                    <button
                      type="button"
                      aria-label={`Usuń kampanię ${c.name}`}
                      className="rounded-md border border-border p-1 text-muted-foreground hover:bg-muted"
                      onClick={() => deleteMutation.mutate(c)}
                      disabled={deleteMutation.isPending}
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}

          <form
            className="grid grid-cols-1 gap-2 sm:grid-cols-6"
            onSubmit={(e) => {
              e.preventDefault();
              const problem = validateCampaignForm(form);
              setFormError(problem);
              if (problem === null) createMutation.mutate();
            }}
          >
            <input
              aria-label="Nazwa kampanii"
              placeholder="Nazwa kampanii"
              className="rounded-md border border-border bg-background px-2 py-1 text-sm sm:col-span-2"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <input
              aria-label="Emoji"
              placeholder="Emoji"
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
              value={form.emoji}
              onChange={(e) => setForm({ ...form, emoji: e.target.value })}
            />
            <input
              aria-label="Data startu"
              type="date"
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
              value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
            />
            <input
              aria-label="Data końca"
              type="date"
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
              value={form.end_date}
              onChange={(e) => setForm({ ...form, end_date: e.target.value })}
            />
            <input
              aria-label="Cel netto"
              type="number"
              min={0}
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
              value={form.target_net}
              onChange={(e) => setForm({ ...form, target_net: e.target.value })}
            />
            <button
              type="submit"
              className="inline-flex items-center justify-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-60 sm:col-span-2"
              disabled={createMutation.isPending}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Załóż i pokaż baner
            </button>
          </form>

          {formError && (
            <p role="alert" className="text-xs text-destructive">
              {formError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
