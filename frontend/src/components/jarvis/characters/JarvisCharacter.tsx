/**
 * Postaci Jarvisa — gotowe ilustracje (decyzja 21.09.2026), inline SVG.
 *
 * Kolory NIE są wpisane w rysunek: klasy `j-*` (globals.css, sekcja „Jarvis”)
 * biorą akcent z `--jarvis-accent`, więc postać chodzi za paletą, trybem
 * ciemnym i akcentem wybranym przez użytkownika. Bez gradientów z `id` — dwie
 * postaci na jednym ekranie (panel + galeria) nie mogą się pogryźć.
 *
 * Klasy animacji: `j-eye` mruga, `j-arm` macha, `j-glow` pulsuje. Nastrój
 * (`idle`, `thinking`…) steruje klasą na opakowaniu.
 *
 * Lista postaci musi zgadzać się z `JarvisCharacter` w
 * `backend/app/services/jarvis/prefs.py` (pilnuje test characters.test.ts).
 */

import type { CSSProperties, ReactElement } from "react";
import type { JarvisAccent, JarvisCharacterId, JarvisMood } from "@/lib/jarvis/types";

export const JARVIS_CHARACTERS: ReadonlyArray<{
  id: JarvisCharacterId;
  label: string;
  unlockable?: boolean;
}> = [
  { id: "robot", label: "Robot Jarvis" },
  { id: "owl", label: "Sowa" },
  { id: "cat", label: "Kot" },
  { id: "ghost", label: "Duszek" },
  { id: "rocket", label: "Rakieta" },
  { id: "star", label: "Gwiazdka" },
  { id: "dragon", label: "Smok" },
  { id: "astronaut", label: "Astronauta" },
  { id: "robot_gold", label: "Złoty Jarvis", unlockable: true },
  { id: "trophy", label: "Puchar", unlockable: true },
];

export const JARVIS_ACCENTS: ReadonlyArray<{ id: JarvisAccent; label: string; color: string }> = [
  { id: "primary", label: "Jak aplikacja", color: "hsl(var(--primary))" },
  { id: "violet", label: "Fiolet", color: "hsl(263 70% 55%)" },
  { id: "blue", label: "Niebieski", color: "hsl(221 83% 55%)" },
  { id: "green", label: "Zielony", color: "hsl(152 60% 40%)" },
  { id: "orange", label: "Pomarańczowy", color: "hsl(24 90% 52%)" },
  { id: "rose", label: "Różowy", color: "hsl(346 77% 55%)" },
  { id: "graphite", label: "Grafit", color: "hsl(230 10% 40%)" },
];

export function accentColor(accent: JarvisAccent | undefined): string {
  return JARVIS_ACCENTS.find((a) => a.id === accent)?.color ?? "hsl(var(--primary))";
}

interface Props {
  id: JarvisCharacterId;
  accent?: JarvisAccent;
  mood?: JarvisMood;
  size?: number;
  className?: string;
  title?: string;
}

export function JarvisCharacter({ id, accent = "primary", mood = "idle", size = 72, className, title }: Props) {
  const style = { "--jarvis-accent": accentColor(accent) } as CSSProperties;
  const Art = ART[id] ?? ART.robot;
  return (
    <span
      className={`jarvis-art jarvis-mood-${mood} inline-block ${className ?? ""}`}
      style={style}
      data-character={id}
      data-mood={mood}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label={title ?? JARVIS_CHARACTERS.find((c) => c.id === id)?.label ?? "Jarvis"}
      >
        <Art />
      </svg>
    </span>
  );
}

function Eyes({ cx1, cx2, cy, r = 5 }: { cx1: number; cx2: number; cy: number; r?: number }) {
  return (
    <g className="j-eye">
      <circle cx={cx1} cy={cy} r={r} className="j-ink" />
      <circle cx={cx2} cy={cy} r={r} className="j-ink" />
      <circle cx={cx1 + r * 0.35} cy={cy - r * 0.4} r={r * 0.35} className="j-white" />
      <circle cx={cx2 + r * 0.35} cy={cy - r * 0.4} r={r * 0.35} className="j-white" />
    </g>
  );
}

