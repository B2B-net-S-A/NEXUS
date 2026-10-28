// Ekran 6: lista wyników wyszukiwania / projekt w Recruiterze.
// Odczyt strony tylko po kliknięciu „Sprawdź tę stronę”.

import { ERROR_KINDS } from "../api.js";
import { BATCH_STATUS, batchCounters, defaultSelected, isSelectable, profileFromListPerson } from "../view/logic.js";
import { apiErrorText } from "./errors.js";
import { jobPicker } from "./job-picker.js";
import { button, frame, h, pill, spinnerLabel } from "./ui.js";

const TITLES = {
  search: "Wyniki wyszukiwania",
  recruiter_search: "Wyszukiwanie w Recruiterze",
  recruiter_project: "Projekt w Recruiterze",
};

export function initialListState() {
  return { job: null, people: null, items: null, selected: new Set(), results: {}, busy: false, adding: false, error: null, skipped: 0, truncated: false };
}

function rowResult(r) {
  if (!r) return null;
  return h("span", { class: `row-result row-result--${r.tone}` }, r.text);
}

async function addSelected(ctx, ls) {
  ls.adding = true;
  ls.error = null;
  ctx.render();
  const jobId = ls.job?.id ?? null;
  // Po kolei, nie równolegle — to zapis do bazy, nie wyścig.
  for (const index of [...ls.selected].sort((a, b) => a - b)) {
    const person = ls.people[index];
    const item = ls.items.find((it) => it.index === index) || {};
    try {
      if (item.candidate_id) {
        if (!jobId) {
          ls.results[index] = { tone: "muted", text: "Już w NEXUSIE" };
        } else {
          const res = await ctx.api.addToJobs(item.candidate_id, [jobId]);
          ls.results[index] = (res.assigned_job_ids || []).includes(jobId)
            ? { tone: "success", text: "Dodano do rekrutacji" }
            : { tone: "warning", text: `Pominięto: ${(res.skipped || []).map((s) => s.reason).join("; ") || "bez zmian"}` };
        }
      } else {
        const profile = profileFromListPerson(person, ctx.state.tab.url, ctx.state.page.source);
        const res = await ctx.api.addCandidate(profile, jobId ? [jobId] : []);
        const skipped = res.skipped || [];
        ls.results[index] = skipped.length
          ? { tone: "warning", text: `Dodano do bazy · pominięto rekrutację: ${skipped.map((s) => s.reason).join("; ")}` }
          : { tone: "success", text: res.created === false ? "Już był w NEXUSIE" : "Dodano" };
      }
      ls.selected.delete(index);
    } catch (err) {
      if (err.kind === ERROR_KINDS.KEY_INVALID) return;
      if (err.kind === ERROR_KINDS.DAILY_LIMIT || err.kind === ERROR_KINDS.NETWORK) {
        ls.results[index] = { tone: "error", text: apiErrorText(err) };
        ls.error = apiErrorText(err);
        break;
      }
      ls.results[index] =
        err.kind === ERROR_KINDS.OFF_LIMITS
          ? { tone: "error", text: "Off-limits — otwórz profil, żeby wskazać, jak się zgłosił" }
          : { tone: "error", text: apiErrorText(err) };
    }
    ctx.render();
  }
  ls.adding = false;
  ctx.onWrite();
  ctx.render();
}

