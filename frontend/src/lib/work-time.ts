/**
 * Miesiąc roboczy w przeliczeniach stawek — JEDNA stała dla całego frontendu.
 *
 * Decyzja z 22.09.2026 (audyt statystyk): stawkę godzinową i dzienną
 * przeliczamy na kwotę miesięczną zawsze tym samym miesiącem roboczym —
 * 21 MD × 8 h = 168 h. Dotyczy MRR, marży, przychodu, prognoz, analityki i UI.
 * Do tej daty obok siebie żyły 160 h (domyślne godziny kontraktu i zamówienia),
 * 176 h (kontrakt przeliczony z MD) i 22 MD — ta sama stawka dawała MRR różny
 * o ~10%.
 *
 * Lustro backendu: `backend/app/core/work_time.py` (test
 * `work-time.test.ts` pilnuje zgodności liczb).
 */

/** 1 MD (dzień roboczy) = 8 godzin. */
export const HOURS_PER_MD = 8;
/** Miesiąc roboczy = 21 MD. */
export const MD_PER_MONTH = 21;
/** Miesiąc roboczy w godzinach = 21 × 8 = 168. */
export const HOURS_PER_MONTH = MD_PER_MONTH * HOURS_PER_MD;
