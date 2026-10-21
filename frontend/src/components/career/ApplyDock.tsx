"use client";

import { useEffect, useState } from "react";

/**
 * Telefon (< 1024 px): „Aplikuj · 2 minuty” przyklejone do dołu od chwili, gdy
 * hero znika z ekranu, do chwili, gdy widać formularz (etap 7, PR C). Na
 * komputerze przycisk jest przy wyniku w panelu parametrów, więc CSS go chowa.
 */
export function ApplyDock({
  heroId,
  formId,
}: {
  heroId: string;
  formId: string;
}) {
  const [heroGone, setHeroGone] = useState(false);
  const [formSeen, setFormSeen] = useState(false);

  useEffect(() => {
    const hero = document.getElementById(heroId);
    const form = document.getElementById(formId);
    if (!hero || !form || typeof IntersectionObserver === "undefined") return;
    const heroObs = new IntersectionObserver(([e]) =>
      setHeroGone(!e.isIntersecting),
    );
    const formObs = new IntersectionObserver(([e]) =>
      setFormSeen(e.isIntersecting),
    );
    heroObs.observe(hero);
    formObs.observe(form);
    return () => {
      heroObs.disconnect();
      formObs.disconnect();
    };
  }, [heroId, formId]);

  const shown = heroGone && !formSeen;
  return (
    <div
      className="kr-dock"
      data-shown={shown ? "" : undefined}
      aria-hidden={!shown}
    >
      <a
        href={`#${formId}`}
        className="kr-dock-btn"
        tabIndex={shown ? undefined : -1}
      >
        Aplikuj · 2 minuty
      </a>
    </div>
  );
}
