"use client";

import { useState } from "react";

import { checklistSummary, highlightSkill } from "@/lib/career/site";

import { CheckIcon, siteStyles as s } from "./SiteFrame";

export interface ChecklistItem {
  text: string;
  note?: string | null;
}

function Item({ item, skills }: { item: ChecklistItem; skills: readonly string[] }) {
  const h = highlightSkill(item.text, skills);
  return (
    <li>
      <label>
        <input type="checkbox" className={s.srOnly} />
        <span aria-hidden="true" className={s.cb}>
          <CheckIcon />
        </span>
        <span>
          {h.before}
          {h.key ? <b>{h.key}</b> : null}
          {h.after}
          {item.note ? <small> · {item.note}</small> : null}
        </span>
      </label>
    </li>
  );
}

/**
 * Lista „Co już masz?” (plansza OfertaA): kandydat odhacza wymagania i widzi,
 * ile już spełnia. Zaznaczenia nic nie wysyłają — to podpowiedź przed
 * „Aplikuj”, nie filtr. Pogrubienie = krótka nazwa umiejętności z tablicy.
 */
export function OfferChecklist({
  must,
  nice,
  skills,
}: {
  must: ChecklistItem[];
  nice: ChecklistItem[];
  skills: readonly string[];
}) {
  const [req, setReq] = useState(0);
  const [opt, setOpt] = useState(0);
  const total = must.length + nice.length;
  const count = (set: (fn: (n: number) => number) => void) => (e: React.ChangeEvent<HTMLUListElement>) => {
    const target = e.target as unknown as HTMLInputElement;
    if (target.type === "checkbox") set((n) => n + (target.checked ? 1 : -1));
  };

  const group = (
    title: string,
    items: ChecklistItem[],
    done: number,
    onChange: (e: React.ChangeEvent<HTMLUListElement>) => void,
  ) =>
    items.length > 0 ? (
      <>
        <div className={s.gh}>
          <h3>{title}</h3>
          <span className={s.mono}>
            {done} z {items.length}
          </span>
        </div>
        <ul className={s.cl} onChange={onChange}>
          {items.map((item, i) => (
            <Item key={`${i}-${item.text}`} item={item} skills={skills} />
          ))}
        </ul>
      </>
    ) : null;

  return (
    <aside className={s.chk} aria-label="Wymagania">
      <h2>Co już masz?</h2>
      <p className={s.hint}>Zaznacz, co już znasz.</p>
      {group("Wymagane", must, req, count(setReq))}
      {group("Mile widziane", nice, opt, count(setOpt))}
      <div className={s.tally}>
        <span className={s.tallyNum} aria-live="polite">
          {req + opt}/{total}
        </span>
        <p>
          <b>Nie musisz mieć wszystkiego.</b>
          {checklistSummary(must.length, nice.length)}
        </p>
        <a href="#aplikuj" className={s.tallyGo}>
          Aplikuj →
        </a>
      </div>
    </aside>
  );
}
