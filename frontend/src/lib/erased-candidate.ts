/**
 * Adres z nagrobka (decyzja Artura, 03.11.2026): profil z tym adresem trwale
 * usunięto, więc serwer odpowiada 409 `candidate_erased`, a okno pyta rekrutera
 * i ponawia zapis z `confirm_erased`. Nagrobek stoi też po usuniętym duplikacie,
 * dlatego tekst nie mówi o prośbie osoby.
 */

export const ERASED_CANDIDATE_CONFIRM = {
  title: "Ten adres należał do usuniętego profilu",
  description:
    "Profil z tym adresem trwale usunięto. Dodaj osobę tylko wtedy, gdy wiesz, że wróciła do kontaktu.",
  confirmLabel: "Dodaj mimo to",
} as const;

/** Zdanie serwera przy odmowie `candidate_erased`; każdy inny błąd → `null`. */
export function erasedCandidateMessage(error: unknown): string | null {
  const response = (error as { response?: { status?: unknown; data?: unknown } } | null)
    ?.response;
  if (response?.status !== 409) return null;
  const detail = (response.data as { detail?: unknown } | null)?.detail as
    | { code?: unknown; message?: unknown }
    | null
    | undefined;
  if (detail?.code !== "candidate_erased") return null;
  return typeof detail.message === "string"
    ? detail.message
    : ERASED_CANDIDATE_CONFIRM.description;
}