function personRow(ctx, ls, person, index) {
  const item = ls.items?.find((it) => it.index === index) || null;
  const selectable = item ? isSelectable(item) : false;
  const status = item ? BATCH_STATUS[item.status] : null;
  return h(
    "li",
    { class: `result ${selectable ? "" : "result--locked"}` },
    h(
      "label",
      { class: "result__label" },
      h("input", {
        type: "checkbox",
        disabled: !selectable || ls.adding || Boolean(ls.results[index]),
        checked: ls.selected.has(index),
        "aria-label": `Zaznacz: ${person.full_name}`,
        onChange: (e) => {
          if (e.target.checked) ls.selected.add(index);
          else ls.selected.delete(index);
          ctx.render();
        },
      }),
      h(
        "span",
        { class: "result__body" },
        h("span", { class: "result__name" }, person.full_name),
        h("span", { class: "result__sub muted" }, person.headline || h("span", { class: "missing-inline" }, "nagłówek nie odczytany")),
        item?.label ? h("span", { class: "result__sub" }, item.label) : null,
        rowResult(ls.results[index]),
      ),
      h(
        "span",
        { class: "result__side" },
        status ? pill(status.pill, status.tone) : null,
      ),
    ),
  );
}

export function renderList(ctx) {
  const { state } = ctx;
  const ls = state.list;
  const title = TITLES[state.page.source] || "Lista osób";

  const picker = jobPicker({
    api: ctx.api,
    value: ls.job,
    noneLabel: "bez rekrutacji (tylko baza)",
    onChange: (job) => {
      ls.job = job;
      ctx.render();
    },
  });

  const checkLabel = ls.items ? "Sprawdź ponownie" : "Sprawdź tę stronę";
  const check = button(ls.busy ? spinnerLabel("Sprawdzam…") : checkLabel, () => ctx.checkList(), {
    variant: ls.items ? "secondary" : "primary",
    disabled: ls.busy || ls.adding,
    extraClass: "btn--block",
  });

  const parts = [h("h2", { class: "screen__title" }, title), h("div", { class: "picker-inline" }, picker)];

  if (ls.error) parts.push(frame("error", h("p", {}, ls.error)));

  if (ls.items) {
    const counts = batchCounters(ls.items);
    parts.push(
      h(
        "div",
        { class: "row row--wrap counters" },
        Object.entries(BATCH_STATUS)
          .filter(([key]) => key !== "contractor" || counts.contractor > 0)
          .map(([key, s]) => pill(`${s.label}: ${counts[key]}`, s.tone)),
      ),
    );
    if (ls.skipped) parts.push(h("p", { class: "hint" }, `Pominięto ${ls.skipped} poz. bez nazwiska („Członek LinkedIn”).`));
    if (ls.truncated) parts.push(h("p", { class: "hint" }, "Na stronie jest więcej osób — sprawdzam pierwsze 50."));
    parts.push(h("ul", { class: "results" }, ls.people.map((p, i) => personRow(ctx, ls, p, i))));
    const n = ls.selected.size;
    parts.push(
      h(
        "div",
        { class: "actions" },
        button(ls.adding ? spinnerLabel("Dodaję…") : `Dodaj zaznaczone (${n})`, () => addSelected(ctx, ls), {
          variant: "primary",
          disabled: n === 0 || ls.adding,
          extraClass: "btn--block",
        }),
        check,
        h("p", { class: "caption" }, "Odczyt tylko po kliknięciu „Sprawdź”, najwyżej jedna strona wyników naraz."),
      ),
    );
  } else {
    parts.push(
      h("p", { class: "muted" }, "Sprawdzę osoby widoczne na tej stronie: kto jest nowy, kto już jest w NEXUSIE, a kogo nie wolno nam zaczepiać."),
      h("div", { class: "actions" }, check, h("p", { class: "caption" }, "Odczyt tylko po kliknięciu „Sprawdź”, najwyżej jedna strona wyników naraz.")),
    );
  }
  return h("div", { class: "screen" }, parts);
}

/** Wynik odczytu + lookup-batch → stan listy (domyślnie zaznaczeni nowi). */
export function applyBatch(ls, read, batch) {
  ls.people = read.people;
  ls.skipped = read.skipped;
  ls.truncated = read.truncated;
  ls.items = batch.items;
  ls.results = {};
  ls.selected = new Set(batch.items.filter((it) => isSelectable(it) && defaultSelected(it)).map((it) => it.index));
}
