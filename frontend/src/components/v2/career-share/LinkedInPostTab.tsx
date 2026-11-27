"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Copy, Download, Loader2 } from "lucide-react";

import "@/components/career/layouts/brandFonts.css";
import { POST_SIZE, PostCardFacts, PostCardMap, PostCarouselSlide } from "@/components/career/ogPostCard";
import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { DialogBody } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useInviteLinks, useJobPublicProfile } from "@/lib/api/careerLinks";
import { downloadBlob } from "@/lib/authenticated-files";
import { jpegPagesToPdf } from "@/lib/career/carouselPdf";
import {
  postComment,
  postDataPath,
  postDataQueryKey,
  postGraphicPath,
  type PostDataResponse,
  type PostVariant,
} from "@/lib/career/postGraphic";
import { copyTextToClipboard } from "@/lib/clipboard";

import { activeLinkForJob, linkUrl, pageState } from "./share-utils";

/*
 * Zakładka „Post na LinkedIn” (decyzja Artura 27.11.2026, prośba Olafa):
 * grafika do posta (Mapa / Konkrety / karuzela PDF), treść posta z szablonu
 * i pierwszy komentarz z linkiem. Zespół wrzuca grafikę jako post, a link do
 * aplikacji daje w komentarzu.
 *
 * WYJĄTEK OD ZASADY TOKEN-FIRST: podgląd grafiki to ZEWNĘTRZNY obraz (ten sam
 * kadr, który rysuje `next/og`), przeskalowany — ma wyglądać tak samo w każdym
 * motywie NEXUSA. Reszta zakładki to tokeny.
 */

const VARIANTS: { id: PostVariant; label: string; hint: string }[] = [
  { id: "mapa", label: "Mapa", hint: "Jak strona kariery: technologie, stanowisko, miasto na mapie." },
  { id: "konkrety", label: "Konkrety", hint: "Wielka technologia, czym się zajmiesz i czego szukamy." },
  { id: "karuzela", label: "Karuzela", hint: "Dokument PDF ze slajdami — na LinkedInie „Dodaj dokument”." },
];

