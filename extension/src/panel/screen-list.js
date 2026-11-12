// Ekran 6: lista wyników wyszukiwania / projekt w Recruiterze.
// Odczyt strony tylko po kliknięciu „Sprawdź tę stronę”.

import { ERROR_KINDS } from "../api.js";
import { BATCH_STATUS, defaultSelected, isSelectable, profileFromListPerson } from "../view/logic.js";
import { apiErrorText } from "./errors.js";
import { degreeLabel, isTodo, lastContactLine, listForClipboard, triage } from "../view/outreach.js";
import { button, frame, h, pill, segmented, spinnerLabel } from "./ui.js";

const TITLES = {
  search: "Wyniki wyszukiwania",
  recruiter_search: "Wyszukiwanie w Recruiterze",
  recruiter_project: "Projekt w Recruiterze",
};

export function initialListState() {
  return { people: null, items: null, selected: new Set(), results: {}, busy: false, adding: false, error: null, skipped: 0, truncated: false, filter: "all" };
}

function rowResult(r) {
  if (!r) return null;
  return h("span", { class: `row-result row-result--${r.tone}` }, r.text);
}

async function addSelected(ctx, ls) {
  ls.adding = true;
  ls.error = null;
  ctx.render();
  const jobId = ctx.state.activeJob?.id ?? null;
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

/** Telefon w NEXUSIE, kontakt zespołu i stopień: zamiast spotlightów, których Lite nie ma. */
function rowExtras(person, item) {
  const parts = [];
  if (item?.has_phone && item.candidate_id) parts.push(pill("☎ telefon w NEXUSIE", "info"));
  const contact = lastContactLine(item?.last_contact);
  if (contact) parts.push(contact.tone === "warning" ? pill(contact.text, "warning") : h("span", { class: "result__sub muted" }, contact.text));
  if (item?.status === "new" && person.degree && person.degree < 3) {
    parts.push(h("span", { class: "result__sub muted" }, `${degreeLabel(person.degree)} · ${person.degree === 1 ? "wiadomość" : "zaproszenie"} zamiast InMaila`));
  }
  return parts.length ? h("span", { class: "result__extra" }, parts) : null;
}

function triageCard(ctx, ls) {
  const t = triage(ls.items);
  const rest = [
    t.inBase ? pill(`w NEXUSIE ${t.inBase}${t.withPhone ? `, z telefonem ${t.withPhone}` : ""}`, "muted") : null,
    t.recent ? pill(`kontakt zespołu < 30 dni: ${t.recent}`, "warning") : null,
    t.offLimits ? pill(`off-limits ${t.offLimits}`, "error") : null,
    t.contractors ? pill(`kontraktorzy ${t.contractors}`, "warning") : null,
  ].filter(Boolean);
  return h(
    "div",
    { class: "card triage" },
    h("p", {}, h("strong", {}, `Z ${t.total} osób do przejrzenia ${t.todo}.`), rest.length ? " Reszta:" : ""),
    rest.length ? h("div", { class: "row row--wrap" }, rest) : null,
    segmented(
      [
        { value: "todo", label: `Do przejrzenia (${t.todo})` },
        { value: "all", label: `Wszyscy (${t.total})` },
      ],
      ls.filter,
      (v) => {
        ls.filter = v;
        // Ukryta osoba nie może zostać zaznaczona — „Dodaj zaznaczone” dodałby kogoś, kogo nie widać.
        if (v === "todo") for (const i of [...ls.selected]) if (!isTodo(ls.items.find((it) => it.index === i))) ls.selected.delete(i);
        ctx.render();
      },
      "Które osoby pokazać",
    ),
  );
}

async function copyText(ctx, text, done) {
  try {
    await navigator.clipboard.writeText(text);
    done("Skopiowano.");
  } catch {
    done("Nie udało się skopiować. Zaznacz tekst i skopiuj ręcznie (Ctrl+C).");
  }
  ctx.render();
}

/** Słowa kluczowe i firmy off-limits do filtrów Recruitera; rekruter wkleja je sam. */
function searchKitCard(ctx, ls, job) {
  const kit = ctx.searchKit?.(job.id);
  if (!kit) return null;
  const body = [];
  if (kit.busy) body.push(spinnerLabel("Składam wyszukiwanie…"));
  else if (kit.error) body.push(frame("error", h("p", {}, kit.error)));
  else if (kit.data) {
    const d = kit.data;
    const copy = (label, text) => button(label, () => copyText(ctx, text, (msg) => (ls.kitNotice = msg)), { disabled: !text });
    if (d.keywords) {
      body.push(h("div", { class: "kit__field" }, h("span", { class: "field__label" }, "Słowa kluczowe"), h("pre", { class: "code" }, d.keywords), h("div", { class: "kit__row" }, h("span", { class: "hint" }, "Z tytułu i umiejętności „must” rekrutacji."), copy("Kopiuj", d.keywords))));
    }
    if (d.titles?.length) {
      body.push(h("div", { class: "kit__field" }, h("span", { class: "field__label" }, "Stanowiska"), h("div", { class: "kit__row" }, h("div", { class: "chips" }, d.titles.map((t) => h("span", { class: "chip" }, t))), copy("Kopiuj", listForClipboard(d.titles)))));
    }
    if (d.skills_nice?.length) {
      body.push(h("div", { class: "kit__field" }, h("span", { class: "field__label" }, "Mile widziane (do filtra umiejętności)"), h("div", { class: "chips" }, d.skills_nice.map((t) => h("span", { class: "chip" }, t)))));
    }
    if (d.locations?.length) {
      body.push(h("div", { class: "kit__field" }, h("span", { class: "field__label" }, "Lokalizacja"), h("div", { class: "chips" }, d.locations.map((t) => h("span", { class: "chip" }, t)))));
    }
    if (d.exclude_companies?.length) {
      body.push(
        h(
          "div",
          { class: "kit__field" },
          h("span", { class: "field__label" }, `Wyklucz obecną firmę: off-limits (${d.exclude_companies.length})`),
          h("div", { class: "kit__row" }, h("div", { class: "chips" }, d.exclude_companies.map((t) => h("span", { class: "chip chip--x" }, t))), copy(`Kopiuj ${d.exclude_companies.length}`, listForClipboard(d.exclude_companies))),
        ),
      );
    }
    if (ls.kitNotice) body.push(h("p", { class: "hint" }, ls.kitNotice));
  }
  // Po sprawdzeniu listy zwinięte: na laptopie 1280 × 720 zasłaniałoby wyniki.
  return h(
    "details",
    { class: "section", open: !ls.items },
    h("summary", { class: "section__title kit__summary" }, `Wyszukiwanie do Recruitera · ${job.title}`),
    h("div", { class: "kit" }, body),
  );
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
        rowExtras(person, item),
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

  // Rekrutację wybiera się na pasku „Pracuję nad”, tu tylko mówimy, dokąd trafią osoby.
  const job = state.activeJob;
  const target = h("p", { class: "hint" }, job ? `Dodane osoby trafią do rekrutacji „${job.title}”.` : "Bez rekrutacji na pasku dodane osoby trafią tylko do bazy.");

  const checkLabel = ls.items ? "Sprawdź ponownie" : "Sprawdź tę stronę";
  const check = button(ls.busy ? spinnerLabel("Sprawdzam…") : checkLabel, () => ctx.checkList(), {
    variant: ls.items ? "secondary" : "primary",
    disabled: ls.busy || ls.adding,
    extraClass: "btn--block",
  });

  const parts = [h("h2", { class: "screen__title" }, title), target];
  if (job && state.page.source !== "recruiter_project") parts.push(searchKitCard(ctx, ls, job));

  if (ls.error) parts.push(frame("error", h("p", {}, ls.error)));

  if (ls.items) {
    parts.push(triageCard(ctx, ls));
    if (ls.skipped) parts.push(h("p", { class: "hint" }, `Pominięto ${ls.skipped} poz. bez nazwiska („Członek LinkedIn”).`));
    if (ls.truncated) parts.push(h("p", { class: "hint" }, "Na stronie jest więcej osób — sprawdzam pierwsze 50."));
    const visible = (i) => ls.filter !== "todo" || isTodo(ls.items.find((it) => it.index === i)) || Boolean(ls.results[i]);
    parts.push(h("ul", { class: "results" }, ls.people.map((p, i) => (visible(i) ? personRow(ctx, ls, p, i) : null))));
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
