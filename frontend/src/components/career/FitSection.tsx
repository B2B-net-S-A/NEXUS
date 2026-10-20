"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useRef, useState } from "react";

import { SceneSketch } from "./BoardPreview";
import { Cmd } from "./CareerHero";
import { SCORE_LABELS } from "./scenes/CareerScene";
import { useScene } from "./scenes/SceneContext";

// ScrollTrigger rejestruje się w efekcie: przy imporcie czyta `matchMedia`,
// którego nie ma w jsdom (testy).
gsap.registerPlugin(useGSAP);

/**
 * „Sprawdź się” na stronie rekrutacji (etap 7, PR C, 21.10.2026; prototyp
 * https://claude.ai/artifact/TsUgULCMSSjVTiYWvoGN3b). Zastępuje listę
 * `check --wymagania`: każde wymaganie to karta z „Znam to”, które łączy ten
 * sam punkt w scenie hero i podbija wynik „x z 5” (wspólny `useScene`). Nad
 * kartami stoi przyklejony pasek: szkic sceny i wynik, żeby skutek kliknięcia
 * było widać także daleko pod hero. ScrollTrigger podświetla wymaganie, które
 * mija środek ekranu. Zaznaczenia zostają w przeglądarce — nic nie wysyłamy.
 *
 * Wymagania spoza pięciu punktów sceny (szóste wymaganie, reszta „mile
 * widzianych”) są kartami bez przycisku, żeby nic nie zginęło.
 */
export function FitSection({
  must,
}: {
  must: { name: string; note: string | null }[];
}) {
  const {
    theme,
    items,
    order,
    isOn,
    toggle,
    count,
    total,
    extraNice,
    recruiterFirstName,
  } = useScene();
  const [reading, setReading] = useState<number | null>(null);
  const root = useRef<HTMLElement>(null);

  const mustInScene = items.filter((i) => i.kind === "must").length;
  const extraMust = must.filter((m) => m.name.trim()).slice(mustInScene);

  useGSAP(
    () => {
      if (
        typeof window === "undefined" ||
        typeof window.matchMedia !== "function"
      )
        return;
      gsap.registerPlugin(ScrollTrigger);
      const cards = gsap.utils.toArray<HTMLElement>(
        ".kr-fit-card[data-fit-index]",
        root.current,
      );
      cards.forEach((card) => {
        const index = Number(card.dataset.fitIndex);
        ScrollTrigger.create({
          trigger: card,
          start: "top 60%",
          end: "bottom 40%",
          onToggle: (self) => {
            if (self.isActive) setReading(index);
            else setReading((cur) => (cur === index ? null : cur));
          },
        });
      });
    },
    { scope: root, dependencies: [items.length] },
  );

  if (items.length === 0 && extraMust.length === 0 && extraNice.length === 0)
    return null;

  return (
    <section ref={root} className="kr-fit" aria-label="Sprawdź się">
      <Cmd>check --wymagania</Cmd>
      <h2 className="kr-fit-title">Sprawdź się</h2>
      <p className="kr-fit-lead">
        Kliknij „Znam to” przy tym, co znasz. Punkt połączy się w scenie, a
        wynik pokaże, ile masz. Nie musisz mieć wszystkiego, żeby aplikować.
      </p>

      {items.length > 0 ? (
        <div className="kr-fit-stage">
          <SceneSketch
            theme={theme}
            items={items}
            animateKey="fit"
            fit={{ order, reading }}
          />
          <div className="kr-fit-score" aria-live="polite">
            <strong>
              {count} z {total}
            </strong>
            <span>{SCORE_LABELS[theme]}</span>
            <span className="kr-fit-bar" aria-hidden="true">
              {items.map((item, i) => (
                <i key={item.key} data-on={i < count ? "" : undefined} />
              ))}
            </span>
            <span className="kr-fit-note">
              Zaznaczenia widzisz tylko Ty — nic nie wysyłamy.
            </span>
          </div>
        </div>
      ) : null}

      <ul className="kr-fit-list">
        {items.map((item, i) => {
          const on = isOn(i);
          return (
            <li
              key={item.key}
              className="kr-fit-card"
              data-fit-index={i}
              data-reading={reading === i ? "" : undefined}
              data-on={on ? "" : undefined}
            >
              <span className="kr-fit-kind">
                {item.kind === "must" ? "Wymagane" : "Mile widziane"}
              </span>
              <span className="kr-fit-name">{item.name}</span>
              <span className="kr-fit-text">
                {item.note ??
                  (item.kind === "must"
                    ? `Na rozmowie ${recruiterFirstName} zapyta o Twoje doświadczenie.`
                    : "Nie musisz tego znać, ale pomaga na starcie.")}
              </span>
              <button
                type="button"
                className="kr-fit-btn"
                aria-pressed={on}
                aria-label={`Znam to: ${item.name}`}
                onClick={() => toggle(i)}
              >
                <svg
                  viewBox="0 0 24 24"
                  width="16"
                  height="16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  aria-hidden="true"
                >
                  <path d="M5 12l5 5L20 7" />
                </svg>
                Znam to
              </button>
            </li>
          );
        })}
        {extraMust.map((m) => (
          <li key={`m-${m.name}`} className="kr-fit-card">
            <span className="kr-fit-kind">Wymagane</span>
            <span className="kr-fit-name">{m.name}</span>
            {m.note ? <span className="kr-fit-text">{m.note}</span> : null}
          </li>
        ))}
        {extraNice.length > 0 ? (
          <li className="kr-fit-card">
            <span className="kr-fit-kind">Mile widziane</span>
            <span className="kr-fit-name">{extraNice.join(" · ")}</span>
          </li>
        ) : null}
      </ul>
    </section>
  );
}
