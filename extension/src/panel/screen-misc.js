// Ekrany 1 (Nie połączono), Serwer, stany: ładowanie, błąd, limit,
// strona nieobsługiwana, strona nieodczytana, kilka podobnych osób.

import { SERVERS } from "../config.js";
import { usageLabel } from "../view/logic.js";
import { button, externalLink, frame, h, linkButton, pill, skeleton } from "./ui.js";

export function renderConnect(ctx) {
  const { state } = ctx;
  const server = SERVERS[state.serverId];
  return h(
    "div",
    { class: "screen screen--center" },
    h("h2", { class: "screen__title" }, "Połącz wtyczkę z NEXUSEM"),
    h("p", { class: "muted" }, "Zaloguj się w NEXUSIE — klucz wtyczki trafi tu sam, niczego nie kopiujesz. Potem otwórz profil albo wyniki wyszukiwania na LinkedInie."),
    state.connectMessage ? frame("info", h("p", {}, state.connectMessage)) : null,
    state.connectPending ? frame("info", h("p", {}, "Czekam na połączenie… Dokończ logowanie w karcie NEXUSA.")) : null,
    button("Zaloguj przez NEXUS", () => ctx.startConnect(), { variant: "primary", extraClass: "btn--block" }),
    h("p", { class: "caption" }, "Serwer: ", linkButton(`${server.label}`, () => ctx.openSettings())),
  );
}

export function renderSettings(ctx) {
  const { state } = ctx;
  let chosen = state.serverId;
  const options = Object.values(SERVERS).map((s) =>
    h(
      "label",
      { class: "radio" },
      h("input", { type: "radio", name: "server", value: s.id, checked: s.id === chosen, onChange: () => (chosen = s.id) }),
      h("span", {}, h("strong", {}, s.label), h("br"), h("span", { class: "muted small" }, s.apiBase ? `${s.frontUrl} · API ${s.apiBase}` : s.frontUrl)),
    ),
  );
  return h(
    "div",
    { class: "screen" },
    h("h2", { class: "screen__title" }, "Serwer"),
    h("fieldset", { class: "radio-group" }, h("legend", { class: "radio-group__legend" }, "Z którym NEXUSEM łączyć wtyczkę?"), options),
    state.connection ? frame("warning", h("p", {}, "Zmiana serwera odłączy wtyczkę — połączysz ją ponownie jednym kliknięciem.")) : null,
    h("div", { class: "row" }, button("Zapisz", () => ctx.saveServer(chosen), { variant: "primary" }), button("Wróć", () => ctx.closeSettings())),
  );
}

export function renderLoading() {
  return h("div", { class: "screen" }, skeleton());
}

export function renderError(ctx) {
  const { state } = ctx;
  return h(
    "div",
    { class: "screen" },
    frame("error", h("p", { class: "frame__title" }, state.error?.message || "Nie udało się połączyć z NEXUSEM. Spróbuj ponownie.")),
    state.error?.retryable === false ? null : button("Spróbuj ponownie", () => ctx.retry(), { variant: "primary" }),
  );
}

export function renderLimit(ctx) {
  const usage = usageLabel(ctx.state.me?.usage);
  return h(
    "div",
    { class: "screen" },
    pill("Limit na dziś", "warning"),
    h("h2", { class: "screen__title" }, "Dzisiejszy limit odczytów wyczerpany, wróć jutro."),
    h("p", { class: "muted" }, "Limit chroni konto LinkedIn przed wyglądem automatu. Dodane dziś osoby są już w NEXUSIE."),
    usage ? h("p", { class: "caption" }, usage) : null,
  );
}

export function renderUnsupported() {
  return h(
    "div",
    { class: "screen screen--center" },
    h("h2", { class: "screen__title" }, "Otwórz profil albo wyniki wyszukiwania na LinkedInie"),
    h(
      "ul",
      { class: "hint-list muted" },
      h("li", {}, "profil: linkedin.com/in/…"),
      h("li", {}, "profil w Recruiterze: linkedin.com/talent/…/profile/…"),
      h("li", {}, "wyniki wyszukiwania osób, wyszukiwanie w Recruiterze albo lista projektu"),
    ),
  );
}

export function renderNotRead(ctx) {
  return h(
    "div",
    { class: "screen" },
    frame("warning", h("p", { class: "frame__title" }, "Nie odczytałem tej strony"), h("p", {}, "Profil mógł się jeszcze nie wczytać. Przewiń go chwilę albo odśwież kartę i spróbuj ponownie.")),
    button("Odczytaj ponownie", () => ctx.retry(), { variant: "primary" }),
  );
}

export function renderAmbiguous(ctx) {
  const { state } = ctx;
  const lookup = state.lookup;
  return h(
    "div",
    { class: "screen" },
    pill("Kilka podobnych osób w NEXUSIE", "warning"),
    h("h2", { class: "person-head__name" }, state.read.profile.full_name || "—"),
    h("p", { class: "muted" }, "NEXUS ma kilka osób o tym imieniu i nazwisku. Sprawdź, czy to któraś z nich, zanim dodasz nową."),
    h(
      "ul",
      { class: "list" },
      lookup.ambiguous.map((a) =>
        h(
          "li",
          { class: "list__item" },
          h("div", { class: "list__body" }, h("span", { class: "list__title" }, a.name), h("span", { class: "list__sub muted" }, a.company || "")),
          externalLink("Otwórz ↗", a.url),
        ),
      ),
    ),
    h("div", { class: "actions" }, button("To nikt z nich — dodaj nową osobę", () => ctx.forceAdd(), { extraClass: "btn--block" })),
  );
}
