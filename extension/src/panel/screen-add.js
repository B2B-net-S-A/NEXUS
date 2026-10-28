// Ekran 2 („Nie ma w NEXUSIE”) i 4 (off-limits: „Dodaj: sam się zgłosił”).

import { ERROR_KINDS } from "../api.js";
import {
  FIELD_LABELS,
  OFF_LIMITS_SKIP,
  addButtonLabel,
  companySinceLabel,
  contractorText,
  firstName,
  formatTenure,
  offLimitsButtonLabel,
  scoreTone,
  tenureMonths,
  todayLabel,
} from "../view/logic.js";
import { apiErrorText } from "./errors.js";
import { jobPicker } from "./job-picker.js";
import { offLimitsQuestion } from "./off-limits.js";
import { button, externalLink, frame, h, linkButton, missing, pill, section, spinnerLabel } from "./ui.js";

const EDITABLE = ["full_name", "current_title", "current_company", "location", "headline"];

/** Stan ekranu dodawania dla świeżego odczytu. */
export function initialAddState(read) {
  return {
    profile: { ...read.profile },
    editing: false,
    focusField: null,
    selected: new Set(),
    extraJobs: [],
    pdfFile: null,
    how: null,
    askHow: false, // 409 przy firmie, której lookup nie oznaczył jako off-limits
    busy: false,
    error: null,
    result: null,
  };
}

function readRow(label, value, onMissing) {
  return h("div", { class: "kv" }, h("dt", { class: "kv__label" }, label), h("dd", { class: "kv__value" }, value || missing(onMissing)));
}

function readSection(ctx, add) {
  const p = add.profile;
  const startEdit = (field) => () => {
    add.editing = true;
    add.focusField = field;
    ctx.render();
  };

  if (add.editing) {
    const inputs = EDITABLE.map((field) =>
      h(
        "label",
        { class: "field" },
        h("span", { class: "field__label" }, FIELD_LABELS[field]),
        h("input", {
          class: "input",
          value: p[field] || "",
          "data-field": field,
          placeholder: "nie odczytano — wpisz",
          onInput: (e) => {
            p[field] = e.target.value.trim() || null;
          },
        }),
      ),
    );
    const body = h("div", { class: "form" }, inputs, button("Gotowe", () => {
      add.editing = false;
      ctx.render();
    }));
    queueMicrotask(() => {
      const target = body.querySelector(`[data-field="${add.focusField || "full_name"}"]`);
      target?.focus();
    });
    return section("Odczytane z tej strony", body);
  }

  const tenure = formatTenure(tenureMonths(p.experience));
  const skills = p.skills?.length
    ? h("div", { class: "chips" }, p.skills.slice(0, 12).map((s) => h("span", { class: "chip" }, s)))
    : h("span", { class: "muted" }, "nie odczytano");

  return h(
    "section",
    { class: "section" },
    h("div", { class: "section__head" }, h("h3", { class: "section__title" }, "Odczytane z tej strony"), linkButton("Popraw", startEdit("full_name"))),
    h(
      "dl",
      { class: "kv-list" },
      readRow("Osoba", p.full_name, startEdit("full_name")),
      readRow("Stanowisko", p.current_title, startEdit("current_title")),
      readRow("Firma", companySinceLabel(p), startEdit("current_company")),
      readRow("Miasto", p.location, startEdit("location")),
      h("div", { class: "kv" }, h("dt", { class: "kv__label" }, "Staż"), h("dd", { class: "kv__value" }, tenure || h("span", { class: "muted" }, "nie odczytano z historii pracy"))),
    ),
    h("div", { class: "kv-skills" }, h("span", { class: "kv__label" }, "Umiejętności"), skills),
    p.page_kind === "recruiter_profile" && !p.public_url
      ? h("p", { class: "hint" }, "Nie widzę linku do profilu publicznego — NEXUS poszuka po imieniu, nazwisku i firmie.")
      : null,
  );
}

