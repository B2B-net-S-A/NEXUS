/**
 * Identyfikatory światów wyglądu. Lustro po stronie serwera:
 * `backend/app/services/appearance_prefs.py` (`WORLD_IDS`) — test
 * `backend/tests/test_appearance_prefs.py` porównuje obie listy, bo serwer
 * odrzuca zapis świata, którego nie zna. `game` = tryb gry, `none` = bez świata.
 * Reguła: `docs/claude/ui/swiaty-wygladu.md`.
 */
export const WORLD_IDS = [
  "none",
  "game",
  "arcade",
  "stadium",
  "space",
  "zen",
  "winter",
  "retro",
  "sakura",
  "latte",
  "lavender",
  "botanic",
  "marble",
  "sunset",
  "holo",
  "tulips",
  "pitstop",
  "rgb",
  "mountains",
  "blueprint",
] as const;

export type AccountWorldId = (typeof WORLD_IDS)[number];

export function isAccountWorldId(value: unknown): value is AccountWorldId {
  return typeof value === "string" && (WORLD_IDS as readonly string[]).includes(value);
}