function Smile({ x, y, w = 12 }: { x: number; y: number; w?: number }) {
  return (
    <path
      d={`M${x - w / 2} ${y} Q${x} ${y + w * 0.55} ${x + w / 2} ${y}`}
      className="j-stroke-ink"
      strokeWidth={3}
      strokeLinecap="round"
      fill="none"
    />
  );
}

function Cheeks({ x1, x2, y }: { x1: number; x2: number; y: number }) {
  return (
    <g>
      <ellipse cx={x1} cy={y} rx={4} ry={2.6} className="j-blush" />
      <ellipse cx={x2} cy={y} rx={4} ry={2.6} className="j-blush" />
    </g>
  );
}

function Robot({ gold = false }: { gold?: boolean }) {
  const body = gold ? "j-gold" : "j-accent";
  const deep = gold ? "j-gold-deep" : "j-deep";
  return (
    <g>
      <line x1="50" y1="10" x2="50" y2="22" className="j-stroke-deep" strokeWidth={3} strokeLinecap="round" />
      <circle cx="50" cy="9" r="5" className="j-glow j-warm" />
      {gold && (
        <path d="M36 20 L40 11 L45 17 L50 8 L55 17 L60 11 L64 20 Z" className="j-gold-deep" />
      )}
      <rect x="22" y="22" width="56" height="44" rx="16" className={body} />
      <rect x="30" y="31" width="40" height="24" rx="11" className="j-screen" />
      <Eyes cx1={41} cx2={59} cy={42} r={4.5} />
      <Smile x={50} y={49} w={10} />
      <rect x="15" y="36" width="8" height="14" rx="4" className={deep} />
      <rect x="77" y="36" width="8" height="14" rx="4" className={deep} />
      <rect x="34" y="68" width="32" height="20" rx="9" className={body} />
      <circle cx="50" cy="78" r="4" className="j-glow j-warm" />
      <rect x="22" y="70" width="10" height="7" rx="3.5" className={`${deep} j-arm`} />
      <rect x="68" y="70" width="10" height="7" rx="3.5" className={deep} />
    </g>
  );
}

function Owl() {
  return (
    <g>
      <path d="M26 30 L30 14 L40 26 Z" className="j-deep" />
      <path d="M74 30 L70 14 L60 26 Z" className="j-deep" />
      <ellipse cx="50" cy="56" rx="30" ry="34" className="j-accent" />
      <ellipse cx="50" cy="66" rx="18" ry="20" className="j-soft" />
      <path d="M44 72 q6 4 12 0 M42 80 q8 4 16 0" className="j-stroke-deep" strokeWidth={2} fill="none" strokeLinecap="round" />
      <circle cx="38" cy="42" r="12" className="j-white" />
      <circle cx="62" cy="42" r="12" className="j-white" />
      <Eyes cx1={38} cx2={62} cy={43} r={6} />
      <path d="M46 52 L54 52 L50 60 Z" className="j-warm" />
      <path d="M21 58 q-6 14 6 24 q2 -12 -6 -24 Z" className="j-deep j-arm" />
      <path d="M79 58 q6 14 -6 24 q-2 -12 6 -24 Z" className="j-deep" />
      <path d="M40 90 v4 M46 90 v4 M54 90 v4 M60 90 v4" className="j-stroke-warm" strokeWidth={3} strokeLinecap="round" />
    </g>
  );
}

