// Klocki interfejsu panelu. Treść zawsze przez textContent — dane z LinkedIna
// i z NEXUSA nigdy nie trafiają do innerHTML.

/**
 * h("button", {class: "btn", onClick: fn}, "Tekst", childNode)
 * Atrybuty `on*` to zdarzenia, `class`, `text`, `hidden`, `disabled`, `value`,
 * `checked` ustawiane jako właściwości, reszta jako atrybuty.
 */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (["hidden", "disabled", "checked", "value", "selected", "multiple", "required"].includes(k)) el[k] = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false || c === "") continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function pill(text, tone = "muted", extraClass = "") {
  return h("span", { class: `pill pill--${tone} ${extraClass}`.trim() }, text);
}

export function frame(tone, ...children) {
  return h("div", { class: `frame frame--${tone}`, role: tone === "error" || tone === "warning" ? "alert" : null }, ...children);
}

export function section(title, ...children) {
  return h("section", { class: "section" }, title ? h("h3", { class: "section__title" }, title) : null, ...children);
}

export function button(label, onClick, { variant = "secondary", disabled = false, type = "button", extraClass = "" } = {}) {
  return h("button", { type, class: `btn btn--${variant} ${extraClass}`.trim(), onClick, disabled }, label);
}

export function linkButton(label, onClick, extraClass = "") {
  return h("button", { type: "button", class: `link ${extraClass}`.trim(), onClick }, label);
}

/** Link zewnętrzny tylko dla http(s) — adres z API też jest danymi z zewnątrz. */
export function safeHref(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

export function externalLink(label, url, extraClass = "") {
  const href = safeHref(url);
  if (!href) return null;
  return h("a", { class: `link ${extraClass}`.trim(), href, target: "_blank", rel: "noopener noreferrer" }, label);
}

/** Pole, którego czytnik nie odczytał — zamiast pustki. */
export function missing(onClick) {
  return h("button", { type: "button", class: "missing", onClick }, "nie odczytano — wpisz");
}

export function segmented(options, value, onChange, name) {
  return h(
    "div",
    { class: "segmented", role: "radiogroup", "aria-label": name },
    options.map((o) =>
      h(
        "button",
        {
          type: "button",
          role: "radio",
          "aria-checked": String(o.value === value),
          class: `segmented__item ${o.value === value ? "is-active" : ""}`,
          onClick: () => onChange(o.value),
        },
        o.label,
      ),
    ),
  );
}

export function skeleton() {
  return h(
    "div",
    { class: "skeleton", "aria-busy": "true", "aria-label": "Wczytywanie" },
    h("div", { class: "skeleton__line skeleton__line--short" }),
    h("div", { class: "skeleton__line skeleton__line--title" }),
    h("div", { class: "skeleton__line" }),
    h("div", { class: "skeleton__block" }),
    h("div", { class: "skeleton__line" }),
    h("div", { class: "skeleton__line skeleton__line--short" }),
  );
}

export function spinnerLabel(text) {
  return h("span", { class: "busy" }, h("span", { class: "busy__dot", "aria-hidden": "true" }), text);
}
