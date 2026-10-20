"use client";

import gsap from "gsap";
import { ScrambleTextPlugin } from "gsap/ScrambleTextPlugin";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import Lenis from "lenis";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * Ruch wspólny dla stron kariery (etap 7, PR D, decyzje D1 = A i D3 = A,
 * 21.10.2026; prototyp https://claude.ai/artifact/TsUgULCMSSjVTiYWvoGN3b).
 *
 * - Moment otwarcia: linie tytułu wysuwają się spod maski (SplitText),
 *   a komenda nad tytułem (`data-kr-scramble`) rozszyfrowuje się raz
 *   (ScrambleText). Po animacji SplitText przywraca oryginalny tytuł, żeby
 *   React nie trafił na podmienione węzły przy kolejnym renderze.
 * - Płynny scroll (Lenis) tylko z myszą od 1024 px; na telefonie i touchpadzie
 *   zostaje natywny. Lenis napędza ScrollTrigger (sekcja „Sprawdź się”, oś
 *   procesu) i obsługuje kotwice `#…` („Aplikuj”).
 *
 * „Ograniczony ruch” w systemie wyłącza wszystko — strona stoi od początku.
 * Bez `matchMedia` (jsdom) komponent nic nie robi.
 */
/** Jeden Lenis na dokument — harness `/preview/kariera` ma wiele korzeni. */
let lenisInUse = false;

export function CareerMotion() {
  const pathname = usePathname();
  const marker = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    // Tylko własny korzeń: kilka korzeni na stronie nie dzieli cudzych tytułów.
    const root = marker.current?.closest<HTMLElement>(".kr-root");
    if (!root) return;
    gsap.registerPlugin(ScrollTrigger, SplitText, ScrambleTextPlugin);
    const mm = gsap.matchMedia();

    // Otwarcie bez kontekstu matchMedia: sprzątanie jest jawne, bo podwójny
    // efekt (StrictMode, zmiana adresu) nie może podzielić tytułu dwa razy
    // ani zostawić go przesuniętego pod maską.
    const tweens: gsap.core.Tween[] = [];
    const splits: SplitText[] = [];
    const scrambled: [HTMLElement, string][] = [];
    let cancelled = false;
    const open = () => {
      if (cancelled) return;
      gsap.utils.toArray<HTMLElement>(".kr-title:not([data-kr-split])", root).forEach((title) => {
        title.setAttribute("data-kr-split", "");
        const split = new SplitText(title, { type: "lines", mask: "lines" });
        splits.push(split);
        tweens.push(
          gsap.from(split.lines, {
            yPercent: 105,
            duration: 0.9,
            stagger: 0.08,
            ease: "expo.out",
            delay: 0.1,
            onComplete: () => {
              split.revert();
              title.removeAttribute("data-kr-split");
            },
          }),
        );
      });
      gsap.utils.toArray<HTMLElement>("[data-kr-scramble]", root).forEach((el) => {
        const text = el.textContent ?? "";
        scrambled.push([el, text]);
        tweens.push(
          gsap.to(el, { duration: 0.9, scrambleText: { text, chars: "01/_<>$", speed: 0.5 } }),
        );
      });
    };
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // Linie liczone na właściwym kroju — inaczej po podmianie fontu pękają inaczej.
      if (!document.fonts || document.fonts.status === "loaded") open();
      else void document.fonts.ready.then(open);
    }

    mm.add(
      "(min-width: 1024px) and (pointer: fine) and (prefers-reduced-motion: no-preference)",
      () => {
        if (lenisInUse) return;
        lenisInUse = true;
        const lenis = new Lenis({ duration: 1.05 });
        const raf = (time: number) => lenis.raf(time * 1000);
        lenis.on("scroll", ScrollTrigger.update);
        gsap.ticker.add(raf);
        gsap.ticker.lagSmoothing(0);
        // Kotwice („Aplikuj” → #aplikuj) przewija Lenis, inaczej skok gubi płynność.
        const onClick = (e: MouseEvent) => {
          const link = (e.target as HTMLElement | null)?.closest?.('a[href^="#"]');
          const id = link?.getAttribute("href")?.slice(1);
          const target = id ? document.getElementById(id) : null;
          if (!target) return;
          e.preventDefault();
          lenis.scrollTo(target, { offset: -16 });
          history.replaceState(null, "", `#${id}`);
        };
        document.addEventListener("click", onClick);
        return () => {
          document.removeEventListener("click", onClick);
          gsap.ticker.remove(raf);
          gsap.ticker.lagSmoothing(500, 33);
          lenis.destroy();
          lenisInUse = false;
        };
      },
    );

    return () => {
      cancelled = true;
      tweens.forEach((t) => t.kill());
      splits.forEach((sp) => sp.revert());
      root.querySelectorAll("[data-kr-split]").forEach((t) => t.removeAttribute("data-kr-split"));
      scrambled.forEach(([el, text]) => {
        el.textContent = text;
      });
      mm.revert();
    };
  }, [pathname]);

  return <span ref={marker} hidden />;
}
