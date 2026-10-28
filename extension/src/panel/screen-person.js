// Ekran 3 („Osoba jest w NEXUSIE”) z ramkami off-limits/kontraktor (4)
// i zakładką „Wiadomość” (5).

import { ERROR_KINDS } from "../api.js";
import {
  CONTACT_CHANNELS,
  contractorText,
  formatDate,
  formatMonthYear,
  inNexusSinceLabel,
  jobIdsForHow,
  offLimitsText,
  ownerText,
  processPill,
  rodoLabel,
  rodoTone,
} from "../view/logic.js";
import { apiErrorText } from "./errors.js";
import { jobPicker } from "./job-picker.js";
import { renderMessage } from "./screen-message.js";
import { offLimitsQuestion } from "./off-limits.js";
import { button, externalLink, frame, h, pill, section, segmented, spinnerLabel } from "./ui.js";

export function initialPersonState() {
  return { tab: "person", form: null, job: null, how: null, askHow: null, busy: false, error: null, notice: null, message: null };
}

function processesSection(lookup) {
  if (!lookup.processes.length) return section("W rekrutacjach", h("p", { class: "muted" }, "Jeszcze w żadnej rekrutacji."));
  return section(
    "W rekrutacjach",
    h(
      "ul",
      { class: "list" },
      lookup.processes.map((p) => {
        const st = processPill(p);
        return h(
          "li",
          { class: "list__item" },
          h(
            "div",
            { class: "list__body" },
            h("span", { class: "list__title" }, p.job_title),
            h("span", { class: "list__sub muted" }, [p.client_name, p.recruiter_name].filter(Boolean).join(" · ")),
          ),
          pill(st.text, st.tone),
        );
      }),
    ),
  );
}

function contactsSection(lookup) {
  if (!lookup.contacts.length) return section("Kontakty zespołu", h("p", { class: "muted" }, "Brak zapisanych kontaktów."));
  return section(
    "Kontakty zespołu",
    h(
      "ol",
      { class: "timeline" },
      lookup.contacts.map((c) =>
        h(
          "li",
          { class: "timeline__item" },
          h("span", { class: "timeline__meta muted" }, [formatDate(c.at), c.user_name, c.channel_label].filter(Boolean).join(" · ")),
          c.note ? h("span", { class: "timeline__note" }, c.note) : null,
        ),
      ),
    ),
  );
}

function factsSection(lookup) {
  const rows = [];
  if (lookup.rate) {
    rows.push(
      h(
        "div",
        { class: "kv" },
        h("dt", { class: "kv__label" }, "Stawka od"),
        h("dd", { class: "kv__value" }, lookup.rate.label, lookup.rate.as_of ? h("span", { class: "muted" }, ` · stan na ${formatMonthYear(lookup.rate.as_of)}`) : null),
      ),
    );
  }
  rows.push(h("div", { class: "kv" }, h("dt", { class: "kv__label" }, "RODO"), h("dd", { class: "kv__value" }, pill(rodoLabel(lookup.rodo), rodoTone(lookup.rodo)))));
  return h("dl", { class: "kv-list section" }, rows);
}

// ── Formularze w stopce: + Rekrutacja / Notatka / Kontakt ───────────────────

async function run(ctx, ps, fn) {
  ps.busy = true;
  ps.error = null;
  ps.notice = null;
  ctx.render();
  try {
    await fn();
  } catch (err) {
    if (err.kind === ERROR_KINDS.OFF_LIMITS) {
      ps.askHow = (err.detail && typeof err.detail === "object" ? err.detail : null) || {};
      ps.error = null;
    } else if (err.kind !== ERROR_KINDS.KEY_INVALID) {
      ps.error = apiErrorText(err);
    }
  } finally {
    ps.busy = false;
    ctx.render();
  }
}