function Cat() {
  return (
    <g>
      <path d="M24 40 L28 14 L44 30 Z" className="j-accent" />
      <path d="M76 40 L72 14 L56 30 Z" className="j-accent" />
      <path d="M29 34 L31 21 L39 29 Z" className="j-blush" />
      <path d="M71 34 L69 21 L61 29 Z" className="j-blush" />
      <path d="M72 78 q18 -4 14 -22" className="j-stroke-accent j-arm" strokeWidth={7} strokeLinecap="round" fill="none" />
      <ellipse cx="50" cy="78" rx="24" ry="16" className="j-accent" />
      <ellipse cx="50" cy="44" rx="28" ry="24" className="j-accent" />
      <ellipse cx="50" cy="52" rx="14" ry="9" className="j-soft" />
      <Eyes cx1={40} cx2={60} cy={42} r={5} />
      <path d="M47 49 L53 49 L50 53 Z" className="j-blush-deep" />
      <path d="M50 53 q-4 5 -8 2 M50 53 q4 5 8 2" className="j-stroke-ink" strokeWidth={2} fill="none" strokeLinecap="round" />
      <path d="M22 48 h12 M22 54 l12 -2 M78 48 h-12 M78 54 l-12 -2" className="j-stroke-deep" strokeWidth={1.6} strokeLinecap="round" />
    </g>
  );
}

function Ghost() {
  return (
    <g>
      <path
        d="M22 50 Q22 18 50 18 Q78 18 78 50 L78 84 Q72 78 66 84 Q60 90 54 84 Q50 78 46 84 Q40 90 34 84 Q28 78 22 84 Z"
        className="j-soft"
      />
      <path
        d="M22 50 Q22 18 50 18 Q78 18 78 50"
        className="j-stroke-accent"
        strokeWidth={3}
        fill="none"
      />
      <Eyes cx1={40} cx2={60} cy={46} r={5.5} />
      <Cheeks x1={33} x2={67} y={56} />
      <ellipse cx="50" cy="60" rx="5" ry="6" className="j-ink" />
      <path d="M18 60 q-8 -2 -8 -10" className="j-stroke-accent j-arm" strokeWidth={5} strokeLinecap="round" fill="none" />
      <circle cx="84" cy="24" r="3" className="j-glow j-accent" />
    </g>
  );
}

function Rocket() {
  return (
    <g>
      <path d="M42 80 Q50 98 58 80 Z" className="j-glow j-warm" />
      <path d="M34 62 L22 82 L38 76 Z" className="j-accent j-arm" />
      <path d="M66 62 L78 82 L62 76 Z" className="j-accent" />
      <path d="M50 8 Q72 28 68 62 L64 80 L36 80 L32 62 Q28 28 50 8 Z" className="j-white-soft" />
      <path d="M50 8 Q60 16 64 26 L36 26 Q40 16 50 8 Z" className="j-accent" />
      <circle cx="50" cy="46" r="13" className="j-deep" />
      <circle cx="50" cy="46" r="10" className="j-screen" />
      <Eyes cx1={45.5} cx2={54.5} cy={45} r={2.8} />
      <Smile x={50} y={50} w={6} />
      <rect x="40" y="68" width="20" height="5" rx="2.5" className="j-accent" />
    </g>
  );
}

function Star() {
  return (
    <g>
      <path
        d="M50 8 L61 36 L91 38 L68 57 L76 88 L50 71 L24 88 L32 57 L9 38 L39 36 Z"
        className="j-accent"
        strokeLinejoin="round"
      />
      <path d="M50 18 L58 38 L50 34 Z" className="j-soft" />
      <Eyes cx1={42} cx2={58} cy={48} r={4.5} />
      <Cheeks x1={36} x2={64} y={57} />
      <Smile x={50} y={56} w={10} />
      <circle cx="86" cy="16" r="3" className="j-glow j-warm" />
      <circle cx="14" cy="80" r="2.5" className="j-glow j-warm" />
    </g>
  );
}

