"use client";

import { useEffect, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";

interface AudioPlayerProps {
  src: string;
  className?: string;
}

/**
 * Lightweight wrapper over `<audio controls>` for call and meeting recordings.
 *
 * We render the native player and also expose an external "Open" link as a
 * fallback for browsers that block the audio element (mixed-content) or codecs.
 */
export default function AudioPlayer({ src, className = "" }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
  }, [src]);

  if (!src) return null;

  return (
    <div className={`space-y-1.5 ${className}`}>
      <audio
        ref={audioRef}
        controls
        preload="metadata"
        className="w-full"
        onError={() => setError("Nie udało się odtworzyć nagrania w przeglądarce")}
      >
        <source src={src} type="audio/mpeg" />
      </audio>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        {error ? <span className="text-amber-600">{error}</span> : <span />}
        <a
          href={src}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 hover:text-primary"
        >
          Otwórz w nowej karcie <ExternalLink className="h-3 w-3" />
        </a>
      </div>
    </div>
  );
}
