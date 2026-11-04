"use client";

/**
 * Czy robot Jarvisa wisi w rogu (`prefs.enabled`) — wspólne dla maskotki
 * (przycisk „Schowaj”) i menu „Wygląd” w górnym pasku (przywrócenie).
 * Zmiana od razu w cache, zapis w tle; błąd zapisu cofa stan i mówi o tym.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useOptionalToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { fetchJarvisPrefs, jarvisKeys, saveJarvisPrefs } from "@/lib/jarvis/api";
import type { JarvisPrefsResponse } from "@/lib/jarvis/types";
import { useAuthStore } from "@/store/auth";

/**
 * Robot w rogu: tylko gdy nie jest schowany. Tryb gry trzyma go także bez
 * modelu (panel mówi wtedy, że asystent nie działa), ale nie wbrew „Schowaj”
 * (prośba z 28.10.2026: w trybie gry nie dało się go pozbyć).
 */
export function shouldShowMascot(enabled: boolean, available: boolean, kidsMode: boolean): boolean {
  return enabled && (available || kidsMode);
}

export function useJarvisMascotVisibility(): {
  /** `null`, dopóki preferencje się nie wczytały (albo w trybie „podgląd jako”). */
  visible: boolean | null;
  setVisible: (next: boolean) => void;
} {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const ownSession = useAuthStore((s) => !!s.token && !s.realUser);
  const prefsQuery = useQuery({
    queryKey: jarvisKeys.prefs,
    queryFn: fetchJarvisPrefs,
    enabled: ownSession,
    staleTime: 5 * 60_000,
    retry: 0,
  });
  const save = useMutation({
    mutationFn: (enabled: boolean) => saveJarvisPrefs({ enabled }),
    onMutate: (enabled) => {
      const previous = queryClient.getQueryData<JarvisPrefsResponse>(jarvisKeys.prefs);
      if (previous) queryClient.setQueryData(jarvisKeys.prefs, { ...previous, enabled });
      return { previous };
    },
    onSuccess: (data) => queryClient.setQueryData(jarvisKeys.prefs, data),
    onError: (error, _enabled, context) => {
      if (context?.previous) queryClient.setQueryData(jarvisKeys.prefs, context.previous);
      toast?.showError(apiErrorMessage(error, "Nie udało się zapisać ustawienia asystenta."));
    },
  });
  return {
    visible: ownSession && prefsQuery.data ? prefsQuery.data.enabled : null,
    setVisible: (next) => save.mutate(next),
  };
}
