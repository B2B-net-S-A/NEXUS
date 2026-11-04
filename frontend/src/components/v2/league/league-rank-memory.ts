/**
 * Miejsce w lidze z pierwszego widoku dnia — do strzałki awansu („↑ z 6.”).
 *
 * Wygoda jednej przeglądarki, nie stan: pamięć bywa pusta (okno prywatne,
 * wyczyszczone dane), a wtedy strzałki po prostu nie ma. Spadku nie
 * pokazujemy wcale (decyzja Artura 13.10.2026), więc pamięć służy tylko
 * do porównania „teraz lepiej niż rano”.
 */

const KEY_PREFIX = "nexus:league-rank:";

interface StoredRank {
  day: string;
  league: string;
  rank: number | null;
}

/** Bezpieczny dostęp — sam odczyt `window.localStorage` potrafi rzucić. */
export function leagueRankStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function read(storage: Storage, key: string): StoredRank | null {
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredRank>;
    if (typeof parsed.day !== "string" || typeof parsed.league !== "string") return null;
    const rank = typeof parsed.rank === "number" ? parsed.rank : null;
    return { day: parsed.day, league: parsed.league, rank };
  } catch {
    return null;
  }
}

/**
 * Miejsce, od którego liczy się dzisiejszy awans.
 *
 * Pierwszy widok dnia (albo nowej ligi lub kwartału) zapisuje bieżące miejsce
 * i je zwraca, kolejne zwracają zapisane. `league` to typ i okres ligi
 * („quarterly_champions_recruiter:Q4 2026”) — nowy kwartał zaczyna od zera.
 */
export function dayBaselineRank(
  storage: Storage | null,
  userId: number,
  league: string,
  rank: number | null,
  today: string,
): number | null {
  if (!storage) return null;
  const key = `${KEY_PREFIX}${userId}`;
  const stored = read(storage, key);
  if (stored && stored.day === today && stored.league === league) return stored.rank;
  try {
    storage.setItem(key, JSON.stringify({ day: today, league, rank } satisfies StoredRank));
  } catch {
    // Pełna albo zablokowana pamięć — bez strzałki, reszta działa.
  }
  return rank;
}
