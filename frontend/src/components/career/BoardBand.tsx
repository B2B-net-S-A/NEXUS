import type { ReactNode } from "react";

import { careerTheme, isCareerThemeId, DEFAULT_CAREER_THEME, type ThemePalette } from "./themes";

/**
 * Pasek sceny na karcie tablicy (makieta 6b): tło i dwa kolory szablonu
 * rekrutacji, motyw jego sceny. Rysunek jest ozdobą (`aria-hidden`); nazwa
 * sceny i kategoria są tekstem w kolorach szablonu, które `themes.ts` trzyma
 * na ≥ 4,5:1 do tła (pilnuje `__tests__/board.test.ts`).
 */
type Motif = (p: ThemePalette) => ReactNode;

const MOTIFS: Record<string, Motif> = {
  terminal: (p) => (
    <g>
      <rect x="18" y="40" width="7" height="12" fill={p.accent} />
      <rect x="32" y="44" width="120" height="4" fill={p.muted} opacity=".5" />
      <rect x="32" y="62" width="180" height="4" fill={p.muted} opacity=".35" />
      <rect x="32" y="78" width="90" height="4" fill={p.accent} opacity=".7" />
    </g>
  ),
  sekwencja: (p) => (
    <g fill="none" strokeWidth="1.5">
      <g stroke={p.muted} opacity=".55">
        <line x1="50" y1="30" x2="50" y2="96" />
        <line x1="160" y1="30" x2="160" y2="96" />
        <line x1="270" y1="30" x2="270" y2="96" />
      </g>
      <g stroke={p.accent}>
        <path d="M50 46 H160" />
        <path d="M160 64 H270" />
        <path d="M270 82 H50" strokeDasharray="4 3" />
      </g>
    </g>
  ),
  glitch: (p) => (
    <g>
      <rect x="0" y="34" width="320" height="8" fill={p.decor} opacity=".75" />
      <rect x="40" y="54" width="190" height="5" fill={p.accent} opacity=".7" />
      <rect x="120" y="72" width="180" height="10" fill={p.text} opacity=".15" />
    </g>
  ),
  konstelacja: (p) => (
    <g>
      <g stroke={p.decor} strokeWidth="1" opacity=".7">
        <line x1="40" y1="44" x2="90" y2="76" />
        <line x1="90" y1="76" x2="150" y2="38" />
        <line x1="150" y1="38" x2="210" y2="82" />
        <line x1="210" y1="82" x2="270" y2="50" />
      </g>
      <g fill={p.accent}>
        <circle cx="40" cy="44" r="2.5" />
        <circle cx="90" cy="76" r="3" />
        <circle cx="150" cy="38" r="2.5" />
        <circle cx="210" cy="82" r="3.5" />
        <circle cx="270" cy="50" r="2.5" />
      </g>
    </g>
  ),
  c4: (p) => (
    <g fill="none" strokeWidth="1.3">
      <g stroke={p.decor}>
        <rect x="24" y="36" width="78" height="26" rx="3" />
        <rect x="124" y="36" width="78" height="26" rx="3" />
        <rect x="224" y="36" width="78" height="26" rx="3" />
        <rect x="124" y="72" width="78" height="20" rx="3" />
      </g>
      <g stroke={p.accent}>
        <line x1="102" y1="49" x2="124" y2="49" />
        <line x1="202" y1="49" x2="224" y2="49" />
        <line x1="163" y1="62" x2="163" y2="72" />
      </g>
    </g>
  ),
  topologia: (p) => (
    <g>
      <g stroke={p.decor} strokeWidth="1" opacity=".8">
        <line x1="60" y1="62" x2="150" y2="40" />
        <line x1="60" y1="62" x2="150" y2="84" />
        <line x1="150" y1="40" x2="250" y2="62" />
        <line x1="150" y1="84" x2="250" y2="62" />
      </g>
      <g fill={p.bg} stroke={p.accent} strokeWidth="1.5">
        <circle cx="60" cy="62" r="8" />
        <circle cx="150" cy="40" r="7" />
        <circle cx="150" cy="84" r="7" />
        <circle cx="250" cy="62" r="9" />
      </g>
    </g>
  ),
  tablica: (p) => (
    <g>
      <rect x="30" y="38" width="44" height="40" fill={p.accent} opacity=".85" transform="rotate(-4 52 58)" />
      <rect x="96" y="44" width="44" height="40" fill={p.decor} opacity=".8" transform="rotate(3 118 64)" />
      <rect x="162" y="36" width="44" height="40" fill={p.accent} opacity=".6" transform="rotate(-2 184 56)" />
      <rect x="228" y="46" width="44" height="40" fill={p.decor} opacity=".55" transform="rotate(5 250 66)" />
    </g>
  ),
  plan: (p) => (
    <g>
      <rect x="24" y="38" width="110" height="9" rx="2" fill={p.accent} />
      <rect x="96" y="56" width="130" height="9" rx="2" fill={p.decor} />
      <rect x="180" y="74" width="110" height="9" rx="2" fill={p.accent} opacity=".7" />
    </g>
  ),
  papier: (p) => (
    <g>
      <g stroke={p.line} strokeWidth="1">
        <line x1="0" y1="46" x2="320" y2="46" />
        <line x1="0" y1="64" x2="320" y2="64" />
        <line x1="0" y1="82" x2="320" y2="82" />
      </g>
      <g fill="none" stroke={p.decor} strokeWidth="1.5">
        <rect x="24" y="36" width="10" height="10" />
        <rect x="24" y="54" width="10" height="10" />
      </g>
      <path d="M26 41 l3 3 l5 -6" fill="none" stroke={p.accent} strokeWidth="2" />
      <rect x="44" y="39" width="140" height="4" fill={p.muted} opacity=".6" />
      <rect x="44" y="57" width="100" height="4" fill={p.muted} opacity=".6" />
    </g>
  ),
  radar: (p) => (
    <g fill="none">
      <g stroke={p.accent} opacity=".5">
        <circle cx="160" cy="96" r="24" />
        <circle cx="160" cy="96" r="46" />
        <circle cx="160" cy="96" r="68" />
      </g>
      <line x1="160" y1="96" x2="214" y2="44" stroke={p.accent} strokeWidth="1.5" />
      <circle cx="196" cy="62" r="3.5" fill={p.decor} />
    </g>
  ),
  horyzont: (p) => (
    <g>
      <circle cx="160" cy="72" r="22" fill={p.accent} opacity=".85" />
      <rect x="0" y="72" width="320" height="24" fill={p.bg} />
      <g stroke={p.decor} strokeWidth="1" opacity=".7">
        <line x1="0" y1="74" x2="320" y2="74" />
        <line x1="0" y1="82" x2="320" y2="82" />
        <line x1="0" y1="92" x2="320" y2="92" />
        <line x1="160" y1="74" x2="40" y2="96" />
        <line x1="160" y1="74" x2="280" y2="96" />
      </g>
    </g>
  ),
  szafa: (p) => (
    <g>
      {[38, 54, 70].map((y) => (
        <g key={y}>
          <rect x="90" y={y} width="140" height="12" fill="none" stroke={p.muted} strokeWidth="1" opacity=".6" />
          <circle cx="102" cy={y + 6} r="2.2" fill={p.decor} />
          <circle cx="110" cy={y + 6} r="2.2" fill={y === 54 ? p.accent : p.decor} />
        </g>
      ))}
    </g>
  ),
};

export function BoardBand({ theme, category }: { theme: string; category: string | null }) {
  const id = isCareerThemeId(theme) ? theme : DEFAULT_CAREER_THEME;
  const p = careerTheme(id);
  return (
    <div className="kr-board-band" style={{ background: p.bg, borderColor: p.line }}>
      <svg
        className="kr-board-art"
        viewBox="0 0 320 96"
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
        focusable="false"
      >
        {MOTIFS[id](p)}
      </svg>
      <span className="kr-board-scene" style={{ color: p.muted, background: p.bg }}>
        {p.label.toLocaleLowerCase("pl-PL")}
      </span>
      {category ? (
        <span
          className="kr-board-cat"
          style={{ color: p.text, background: p.bg, borderColor: p.muted }}
        >
          {category}
        </span>
      ) : null}
    </div>
  );
}
