/**
 * Strój robota Jarvisa do świata wyglądu (decyzja Artura 13.11.2026,
 * `docs/claude/ui/swiaty-wygladu.md`). Rysowany w tej samej siatce 100×100
 * co robot (głowa: x 22–78, y 22–66; antena do y 4), więc ubieramy tylko
 * robota — inne postaci mają inne kształty. Kolory w klasach `jo-*`
 * (`globals.css`), nie w kodzie.
 */

import type { ReactElement } from "react";

const OUTFITS: Readonly<Record<string, () => ReactElement>> = {
  // Zima: czapka z pomponem zakrywa antenę.
  winter: () => (
    <g data-outfit="winter">
      <path d="M25 26 C25 6 75 6 75 26 Z" className="jo-red" />
      <rect x="21" y="22" width="58" height="9" rx="4.5" className="jo-white" />
      <circle cx="50" cy="7" r="6" className="jo-white" />
    </g>
  ),
  // Pit stop: kask z szybką i pasem w szachownicę.
  pitstop: () => (
    <g data-outfit="pitstop">
      <path d="M17 46 C14 8 86 8 83 46 L78 46 C78 24 22 24 22 46 Z" className="jo-orange" />
      <rect x="44" y="9" width="12" height="4" className="jo-white" />
      <rect x="44" y="13" width="6" height="4" className="jo-ink" />
      <rect x="50" y="13" width="6" height="4" className="jo-white" />
      <rect x="44" y="9" width="6" height="4" className="jo-ink" />
    </g>
  ),
  // Stadion: szalik kibica w barwach świata.
  stadium: () => (
    <g data-outfit="stadium">
      <rect x="24" y="61" width="52" height="10" rx="5" className="jo-green" />
      <rect x="34" y="61" width="5" height="10" className="jo-gold" />
      <rect x="61" y="61" width="5" height="10" className="jo-gold" />
      <rect x="58" y="66" width="10" height="20" rx="3" className="jo-green" />
      <rect x="58" y="80" width="10" height="3" className="jo-gold" />
    </g>
  ),
  // Tulipany: wianek z tulipanów.
  tulips: () => (
    <g data-outfit="tulips">
      <path d="M24 24 C40 18 60 18 76 24" className="jo-leaf-stroke" strokeWidth={4} fill="none" strokeLinecap="round" />
      {[30, 42, 54, 66].map((x, i) => (
        <path
          key={x}
          d={`M${x - 5} 22 C${x - 6} 15 ${x - 3} 11 ${x - 2} 10 L${x - 1} 14 L${x} 9 L${x + 1} 14 L${x + 2} 10 C${x + 3} 11 ${x + 6} 15 ${x + 5} 22 Z`}
          className={["jo-red", "jo-pink", "jo-yellow", "jo-pink"][i]}
        />
      ))}
    </g>
  ),
  // Sakura: kwiat wiśni przy antenie.
  sakura: () => (
    <g data-outfit="sakura" transform="translate(32 20)">
      {[0, 72, 144, 216, 288].map((deg) => (
        <ellipse key={deg} cx="0" cy="-5" rx="3.6" ry="5.5" className="jo-pink" transform={`rotate(${deg})`} />
      ))}
      <circle r="2.4" className="jo-yellow" />
    </g>
  ),
  // Góry: kapelusz turysty z zieloną taśmą.
  mountains: () => (
    <g data-outfit="mountains">
      <ellipse cx="50" cy="25" rx="34" ry="5" className="jo-brown" />
      <path d="M32 25 C32 8 68 8 68 25 Z" className="jo-brown" />
      <rect x="32" y="18" width="36" height="5" className="jo-green" />
    </g>
  ),
  // Kosmos: hełm-bańka astronauty.
  space: () => (
    <g data-outfit="space">
      <circle cx="50" cy="44" r="36" className="jo-glass" />
      <path d="M28 30 C32 22 40 18 48 17" className="jo-white-stroke" strokeWidth={3} fill="none" strokeLinecap="round" />
    </g>
  ),
  // Arcade: neonowe słuchawki.
  arcade: () => (
    <g data-outfit="arcade">
      <path d="M17 44 C17 6 83 6 83 44" className="jo-magenta-stroke" strokeWidth={5} fill="none" strokeLinecap="round" />
      <rect x="10" y="34" width="12" height="20" rx="5" className="jo-cyan" />
      <rect x="78" y="34" width="12" height="20" rx="5" className="jo-cyan" />
    </g>
  ),
};

const DRESSABLE = new Set(["robot", "robot_gold"]);

export function hasOutfit(character: string, world: string | null | undefined): boolean {
  return Boolean(world && DRESSABLE.has(character) && OUTFITS[world]);
}

export function JarvisOutfit({ world }: { world: string }) {
  const Outfit = OUTFITS[world];
  return Outfit ? <Outfit /> : null;
}
