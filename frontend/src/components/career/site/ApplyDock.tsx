"use client";

import { useEffect, useState } from "react";

import { siteStyles as s } from "./SiteFrame";

export const QUICK_ID = "szybko";

/**
 * Przyklejony pasek „Wyślij CV” na telefonie (poniżej 1024 px). Klik przewija
 * do szybkiej aplikacji i od razu otwiera wybór pliku — kandydat wybiera CV,
 * zaznacza zgodę i wysyła. Pasek znika, gdy szybka aplikacja albo pełny
 * formularz (albo stopka) są na ekranie.
 */
export function ApplyDock() {
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    // Stopka też chowa pasek, żeby nie zasłaniał danych firmy na dole strony.
    // Chowamy dopiero, gdy widać cały przycisk wysyłki szybkiej aplikacji (nie jej
    // skrawek) albo gdy na ekranie jest pełny formularz lub stopka.
    const quickSend = document.getElementById(QUICK_ID)?.querySelector('button[type="submit"]') ?? null;
    const visible = new Set<Element>();
    const onChange = (entries: IntersectionObserverEntry[]) => {
      for (const e of entries) {
        if (e.isIntersecting) visible.add(e.target);
        else visible.delete(e.target);
      }
      setHidden(visible.size > 0);
    };
    const whole = new IntersectionObserver(onChange, { threshold: 1 });
    const any = new IntersectionObserver(onChange);
    if (quickSend) whole.observe(quickSend);
    for (const el of [document.getElementById("aplikuj"), document.querySelector("footer")]) if (el) any.observe(el);
    return () => {
      whole.disconnect();
      any.disconnect();
    };
  }, []);

  const open = () => {
    const form = document.getElementById(QUICK_ID);
    form?.scrollIntoView({ block: "center", behavior: "smooth" });
    form?.querySelector<HTMLInputElement>('input[type="file"]')?.click();
  };

  return (
    <div className={s.dock} hidden={hidden}>
      <button type="button" className={`${s.btn} ${s.btnRed} ${s.dockBtn}`} onClick={open}>
        Wyślij CV <span>30 sekund</span>
      </button>
    </div>
  );
}