function matchRow(add, job, ctx) {
  const checked = add.selected.has(job.job_id);
  return h(
    "li",
    {},
    h(
      "label",
      { class: "match" },
      h("input", {
        type: "checkbox",
        checked,
        onChange: (e) => {
          if (e.target.checked) add.selected.add(job.job_id);
          else add.selected.delete(job.job_id);
          ctx.render();
        },
      }),
      h(
        "span",
        { class: "match__body" },
        h("span", { class: "match__title" }, job.title),
        h("span", { class: "match__sub muted" }, [job.client_name, job.recruiter_name].filter(Boolean).join(" · ")),
      ),
      job.score != null ? h("span", { class: `score score--${scoreTone(job.score)}` }, `${Math.round(job.score)}%`) : null,
    ),
  );
}

function matchesSection(ctx, add, lookup) {
  const jobs = [...lookup.matches, ...add.extraJobs];
  const picker = jobPicker({
    api: ctx.api,
    value: null,
    label: "+",
    noneLabel: "inna rekrutacja",
    onChange: (job) => {
      if (!job) return;
      if (!jobs.some((j) => j.job_id === job.id)) {
        add.extraJobs.push({ job_id: job.id, title: job.title, client_name: job.client_name, recruiter_name: job.recruiter_name, score: null });
      }
      add.selected.add(job.id);
      ctx.render();
    },
  });
  return section(
    "Pasuje do otwartych rekrutacji",
    jobs.length ? h("ul", { class: "matches" }, jobs.map((j) => matchRow(add, j, ctx))) : h("p", { class: "muted" }, "NEXUS nie znalazł pasujących otwartych rekrutacji."),
    h("div", { class: "picker-inline" }, picker),
  );
}

function jobTitle(lookup, add, id) {
  return [...lookup.matches, ...add.extraJobs].find((j) => j.job_id === id)?.title || `rekrutacja #${id}`;
}

async function submit(ctx, add, lookup, { baseOnly }) {
  const offLimits = lookup.off_limits || add.askHow;
  if (!add.profile.full_name) {
    add.error = "Wpisz imię i nazwisko — bez tego NEXUS nie założy osoby.";
    add.editing = true;
    add.focusField = "full_name";
    ctx.render();
    return;
  }
  if (offLimits && !add.how) {
    add.error = "Zaznacz, jak osoba się do nas zgłosiła.";
    ctx.render();
    return;
  }
  const jobIds = baseOnly || add.how === OFF_LIMITS_SKIP ? [] : [...add.selected];
  add.busy = true;
  add.error = null;
  ctx.render();
  try {
    const res = await ctx.api.addCandidate(add.profile, jobIds, offLimits ? add.how : null);
    let pdf = null;
    if (add.pdfFile && res.candidate_id) {
      try {
        await ctx.api.uploadProfilePdf(res.candidate_id, add.pdfFile);
        pdf = { ok: true };
      } catch (err) {
        pdf = { ok: false, message: apiErrorText(err) };
      }
    }
    add.result = { ...res, pdf };
    ctx.onWrite();
  } catch (err) {
    if (err.kind === ERROR_KINDS.OFF_LIMITS) {
      add.askHow = (err.detail && typeof err.detail === "object" ? err.detail : null) || {};
      add.error = "Ta firma jest off-limits. Zaznacz, jak osoba się do nas zgłosiła, i dodaj ponownie.";
    } else if (err.kind === ERROR_KINDS.KEY_INVALID) {
      return; // panel sam wraca do ekranu połączenia
    } else {
      add.error = apiErrorText(err);
    }
  } finally {
    add.busy = false;
    ctx.render();
  }
}

