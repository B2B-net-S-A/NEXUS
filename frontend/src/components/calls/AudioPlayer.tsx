"use client";

import { useEffect, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";

interface AudioPlayerProps {
  src: string;
  className?: string;
  /**
   * When true, fetch `src` with the Bearer token (same-origin authed proxy,
   * e.g. the own-dialer recording endpoint) and play via an object URL. When
   * false (default), the player points directly at a public/signed URL
   * (legacy CloudTalk recordings).
   */
  authed?: boolean;
}

/**
 * Lightweight wrapper over `<audio controls>` for call recordings.
 *
 * - Public mode (default): native `<source>` at a signed/public URL.
 * - Authed mode: `fetch` the URL with the JWT, build an object URL, and feed
 *   it to the audio element. Used for own-dialer recordings served by the
 *   backend proxy (candidate PII — never a public URL).
 */
export default function AudioPlayer({
  src,
  className = "",
  authed = false,
}: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    if (!authed || !src) {
      return;
    }
    let revoked = false;
    let createdUrl: string | null = null;
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("access_token")
        : null;
    fetch(src, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((resp) => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.blob();
      })
      .then((blob) => {
        if (revoked) return;
        createdUrl = URL.createObjectURL(blob);
        setBlobUrl(createdUrl);
      })
      .catch(() => setError("Nie udało się pobrać nagrania"));
    return () => {
      revoked = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
      setBlobUrl(null);
    };
  }, [src, authed]);

  if (!src) return null;

  const playableSrc = authed ? blobUrl : src;

  return (
    <div className={`space-y-1.5 ${className}`}>
      {playableSrc ? (
        <audio
          ref={audioRef}
          controls
          preload="metadata"
          src={authed ? (playableSrc ?? undefined) : undefined}
          className="w-full"
          onError={() =>
            setError("Nie udało się odtworzyć nagrania w przeglądarce")
          }
        >
          {!authed && <source src={src} type="audio/mpeg" />}
        </audio>
      ) : (
        <div className="text-xs text-muted-foreground">Ładowanie nagrania…</div>
      )}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        {error ? <span className="text-amber-600">{error}</span> : <span />}
        {!authed && (
          <a
            href={src}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 hover:text-primary"
          >
            Otwórz w nowej karcie <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </div>
  );
}
