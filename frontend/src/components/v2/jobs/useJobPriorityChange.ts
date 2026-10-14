"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { rawPriorityForLevel, type PriorityLevel } from "@/lib/request-priority";
import { useToast } from "@/components/Toast";

export interface JobPriorityChange {
  /** Poziom do pokazania — wybór widać od razu, przed odpowiedzią serwera. */
  value: PriorityLevel;
  change: (next: PriorityLevel) => void;
  /** Ile zapisów jest w drodze. */
  saving: boolean;
}

/**
 * Zapis priorytetu rekrutacji (`PATCH /api/jobs/{id} {priority}`) — wspólny dla
 * pola „Priorytet” w panelu „Zespół” i plakietki w nagłówku (14.10.2026).
 *
 * Wybór widać natychmiast (wartość lokalna): strzałki klawiatury wybierają od
 * ręki, więc czekanie na serwer cofałoby zaznaczenie pod palcami. Zapisy idą
 * po kolei, odmowa cofa do ostatniego poziomu potwierdzonego przez serwer.
 */
export function useJobPriorityChange(
  jobId: number,
  level: PriorityLevel,
): JobPriorityChange {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [value, setValue] = useState(level);
  const [inFlight, setInFlight] = useState(0);
  // Wartość z serwera (odświeżona rekrutacja, zmiana innej osoby) wygrywa
  // z lokalną — ale dopiero gdy NAPRAWDĘ się zmieni, nie przy każdym renderze,
  // i nie w trakcie zapisów: odświeżenie po pierwszym zapisie serii cofałoby
  // na chwilę wybór do poziomu ze środka.
  const [seenLevel, setSeenLevel] = useState(level);
  if (level !== seenLevel) {
    setSeenLevel(level);
    if (inFlight === 0) setValue(level);
  }
  // Ostatni poziom potwierdzony przez serwer — do niego wracamy po odmowie.
  const confirmed = useRef(level);
  useEffect(() => {
    confirmed.current = level;
  }, [level]);
  // Ostatnio wybrany poziom: po odmowie cofamy tylko wtedy, gdy to on padł.
  const lastRequested = useRef<PriorityLevel | null>(null);
  // Szybkie przejście P1 → P2 → „Przyjmujemy” nie może skończyć się na
  // serwerze poziomem ze środka.
  const queue = useRef<Promise<void>>(Promise.resolve());

  const change = (next: PriorityLevel) => {
    setValue(next);
    lastRequested.current = next;
    setInFlight((count) => count + 1);
    queue.current = queue.current.then(async () => {
      try {
        await api.patch(`/api/jobs/${jobId}`, {
          priority: rawPriorityForLevel(next),
        });
        confirmed.current = next;
      } catch (err) {
        // Nowszy wybór czeka już w kolejce na swój zapis — jego nie cofamy.
        if (lastRequested.current === next) setValue(confirmed.current);
        toast.showError(apiErrorMessage(err, "Nie udało się zmienić priorytetu."));
      } finally {
        setInFlight((count) => count - 1);
        // Odpowiedź PATCH nie niesie obsady — odświeżamy, nie wkładamy do cache'u.
        invalidateJobTeam(queryClient, jobId);
      }
    });
  };

  return { value, change, saving: inFlight > 0 };
}