function jobForm(ctx, ps, lookup) {
  const candidateId = lookup.candidate.id;
  const needHow = Boolean(ps.askHow);
  const save = () =>
    run(ctx, ps, async () => {
      if (!ps.job) {
        ps.error = "Wybierz rekrutację.";
        return;
      }
      const res = await ctx.api.addToJobs(candidateId, jobIdsForHow(ps.how, [ps.job.id]), needHow ? ps.how : null);
      const skipped = res.skipped || [];
      if ((res.assigned_job_ids || []).includes(ps.job.id)) ps.notice = `Dodano do rekrutacji „${ps.job.title}”.`;
      else if (skipped.length) ps.error = `Nie dodano: ${skipped.map((s) => s.reason).join("; ")}`;
      else ps.notice = "Zapisano — osoba jest w bazie, bez nowej rekrutacji.";
      ps.form = null;
      ps.askHow = null;
      ps.how = null;
      ctx.onWrite();
    });
  return h(
    "div",
    { class: "form card" },
    h("h3", { class: "section__title" }, "Dodaj do rekrutacji"),
    jobPicker({ api: ctx.api, value: ps.job, noneLabel: null, onChange: (job) => {
      ps.job = job;
    } }),
    needHow
      ? offLimitsQuestion({
          offLimits: lookup.off_limits,
          message: typeof ps.askHow.message === "string" ? ps.askHow.message : null,
          value: ps.how,
          onChange: (how) => {
            ps.how = how;
            ctx.render();
          },
        })
      : null,
    h("div", { class: "row" }, button(ps.busy ? spinnerLabel("Zapisuję…") : "Dodaj", save, { variant: "primary", disabled: ps.busy || (needHow && !ps.how) }), button("Anuluj", () => closeForm(ctx, ps))),
  );
}

function noteForm(ctx, ps, lookup) {
  const text = h("textarea", {
    class: "input textarea",
    rows: "4",
    placeholder: "Notatka widoczna w NEXUSIE przy tej osobie",
    "aria-label": "Treść notatki",
    value: ps.noteText || "",
    onInput: (e) => (ps.noteText = e.target.value),
  });
  const save = () =>
    run(ctx, ps, async () => {
      const value = text.value.trim();
      if (!value) {
        ps.error = "Wpisz treść notatki.";
        return;
      }
      await ctx.api.addNote(lookup.candidate.id, value);
      ps.form = null;
      ps.noteText = "";
      ps.notice = "Notatka zapisana w NEXUSIE.";
      ctx.onWrite();
    });
  if (!ps.busy) queueMicrotask(() => text.focus());
  return h(
    "div",
    { class: "form card" },
    h("h3", { class: "section__title" }, "Notatka"),
    text,
    h("div", { class: "row" }, button(ps.busy ? spinnerLabel("Zapisuję…") : "Zapisz notatkę", save, { variant: "primary", disabled: ps.busy }), button("Anuluj", () => closeForm(ctx, ps))),
  );
}

function contactForm(ctx, ps, lookup) {
  const st = (ps.contact ||= { channel: "inmail", jobId: null, remind: false, days: 3, note: "" });
  const note = h("textarea", {
    class: "input textarea",
    rows: "3",
    placeholder: "Co ustaliliście? (opcjonalnie)",
    "aria-label": "Notatka do kontaktu",
    value: st.note,
    onInput: (e) => (st.note = e.target.value),
  });
  const openJobs = lookup.processes.filter((p) => !p.closed);
  const jobSelect = h(
    "select",
    { class: "input", "aria-label": "Rekrutacja", onChange: (e) => (st.jobId = e.target.value ? Number(e.target.value) : null) },
    h("option", { value: "" }, "— bez rekrutacji"),
    openJobs.map((p) => h("option", { value: String(p.job_id), selected: st.jobId === p.job_id }, `${p.job_title}${p.client_name ? ` · ${p.client_name}` : ""}`)),
  );
  const days = h("input", { type: "number", min: "1", max: "60", class: "input input--narrow", value: String(st.days), "aria-label": "Za ile dni", onInput: (e) => (st.days = Number(e.target.value) || 3) });
  const save = () =>
    run(ctx, ps, async () => {
      const res = await ctx.api.addContact(lookup.candidate.id, {
        channel: st.channel,
        jobId: st.jobId,
        note: note.value.trim(),
        remindInDays: st.remind ? Math.max(1, Math.min(60, st.days)) : null,
      });
      ps.form = null;
      ps.contact = null;
      ps.notice = res.reminder_id ? `Kontakt zapisany. Przypomnienie za ${st.days} dni.` : "Kontakt zapisany.";
      ctx.onWrite();
      ctx.addLocalContact(st.channel, note.value.trim());
    });
  return h(
    "div",
    { class: "form card" },
    h("h3", { class: "section__title" }, "Zapisz kontakt"),
    segmented(CONTACT_CHANNELS, st.channel, (v) => {
      st.channel = v;
      ctx.render();
    }, "Kanał kontaktu"),
    jobSelect,
    note,
    h(
      "label",
      { class: "checkbox" },
      h("input", { type: "checkbox", checked: st.remind, onChange: (e) => (st.remind = e.target.checked) }),
      h("span", {}, "Przypomnij za"),
      days,
      h("span", {}, "dni"),
    ),
    h("div", { class: "row" }, button(ps.busy ? spinnerLabel("Zapisuję…") : "Zapisz kontakt", save, { variant: "primary", disabled: ps.busy }), button("Anuluj", () => closeForm(ctx, ps))),
  );
}

