import { splitTitle } from "@/lib/career/format";

/**
 * Podgląd posta na LinkedInie — miniatura grafiki Open Graph strony kariery.
 *
 * WYJĄTEK OD ZASADY TOKEN-FIRST: górna część karty odwzorowuje ZEWNĘTRZNY
 * obraz (grafikę OG `kariera.dynaminds.pl`, terminal w barwach Dynaminds:
 * czerń, bordo #9A142D, biel). Ma wyglądać tak samo w każdym motywie NEXUSA,
 * bo tak zobaczy go LinkedIn — dlatego kolory są tu zaszyte celowo i tylko
 * w tym komponencie. Podpis pod obrazem (tytuł + domena) to już NEXUS: tokeny.
 */

export interface LinkedInPreviewCardProps {
  /** Linia komendy nad nagłówkiem, bez znaku `$`. */
  command: string;
  /** Nagłówek grafiki; ostatnie słowo dostaje bordo (kropkę — tylko po literze/cyfrze). */
  headline: string;
  /** Linia pod nagłówkiem, np. „[warszawa · hybryda · b2b]". */
  tagline?: string | null;
  /** Tytuł karty pod obrazem. */
  cardTitle: string;
  /** Domena pod tytułem. */
  host: string;
}


export function LinkedInPreviewCard({
  command,
  headline,
  tagline,
  cardTitle,
  host,
}: LinkedInPreviewCardProps) {
  // Ta sama reguła co na stronie i grafice OG — podgląd ma wyglądać jak post.
  const { first: lead, second: last } = splitTitle(headline);
  return (
    <figure
      className="overflow-hidden rounded-lg border border-border bg-card"
      aria-label="Podgląd posta na LinkedInie"
      data-testid="linkedin-preview"
    >
      {/* Kolory zaszyte celowo — patrz komentarz na górze pliku. */}
      <div
        className="flex h-[184px] flex-col font-mono"
        style={{ backgroundColor: "#000000" }}
        aria-hidden="true"
      >
        <div
          className="flex h-5 items-center gap-1 px-2.5"
          style={{ borderBottom: "1px solid #1A1A1A" }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ border: "1px solid #5C5C5C" }} />
          <span className="h-1.5 w-1.5 rounded-full" style={{ border: "1px solid #5C5C5C" }} />
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: "#9A142D" }} />
        </div>
        <div className="flex flex-1 flex-col justify-between px-4 py-3">
          <span className="truncate text-[9px]" style={{ color: "#F5F5F5" }}>
            <span style={{ color: "#C8384F" }}>$</span> {command}
          </span>
          <span
            className="line-clamp-2 font-sans text-[28px] font-extrabold leading-[0.95] tracking-[-0.04em]"
          >
            {lead ? <span style={{ color: "#FFFFFF" }}>{lead} </span> : null}
            <span style={{ color: "#9A142D" }}>{last}</span>
          </span>
          <span className="truncate text-[9px]" style={{ color: "#8B8B8B" }}>
            {tagline ?? " "}
          </span>
        </div>
      </div>
      <figcaption className="px-3 py-2.5">
        <div className="truncate text-sm font-semibold text-foreground">{cardTitle}</div>
        <div className="truncate text-xs text-muted-foreground">{host}</div>
      </figcaption>
    </figure>
  );
}