async function fetchPostData(slug: string): Promise<PostDataResponse> {
  const res = await fetch(postDataPath(slug), { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as PostDataResponse;
}

async function fetchPng(path: string): Promise<Blob> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

/** PNG slajdu → JPEG (PDF przyjmuje JPEG bez dekodowania). */
async function pngToJpeg(png: Blob): Promise<Uint8Array> {
  const bitmap = await createImageBitmap(png);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Brak canvas 2d");
  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0);
  const jpeg = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
  if (!jpeg) throw new Error("Nie udało się zapisać JPEG");
  return new Uint8Array(await jpeg.arrayBuffer());
}

/** Kadr 1080×1350 przeskalowany do szerokości ramki. */
function ScaledFrame({ children, label }: { children: React.ReactNode; label: string }) {
  const frame = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.26);
  useEffect(() => {
    const node = frame.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width;
      if (width > 0) setScale(width / POST_SIZE.width);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return (
    <div
      ref={frame}
      role="img"
      aria-label={label}
      className="relative w-full overflow-hidden rounded-lg border border-border"
      style={{ aspectRatio: `${POST_SIZE.width} / ${POST_SIZE.height}` }}
    >
      <div
        className="absolute left-0 top-0 origin-top-left"
        style={{ width: POST_SIZE.width, height: POST_SIZE.height, transform: `scale(${scale})` }}
        aria-hidden="true"
      >
        {children}
      </div>
    </div>
  );
}

export interface LinkedInPostTabProps {
  enabled: boolean;
  jobId: number | null;
  /** Przejście do zakładki „Link do tej rekrutacji” (zatwierdzenie opisu, link). */
  onGoToLink: () => void;
}

export function LinkedInPostTab({ enabled, jobId, onGoToLink }: LinkedInPostTabProps) {
  const { showSuccess, showError } = useToast();
  const [variant, setVariant] = useState<PostVariant>("mapa");
  const [slide, setSlide] = useState(0);
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const profileQuery = useJobPublicProfile(enabled ? jobId : null);
  const linksQuery = useInviteLinks(enabled);
  const profile = profileQuery.data ?? null;
  const isLive = pageState(profile) !== "not_live";
  const link = activeLinkForJob(linksQuery.data ?? [], jobId);
  const slug = link?.slug ?? null;

  const dataQuery = useQuery({
    queryKey: postDataQueryKey(slug),
    queryFn: () => fetchPostData(slug as string),
    enabled: enabled && isLive && slug != null,
    staleTime: 60_000,
    retry: false,
  });

  // Nowa rekrutacja albo nowa wersja opisu = świeży szablon treści posta.
  const template = dataQuery.data?.text ?? null;
  useEffect(() => {
    setText(template);
    setSlide(0);
  }, [template, jobId]);

  if (jobId == null) {
    return (
      <DialogBody>
        <p className="text-sm text-muted-foreground">Wybierz rekrutację w zakładce „Link do tej rekrutacji”.</p>
      </DialogBody>
    );
  }
  if (profileQuery.isLoading || linksQuery.isLoading) {
    return (
      <DialogBody>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Sprawdzam stronę i link…
        </div>
      </DialogBody>
    );
  }
  if (profileQuery.isError || linksQuery.isError) {
    return (
      <DialogBody>
        <QueryStateNotice
          state="error"
          description="Nie udało się sprawdzić strony i linku tej rekrutacji."
          onRetry={() => {
            void profileQuery.refetch();
            void linksQuery.refetch();
          }}
        />
      </DialogBody>
    );
  }
  if (!isLive || !link) {
    return (
      <DialogBody className="space-y-3">
        <p className="text-sm text-foreground" data-testid="post-not-ready">
          {!isLive
            ? "Grafika do posta powstaje z opublikowanego opisu. Najpierw zatwierdź opis publiczny."
            : "Do komentarza pod postem potrzebny jest link. Wygeneruj go, a grafika i treść posta pojawią się tutaj."}
        </p>
        <Button variant="outline" size="sm" onClick={onGoToLink}>
          {!isLive ? "Przejdź do opisu" : "Wygeneruj link"}
        </Button>
      </DialogBody>
    );
  }

  const data = dataQuery.data;
  const url = linkUrl(link);
  const comment = postComment(url);
  const slides = data?.slides ?? [];
  const fileBase = `post-${slug}`;

  const copy = async (value: string, what: string) => {
    const ok = await copyTextToClipboard(value);
    if (ok) showSuccess(`Skopiowano ${what}.`);
    else showError("Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie.");
  };

  const download = async () => {
    if (!slug) return;
    setBusy(true);
    try {
      if (variant === "karuzela") {
        const pages = [];
        for (let i = 0; i < slides.length; i += 1) {
          const bytes = await pngToJpeg(await fetchPng(postGraphicPath(slug, "karuzela", i + 1)));
          pages.push({ bytes, width: POST_SIZE.width, height: POST_SIZE.height });
        }
        const pdf = jpegPagesToPdf(pages);
        downloadBlob(new Blob([pdf as BlobPart], { type: "application/pdf" }), `${fileBase}-karuzela.pdf`);
      } else {
        downloadBlob(await fetchPng(postGraphicPath(slug, variant)), `${fileBase}-${variant}.png`);
      }
    } catch (err: unknown) {
      console.error("Pobranie grafiki posta nie powiodło się", err);
      showError("Nie udało się przygotować grafiki. Spróbuj ponownie.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogBody className="space-y-4">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <section className="space-y-3" aria-labelledby="post-graphic-heading">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="post-graphic-heading" className="text-sm font-semibold text-foreground">
              Grafika
            </h3>
            <div className="flex flex-wrap gap-1" role="group" aria-label="Wygląd grafiki">
              {VARIANTS.map((v) => (
                <Button
                  key={v.id}
                  type="button"
                  size="sm"
                  variant={variant === v.id ? "primary" : "outline"}
                  aria-pressed={variant === v.id}
                  onClick={() => {
                    setVariant(v.id);
                    setSlide(0);
                  }}
                >
                  {v.label}
                </Button>
              ))}
            </div>
          </div>
          <p className="text-xs text-muted-foreground">{VARIANTS.find((v) => v.id === variant)?.hint}</p>
          {dataQuery.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Rysuję grafikę…
            </div>
          ) : dataQuery.isError || !data ? (
            <QueryStateNotice
              state="error"
              description="Nie udało się przygotować grafiki do posta."
              onRetry={() => dataQuery.refetch()}
            />
          ) : (
            <div className="mx-auto w-full max-w-[264px] space-y-2">
              <ScaledFrame label={`Grafika do posta: ${data.post.title}`}>
                {variant === "konkrety" ? (
                  <PostCardFacts d={data.post} />
                ) : variant === "karuzela" ? (
                  <PostCarouselSlide d={data.post} slides={slides} index={slide} />
                ) : (
                  <PostCardMap d={data.post} />
                )}
              </ScaledFrame>
              {variant === "karuzela" ? (
                <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Poprzedni slajd"
                    disabled={slide === 0}
                    onClick={() => setSlide((s) => s - 1)}
                  >
                    <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                  </Button>
                  <span className="whitespace-nowrap">
                    Slajd {slide + 1} z {slides.length}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Następny slajd"
                    disabled={slide >= slides.length - 1}
                    onClick={() => setSlide((s) => s + 1)}
                  >
                    <ChevronRight className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
              ) : null}
              <Button type="button" className="w-full" onClick={download} loading={busy} disabled={busy}>
                <Download className="h-4 w-4" aria-hidden="true" />
                {variant === "karuzela" ? "Pobierz karuzelę (PDF)" : "Pobierz grafikę (PNG)"}
              </Button>
              <p className="text-xs text-muted-foreground">
                1080 × 1350 z opublikowanej wersji opisu. Bez klienta i stawek, jak na stronie kariery.
              </p>
            </div>
          )}
        </section>

        <section className="space-y-4" aria-label="Treść posta i komentarz">
          <div className="space-y-1.5">
            <label htmlFor="post-text" className="text-sm font-semibold text-foreground">
              Treść posta
            </label>
            <Textarea
              id="post-text"
              rows={11}
              value={text ?? ""}
              onChange={(e) => setText(e.target.value)}
              disabled={text == null}
              placeholder={dataQuery.isLoading ? "Przygotowuję treść…" : ""}
            />
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" disabled={!text} onClick={() => copy(text ?? "", "treść posta")}>
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                Kopiuj treść
              </Button>
              {template && text !== template ? (
                <Button type="button" variant="ghost" size="sm" onClick={() => setText(template)}>
                  Przywróć szablon
                </Button>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">
              Poprawki tu nie są sprawdzane — nie dopisuj klienta ani stawki.
            </p>
          </div>
          <div className="space-y-1.5">
            <span className="text-sm font-semibold text-foreground">Pierwszy komentarz</span>
            <p
              data-testid="post-comment"
              className="select-all break-all rounded-md border border-border bg-background px-3 py-2 font-mono text-xs text-foreground"
            >
              {comment}
            </p>
            <Button type="button" variant="outline" size="sm" onClick={() => copy(comment, "komentarz z linkiem")}>
              <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              Kopiuj komentarz
            </Button>
            <p className="text-xs text-muted-foreground">
              {link.label ? `Link „${link.label}”` : "Twój link do tej rekrutacji"} — zgłoszenia z posta zobaczysz w
              zakładce „Wyniki”.
            </p>
          </div>
        </section>
      </div>
    </DialogBody>
  );
}