function resultView(ctx, add, lookup) {
  const r = add.result;
  const assigned = (r.assigned_job_ids || []).map((id) => jobTitle(lookup, add, id));
  return h(
    "div",
    { class: "stack" },
    frame(
      "success",
      h("p", { class: "frame__title" }, r.created === false ? "Ta osoba już była w NEXUSIE" : "Dodano do NEXUSA"),
      assigned.length ? h("p", {}, `Rekrutacje: ${assigned.join(", ")}`) : h("p", {}, "Bez rekrutacji — osoba jest w bazie."),
    ),
    (r.skipped || []).length
      ? frame("warning", h("p", { class: "frame__title" }, "Nie dodano do części rekrutacji"), h("ul", {}, r.skipped.map((s) => h("li", {}, `${jobTitle(lookup, add, s.job_id)}: ${s.reason}`))))
      : null,
    r.pdf ? (r.pdf.ok ? frame("success", h("p", {}, "PDF profilu dołączony.")) : frame("error", h("p", {}, `PDF nie został dołączony: ${r.pdf.message}`))) : null,
    h(
      "div",
      { class: "row" },
      externalLink("Otwórz w NEXUSIE ↗", r.url, "btn btn--secondary"),
      button("Pokaż kartę osoby", () => ctx.refreshLookup(), { variant: "primary" }),
    ),
  );
}

export function renderAdd(ctx) {
  const { state } = ctx;
  const lookup = state.lookup;
  const add = state.add;
  const offLimits = lookup.off_limits || add.askHow;
  const p = add.profile;

  const head = h(
    "div",
    { class: "person-head" },
    h("div", { class: "row row--wrap" }, offLimits ? pill("Off-limits", "error") : pill("Nie ma w NEXUSIE", "muted")),
    h("h2", { class: "person-head__name" }, p.full_name || "Osoba bez nazwiska"),
    p.headline ? h("p", { class: "person-head__sub muted" }, p.headline) : null,
  );

  if (add.result) return h("div", { class: "screen" }, head, resultView(ctx, add, lookup));

  const offLimitsBlock = offLimits
    ? offLimitsQuestion({
        offLimits: lookup.off_limits,
        message: typeof add.askHow?.message === "string" ? add.askHow.message : null,
        value: add.how,
        onChange: (how) => {
          add.how = how;
          add.error = null;
          ctx.render();
        },
      })
    : null;

  const selectedCount = add.how === OFF_LIMITS_SKIP ? 0 : add.selected.size;
  const primaryLabel = offLimits ? offLimitsButtonLabel(add.how) : addButtonLabel(selectedCount);
  const fileInput = h("input", {
    type: "file",
    accept: "application/pdf,.pdf",
    class: "visually-hidden",
    id: "pdf-input",
    onChange: (e) => {
      add.pdfFile = e.target.files?.[0] || null;
      ctx.render();
    },
  });

  const footer = h(
    "div",
    { class: "actions" },
    add.error ? frame("error", h("p", {}, add.error)) : null,
    button(add.busy ? spinnerLabel("Dodaję…") : primaryLabel, () => submit(ctx, add, lookup, { baseOnly: false }), {
      variant: "primary",
      disabled: add.busy || (offLimits && !add.how),
      extraClass: "btn--block",
    }),
    h(
      "div",
      { class: "row row--between" },
      offLimits ? h("span") : button("Tylko do bazy", () => submit(ctx, add, lookup, { baseOnly: true }), { disabled: add.busy }),
      h("label", { class: "btn btn--ghost", for: "pdf-input" }, add.pdfFile ? `PDF: ${add.pdfFile.name}` : "Dołącz PDF profilu"),
      fileInput,
    ),
    h("p", { class: "caption" }, `Źródło: LinkedIn · dodaje ${firstName(state.me?.user?.name) || "ty"} · ${todayLabel()}`),
  );

  return h(
    "div",
    { class: "screen" },
    head,
    lookup.contractor ? frame("warning", h("p", {}, contractorText(lookup.contractor))) : null,
    offLimitsBlock,
    readSection(ctx, add),
    add.how === OFF_LIMITS_SKIP ? null : matchesSection(ctx, add, lookup),
    footer,
  );
}
