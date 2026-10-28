"use client";

import { useEffect, useState } from "react";

import s from "./jasnyJob.module.css";

interface JasnyApplyDockProps {
  /** Pierwszy ekran z przyciskiem „Aplikuj — 2 minuty”. */
  heroId: string;
  /** Kontener formularza (`#aplikuj`). */
  formId: string;
}

/**
 * Telefon i tablet (< 1024 px): „Aplikuj — 2 minuty” przyklejone do dołu od
 * chwili, gdy hero znika z ekranu, do chwili, gdy widać formularz — dwa takie
 * same przyciski naraz tylko zasłaniają treść. Od 1024 px CSS go chowa
 * (przycisk jest w przyklejonym pasku u góry).
 */
export function JasnyApplyDock({ heroId, formId }: JasnyApplyDockProps) {
  const [heroGone, setHeroGone] = useState(false);
  const [formSeen, setFormSeen] = useState(false);

  useEffect(() => {
    const hero = document.getElementById(heroId);
    const form = document.getElementById(formId);
    if (!hero || !form || typeof IntersectionObserver === "undefined") return;
    const heroObs = new IntersectionObserver(([e]) => setHeroGone(!e.isIntersecting));
    const formObs = new IntersectionObserver(([e]) => setFormSeen(e.isIntersecting));
    heroObs.observe(hero);
    formObs.observe(form);
    return () => {
      heroObs.disconnect();
      formObs.disconnect();
    };
  }, [heroId, formId]);

  const shown = heroGone && !formSeen;
  return (
    <div className={s.dock} data-shown={shown ? "" : undefined} inert={!shown}>
      <a href={`#${formId}`} className={s.dockBtn}>
        Aplikuj — 2 minuty
      </a>
    </div>
  );
}
