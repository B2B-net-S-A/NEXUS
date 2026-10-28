// Pytanie „Jak się do nas zgłosił?” — przy firmie off-limits i przy każdym
// zapisie, który dostał 409 `off_limits_confirmation_required`.

import { OFF_LIMITS_HOW, offLimitsText } from "../view/logic.js";
import { frame, h } from "./ui.js";

let groupNo = 0;

/**
 * `message` to zdanie z 409 (`detail.message`) — pokazujemy je nad pytaniem.
 * Ramka z opisem umowy tylko wtedy, gdy wiemy, o jaką firmę i klienta chodzi.
 * @param {{offLimits: object | null, message?: string | null, value: string | null, onChange: (how: string) => void}} options
 */
export function offLimitsQuestion({ offLimits, message = null, value, onChange }) {
  const name = `off-limits-how-${++groupNo}`;
  return h(
    "div",
    { class: "off-limits" },
    message ? frame("error", h("p", {}, message)) : null,
    offLimits?.client_name || offLimits?.company ? frame("error", h("p", {}, offLimitsText(offLimits))) : null,
    h(
      "fieldset",
      { class: "radio-group" },
      h("legend", { class: "radio-group__legend" }, "Jak się do nas zgłosił?"),
      OFF_LIMITS_HOW.map((o) =>
        h(
          "label",
          { class: "radio" },
          h("input", { type: "radio", name, value: o.value, checked: o.value === value, onChange: () => onChange(o.value) }),
          h("span", {}, o.label),
        ),
      ),
    ),
  );
}
