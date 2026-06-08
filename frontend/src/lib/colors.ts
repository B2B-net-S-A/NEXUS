/**
 * Shared color sets. Centralized here to kill the duplicated, drifting
 * `AVATAR_COLORS` arrays that previously lived inline in several components
 * (and still referenced the retired `violet` brand color).
 */

/**
 * Decorative avatar background classes. `bg-primary` follows the active accent;
 * the rest are fixed, distinguishable hues for visual variety. Deterministic
 * per name via {@link getAvatarColor}.
 */
export const AVATAR_COLORS = [
  "bg-primary",
  "bg-indigo-600",
  "bg-emerald-600",
  "bg-rose-500",
  "bg-amber-500",
  "bg-cyan-600",
] as const;

/** Deterministic avatar background class derived from a name/identifier. */
export function getAvatarColor(name: string | null | undefined): string {
  const a = name?.charCodeAt(0) ?? 0;
  const b = name && name.length > 1 ? name.charCodeAt(1) : 0;
  return AVATAR_COLORS[(a + b) % AVATAR_COLORS.length];
}
