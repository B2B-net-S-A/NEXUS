"use client";

import { useEffect, useState } from "react";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import {
  clearJobDraft,
  readJobDraft,
  writeJobDraft,
  type JobDraftFormState,
  type RestorableJobDraft,
} from "@/lib/job-draft-storage";

interface UseJobDraftOptions {
  userId: number | string | null | undefined;
  form: JobDraftFormState;
  /**
   * Autosave i odczyt zapisanego szkicu są wyłączone dla „Skopiuj jako
   * template" (`fromJobId != null` w `CreateJobModal`) — kopia istniejącej
   * roli nie jest niezapisanym szkicem, który trzeba przywrócić między
   * sesjami.
   */
  enabled: boolean;
}

interface UseJobDraftResult {
  /** Zapisany szkic odczytany RAZ, gdy `userId` stanie się znane. */
  restorable: RestorableJobDraft | null;
  /** Po „Przywróć szkic" — chowa baner; formularz (już przywrócony przez
   *  wołającego) zostaje dalej pod autosave'em. */
  acceptRestorable: () => void;
  /** Kasuje zapisany szkic i chowa baner — po „Odrzuć" i po udanym zapisie. */
  clear: () => void;
}

export function useJobDraft({
  userId,
  form,
  enabled,
}: UseJobDraftOptions): UseJobDraftResult {
  // Odczyt SYNCHRONICZNY w lazy initializerze (faza renderu), nie w efekcie.
  // Efekty z tego samego commitu wykonują się w kolejności deklaracji, ale
  // stan ustawiony PRZEZ jeden z nich nie jest widoczny w domknięciach
  // pozostałych efektów TEGO SAMEGO commitu — React stosuje go dopiero przy
  // kolejnym renderze. Odczyt-w-efekcie + autosave-w-efekcie na tym samym
  // mouncie dawał więc realny wyścig: pierwszy commit uruchamiał OBA efekty
  // z `restorable` wciąż `null` (autosave nie widział jeszcze świeżo
  // odczytanego szkicu) i pusty formularz kasował plik w `localStorage`,
  // zanim DL zobaczył baner „Przywróć szkic" (zmierzone testem regresyjnym
  // w `CreateJobModalDraft.test.tsx`). Lazy initializer nie ma tego problemu
  // — liczy się PRZED pierwszym przebiegiem jakiegokolwiek efektu.
  const [restorable, setRestorable] = useState<RestorableJobDraft | null>(
    () => (enabled && userId != null ? readJobDraft(userId) : null),
  );

  const debouncedForm = useDebouncedValue(form, 500);
  useEffect(() => {
    // Nierozstrzygnięta oferta przywrócenia nie może być nadpisana — pierwszy
    // debounce PUSTEGO formularza (modal właśnie się otworzył) skasowałby
    // zapisany szkic, zanim DL zdąży kliknąć „Przywróć szkic".
    if (!enabled || userId == null || restorable) return;
    writeJobDraft(userId, debouncedForm);
  }, [debouncedForm, enabled, userId, restorable]);

  return {
    restorable: enabled ? restorable : null,
    acceptRestorable: () => setRestorable(null),
    clear: () => {
      if (userId != null) clearJobDraft(userId);
      setRestorable(null);
    },
  };
}
