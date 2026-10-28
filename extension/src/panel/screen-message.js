// Ekran 5: szkic wiadomości. Wtyczka niczego nie wysyła — tekst się kopiuje,
// a po wysłaniu na LinkedInie rekruter zapisuje kontakt jednym kliknięciem.

import { ERROR_KINDS } from "../api.js";
import { MESSAGE_KINDS, defaultJobId } from "../view/logic.js";
import { apiErrorText } from "./errors.js";
import { jobPicker } from "./job-picker.js";
import { button, frame, h, segmented, spinnerLabel } from "./ui.js";

const REMIND_OPTIONS = [
  { value: "", label: "Bez przypomnienia" },
  { value: "1", label: "Przypomnij jutro" },
  { value: "3", label: "Przypomnij za 3 dni" },
  { value: "7", label: "Przypomnij za 7 dni" },
  { value: "14", label: "Przypomnij za 14 dni" },
];

function jobPresets(lookup) {
  const fromProcesses = lookup.processes
    .filter((p) => !p.closed)
    .map((p) => ({ id: p.job_id, title: p.job_title, client_name: p.client_name, recruiter_name: p.recruiter_name }));
  const fromMatches = lookup.matches.map((m) => ({ id: m.job_id, title: m.title, client_name: m.client_name, recruiter_name: m.recruiter_name }));
  return [...fromProcesses, ...fromMatches];
}

function messageState(ctx) {
  const ps = ctx.state.person;
  if (!ps.message) {
    const presets = jobPresets(ctx.state.lookup);
    const id = defaultJobId(ctx.state.lookup);
    ps.message = {
      job: presets.find((j) => j.id === id) || null,
      kind: "inmail",
      text: "",
      ai: null,
      busy: false,
      error: null,
      notice: null,
      remind: "3",
      requested: false,
    };
  }
  return ps.message;
}

async function draft(ctx, ms) {
  if (!ms.job) {
    ms.error = "Wybierz rekrutację, do której piszesz.";
    ctx.render();
    return;
  }
  ms.busy = true;
  ms.error = null;
  ms.notice = null;
  ms.requested = true;
  ctx.render();
  try {
    const res = await ctx.api.draftMessage(ms.job.id, ms.kind, ctx.state.read.profile);
    ms.text = typeof res.text === "string" ? res.text : "";
    ms.ai = res.ai !== false;
  } catch (err) {
    if (err.kind !== ERROR_KINDS.KEY_INVALID) ms.error = apiErrorText(err);
  } finally {
    ms.busy = false;
    ctx.render();
  }
}

async function copy(ctx, ms, textarea) {
  try {
    await navigator.clipboard.writeText(ms.text);
    ms.notice = "Skopiowano. Wklej tekst na LinkedInie i wyślij.";
  } catch {
    // Zapas, gdy przeglądarka nie da dostępu do schowka (panel bez fokusu).
    textarea.select();
    const ok = document.execCommand("copy");
    ms.notice = ok ? "Skopiowano. Wklej tekst na LinkedInie i wyślij." : null;
    ms.error = ok ? null : "Nie udało się skopiować. Zaznacz tekst i skopiuj ręcznie (Ctrl+C).";
  }
  ctx.render();
}

async function saveContact(ctx, ms) {
  const channel = MESSAGE_KINDS.find((k) => k.value === ms.kind).channel;
  ms.busy = true;
  ms.error = null;
  ctx.render();
  try {
    const res = await ctx.api.addContact(ctx.state.lookup.candidate.id, {
      channel,
      jobId: ms.job?.id ?? null,
      note: ms.text.slice(0, 4000),
      remindInDays: ms.remind ? Number(ms.remind) : null,
    });
    ms.notice = res.reminder_id ? `Kontakt zapisany. Przypomnienie za ${ms.remind} dni.` : "Kontakt zapisany.";
    ctx.onWrite();
    ctx.addLocalContact(channel, ms.job ? `rekrutacja: ${ms.job.title}` : null);
  } catch (err) {
    if (err.kind !== ERROR_KINDS.KEY_INVALID) ms.error = apiErrorText(err);
  } finally {
    ms.busy = false;
    ctx.render();
  }
}

export function renderMessage(ctx) {
  const ms = messageState(ctx);
  const kind = MESSAGE_KINDS.find((k) => k.value === ms.kind);
  if (!ms.requested && ms.job && !ms.busy) queueMicrotask(() => draft(ctx, ms));

  const textarea = h("textarea", {
    class: "input textarea textarea--message",
    rows: "9",
    "aria-label": "Treść wiadomości",
    value: ms.text,
    placeholder: ms.busy ? "Piszę szkic…" : "Tu pojawi się szkic wiadomości",
    disabled: ms.busy,
  });
  const over = () => kind.limit && ms.text.length > kind.limit;
  const counter = h("span", { class: "counter muted" });
  const paintCounter = () => {
    counter.textContent = kind.limit ? `${ms.text.length} / ${kind.limit} zn.` : `${ms.text.length} zn.`;
    counter.classList.toggle("counter--over", Boolean(over()));
  };
  textarea.addEventListener("input", () => {
    ms.text = textarea.value;
    paintCounter();
  });
  paintCounter();

  const remind = h(
    "select",
    { class: "input input--compact", "aria-label": "Przypomnienie", onChange: (e) => (ms.remind = e.target.value) },
    REMIND_OPTIONS.map((o) => h("option", { value: o.value, selected: o.value === ms.remind }, o.label)),
  );

  return h(
    "div",
    { class: "stack" },
    jobPicker({
      api: ctx.api,
      value: ms.job,
      noneLabel: null,
      presets: jobPresets(ctx.state.lookup),
      onChange: (job) => {
        ms.job = job;
        draft(ctx, ms);
      },
    }),
    segmented(MESSAGE_KINDS, ms.kind, (v) => {
      ms.kind = v;
      draft(ctx, ms);
    }, "Rodzaj wiadomości"),
    h("div", { class: "message-box" }, textarea, h("div", { class: "row row--between" }, ms.busy ? spinnerLabel("Piszę szkic…") : h("span", { class: "muted small" }, ms.ai === false ? "AI nie odpowiedziało — tekst z szablonu rekrutacji." : ""), counter)),
    ms.error ? frame("error", h("p", {}, ms.error)) : null,
    ms.notice ? frame("success", h("p", {}, ms.notice)) : null,
    h(
      "div",
      { class: "actions" },
      h(
        "div",
        { class: "row row--between" },
        button("Napisz inaczej", () => draft(ctx, ms), { disabled: ms.busy || !ms.job }),
        button("Kopiuj tekst", () => copy(ctx, ms, textarea), { variant: "primary", disabled: ms.busy || !ms.text }),
      ),
      h("div", { class: "row" }, button("Wysłałem, zapisz kontakt", () => saveContact(ctx, ms), { disabled: ms.busy || !ms.text }), remind),
      h("p", { class: "caption" }, "Wtyczka niczego nie wysyła sama. Tekst wklejasz i wysyłasz na LinkedInie."),
    ),
  );
}