function Dragon() {
  return (
    <g>
      <path d="M26 52 Q8 40 12 22 Q24 32 34 44 Z" className="j-deep j-arm" />
      <path d="M74 52 Q92 40 88 22 Q76 32 66 44 Z" className="j-deep" />
      <path d="M68 82 q22 4 20 -14 q-4 6 -10 6" className="j-stroke-accent" strokeWidth={7} strokeLinecap="round" fill="none" />
      <ellipse cx="50" cy="72" rx="22" ry="18" className="j-accent" />
      <ellipse cx="50" cy="76" rx="12" ry="11" className="j-soft" />
      <path d="M36 28 L32 12 L44 24 Z M64 28 L68 12 L56 24 Z" className="j-warm" />
      <ellipse cx="50" cy="40" rx="24" ry="20" className="j-accent" />
      <ellipse cx="50" cy="50" rx="13" ry="8" className="j-soft" />
      <circle cx="45" cy="49" r="1.6" className="j-ink" />
      <circle cx="55" cy="49" r="1.6" className="j-ink" />
      <Eyes cx1={40} cx2={60} cy={36} r={5} />
      <path d="M42 24 l4 -6 l4 6 l4 -6 l4 6" className="j-stroke-deep" strokeWidth={2.5} fill="none" strokeLinejoin="round" />
    </g>
  );
}

function Astronaut() {
  return (
    <g>
      <rect x="30" y="62" width="40" height="28" rx="12" className="j-white-soft" />
      <rect x="40" y="70" width="20" height="10" rx="3" className="j-accent" />
      <circle cx="45" cy="75" r="2" className="j-glow j-warm" />
      <rect x="20" y="64" width="12" height="9" rx="4.5" className="j-white-soft j-arm" />
      <rect x="68" y="64" width="12" height="9" rx="4.5" className="j-white-soft" />
      <circle cx="50" cy="40" r="28" className="j-white-soft" />
      <rect x="28" y="26" width="44" height="30" rx="15" className="j-deep" />
      <rect x="31" y="29" width="38" height="24" rx="12" className="j-screen" />
      <Eyes cx1={42} cx2={58} cy={40} r={4.2} />
      <Smile x={50} y={46} w={9} />
      <path d="M58 31 q6 1 8 6" className="j-stroke-white" strokeWidth={2.5} strokeLinecap="round" fill="none" />
      <line x1="72" y1="18" x2="78" y2="10" className="j-stroke-deep" strokeWidth={2.5} strokeLinecap="round" />
      <circle cx="79" cy="9" r="3" className="j-glow j-accent" />
    </g>
  );
}

function Trophy() {
  return (
    <g>
      <path d="M26 24 q-14 2 -10 18 q4 12 18 12" className="j-stroke-gold" strokeWidth={6} fill="none" strokeLinecap="round" />
      <path d="M74 24 q14 2 10 18 q-4 12 -18 12" className="j-stroke-gold" strokeWidth={6} fill="none" strokeLinecap="round" />
      <path d="M26 16 H74 V36 Q74 64 50 66 Q26 64 26 36 Z" className="j-gold" />
      <path d="M32 20 H40 V44 Q34 40 32 32 Z" className="j-gold-light" />
      <rect x="44" y="64" width="12" height="12" className="j-gold-deep" />
      <rect x="32" y="76" width="36" height="12" rx="4" className="j-accent" />
      <Eyes cx1={42} cx2={58} cy={38} r={4.5} />
      <Cheeks x1={36} x2={64} y={47} />
      <Smile x={50} y={46} w={10} />
      <circle cx="18" cy="12" r="2.5" className="j-glow j-warm" />
      <circle cx="84" cy="10" r="3" className="j-glow j-warm" />
    </g>
  );
}

const ART: Record<JarvisCharacterId, () => ReactElement> = {
  robot: () => <Robot />,
  owl: () => <Owl />,
  cat: () => <Cat />,
  ghost: () => <Ghost />,
  rocket: () => <Rocket />,
  star: () => <Star />,
  dragon: () => <Dragon />,
  astronaut: () => <Astronaut />,
  robot_gold: () => <Robot gold />,
  trophy: () => <Trophy />,
};
