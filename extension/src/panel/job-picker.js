// Wybór rekrutacji „Do: … ▾” — lista z `GET /jobs?q=` z wyszukiwaniem.
// Komponent trzyma swój stan sam, żeby przerysowanie ekranu nie gubiło fokusu.

import { apiErrorText } from "./errors.js";
import { h } from "./ui.js";

const SEARCH_DEBOUNCE_MS = 300;

function jobSubtitle(job) {
  return [job.client_name, job.recruiter_name].filter(Boolean).join(" · ");
}

/**
 * @param {{
 *   api: ReturnType<import("../api.js").createApi>,
 *   value: {id: number, title: string} | null,
 *   onChange: (job: object | null) => void,
 *   label?: string,
 *   noneLabel?: string | null,   // null = nie da się wybrać „bez rekrutacji”
 *   presets?: Array<object>,      // np. rekrutacje osoby — na górze listy
 * }} options
 */
export function jobPicker({ api, value, onChange, label = "Do:", noneLabel = "wybierz rekrutację", presets = [] }) {
  let selected = value || null;
  let open = false;
  let timer = null;
  let requestNo = 0;

  const current = h("span", { class: "picker__value" });
  const toggle = h(
    "button",
    { type: "button", class: "picker__toggle", "aria-haspopup": "listbox", "aria-expanded": "false" },
    h("span", { class: "picker__label" }, label),
    current,
    h("span", { class: "picker__chevron", "aria-hidden": "true" }, "▾"),
  );
  const search = h("input", { type: "search", class: "input", placeholder: "Szukaj rekrutacji…", "aria-label": "Szukaj rekrutacji" });
  const list = h("ul", { class: "picker__list", role: "listbox" });
  const status = h("p", { class: "picker__status muted" });
  const dropdown = h("div", { class: "picker__dropdown", hidden: true }, search, status, list);
  const root = h("div", { class: "picker" }, toggle, dropdown);

  function paintValue() {
    current.textContent = selected ? selected.title : noneLabel || "wybierz rekrutację";
    current.classList.toggle("muted", !selected);
  }

  function choose(job) {
    selected = job;
    paintValue();
    setOpen(false);
    onChange(job);
  }

  function option(job) {
    return h(
      "li",
      {},
      h(
        "button",
        { type: "button", role: "option", "aria-selected": String(selected?.id === job.id), class: "picker__option", onClick: () => choose(job) },
        h("span", { class: "picker__option-title" }, job.title),
        h("span", { class: "picker__option-sub muted" }, jobSubtitle(job)),
      ),
    );
  }

  function paintList(items) {
    list.replaceChildren();
    if (noneLabel !== null) {
      list.append(h("li", {}, h("button", { type: "button", class: "picker__option picker__option--none", onClick: () => choose(null) }, `— ${noneLabel || "bez rekrutacji"}`)));
    }
    const seen = new Set();
    for (const job of [...presets, ...items]) {
      if (seen.has(job.id)) continue;
      seen.add(job.id);
      list.append(option(job));
    }
  }

  async function load(q) {
    const no = ++requestNo;
    status.textContent = "Wczytuję rekrutacje…";
    try {
      const data = await api.jobs(q);
      if (no !== requestNo) return;
      const items = Array.isArray(data.items) ? data.items : [];
      paintList(items);
      status.textContent = items.length || presets.length ? "" : "Brak otwartych rekrutacji dla tego wyszukiwania.";
    } catch (err) {
      if (no !== requestNo) return;
      paintList([]);
      status.textContent = apiErrorText(err);
    }
  }

  function setOpen(next) {
    open = next;
    dropdown.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) {
      load(search.value.trim());
      search.focus();
    }
  }

  toggle.addEventListener("click", () => setOpen(!open));
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => load(search.value.trim()), SEARCH_DEBOUNCE_MS);
  });
  // Klik poza listą zamyka ją (fokus wychodzi poza komponent).
  root.addEventListener("focusout", (e) => {
    if (open && !root.contains(e.relatedTarget)) setOpen(false);
  });
  search.addEventListener("keydown", (e) => {
    if (e.key === "Escape") setOpen(false);
  });

  paintValue();
  return root;
}
