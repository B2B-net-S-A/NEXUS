import { afterEach, describe, expect, it } from "vitest";

import { api } from "@/lib/api";
import { networkAiApi } from "@/lib/api/cvEditorAi";
import { networkCommandApi } from "@/lib/api/cvEditorCommand";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

/**
 * Edytor CV: AI na zaznaczeniu i polecenie dla całego CV liczą model po
 * stronie serwera (polecenie do 60 s: `cv_command_ai._call_model`,
 * `total_timeout=60`). Na CRUD-owym suficie 30 s przeglądarka zrywała żądanie,
 * rekruter widział błąd, a model i tak policzył — i drugie kliknięcie płaciło
 * drugi raz (audyt 13.10.2026). Sprawdzamy efektywny timeout na prawdziwej
 * instancji `api`, bo o nim decyduje axios.
 */

function captureTimeouts(): { timeouts: number[]; restore: () => void } {
  const previous = api.defaults.adapter;
  const timeouts: number[] = [];
  api.defaults.adapter = async (config) => {
    timeouts.push(config.timeout ?? 0);
    return { data: {}, status: 200, statusText: "OK", headers: {}, config, request: {} };
  };
  return {
    timeouts,
    restore: () => {
      api.defaults.adapter = previous;
    },
  };
}

describe("edytor CV — wywołania AI na suficie dla LLM", () => {
  let restore: (() => void) | null = null;

  afterEach(() => {
    restore?.();
    restore = null;
  });

  it("propozycja dla zaznaczenia i plan polecenia czekają tyle, ile model", async () => {
    const captured = captureTimeouts();
    restore = captured.restore;

    await networkAiApi.propose(7, {
      action: "shorten",
      fragment: "Rozwój usług",
      block_text: "Rozwój usług w Java.",
      block_kind: "li",
      section: "experience",
    });
    await networkCommandApi.plan(7, {
      preset: "shorten",
      lines: [{ id: 0, kind: "bullet", text: "Rozwój usług w Java." }],
    });

    expect(captured.timeouts).toEqual([SLOW_ENDPOINT_TIMEOUT_MS, SLOW_ENDPOINT_TIMEOUT_MS]);
  });
});