function closeForm(ctx, ps) {
  ps.form = null;
  ps.askHow = null;
  ps.how = null;
  ps.error = null;
  ctx.render();
}

function openForm(ctx, ps, form) {
  ps.form = ps.form === form ? null : form;
  ps.error = null;
  ps.notice = null;
  ps.askHow = null;
  ctx.render();
}

async function refreshInNexus(ctx, ps, lookup) {
  await run(ctx, ps, async () => {
    const res = await ctx.api.refresh(lookup.candidate.id, ctx.state.read.profile);
    const n = (res.updated || []).length;
    ps.notice = n ? "Zaktualizowano firmę i stanowisko w NEXUSIE." : "NEXUS ma już te dane — nic do zmiany.";
    ps.jobChangeDone = true;
    ctx.onWrite();
  });
}

export function renderPerson(ctx) {
  const { state } = ctx;
  const lookup = state.lookup;
  const ps = state.person;
  const c = lookup.candidate;

  const head = h(
    "div",
    { class: "person-head" },
    h(
      "div",
      { class: "row row--between" },
      h("div", { class: "row row--wrap" }, pill(inNexusSinceLabel(c), "success"), lookup.off_limits ? pill("Off-limits", "error") : null, lookup.contractor ? pill("Kontraktor", "warning") : null),
      externalLink("Otwórz w NEXUSIE ↗", c.url),
    ),
    h("h2", { class: "person-head__name" }, c.name || state.read.profile.full_name || "—"),
    h("p", { class: "person-head__sub muted" }, [c.headline, c.city].filter(Boolean).join(" · ") || state.read.profile.headline || ""),
  );

  const tabs = segmented(
    [
      { value: "person", label: "Osoba" },
      { value: "message", label: "Wiadomość" },
    ],
    ps.tab,
    (v) => {
      ps.tab = v;
      ctx.render();
    },
    "Widok osoby",
  );

  if (ps.tab === "message") {
    return h("div", { class: "screen" }, head, tabs, renderMessage(ctx));
  }

  const frames = [
    lookup.contractor ? frame("warning", h("p", {}, contractorText(lookup.contractor))) : null,
    lookup.off_limits ? frame("error", h("p", {}, offLimitsText(lookup.off_limits))) : null,
    lookup.owner && !lookup.owner.is_me ? frame("warning", h("p", {}, ownerText(lookup.owner))) : null,
    lookup.job_change && !ps.jobChangeDone
      ? frame(
          "info",
          h("p", {}, `Zmiana pracy? Na LinkedInie: ${lookup.job_change.page_company || "—"}, w NEXUSIE: ${lookup.job_change.nexus_company || "—"}.`),
          button("Zaktualizuj w NEXUSIE", () => refreshInNexus(ctx, ps, lookup), { disabled: ps.busy }),
        )
      : null,
  ];

  const forms = { job: jobForm, note: noteForm, contact: contactForm };
  // Formularz w zwykłym przepływie nad stopką — w przyklejonej stopce zasłaniałby
  // pół panelu na laptopie 1280 × 720.
  const form = ps.form ? forms[ps.form](ctx, ps, lookup) : null;
  if (form && !ps.busy) queueMicrotask(() => form.scrollIntoView?.({ block: "nearest" }));

  const footer = h(
    "div",
    { class: "actions" },
    ps.notice ? frame("success", h("p", {}, ps.notice)) : null,
    ps.error ? frame("error", h("p", {}, ps.error)) : null,
    h(
      "div",
      { class: "row row--even" },
      button("+ Rekrutacja", () => openForm(ctx, ps, "job"), { variant: ps.form === "job" ? "primary" : "secondary" }),
      button("Notatka", () => openForm(ctx, ps, "note"), { variant: ps.form === "note" ? "primary" : "secondary" }),
      button("Kontakt", () => openForm(ctx, ps, "contact"), { variant: ps.form === "contact" ? "primary" : "secondary" }),
    ),
  );

  return h("div", { class: "screen" }, head, tabs, frames, processesSection(lookup), contactsSection(lookup), factsSection(lookup), form, footer);
}
