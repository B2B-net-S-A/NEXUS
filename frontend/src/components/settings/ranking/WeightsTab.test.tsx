import { fireEvent, render, screen } from "@testing-library/react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RankingKnownPoints } from "@/lib/api";

import { panelState } from "./previewFixtures";
import { WeightsTab } from "./WeightsTab";

vi.mock("./LivePreview", () => ({ LivePreview: () => null }));
vi.mock("./ScoringProfilesAdmin", () => ({ ScoringProfilesAdmin: () => null }));

/** Render dłuższy niż 5 ms: planista Reacta oddaje wątek zaraz po commicie,
 *  więc efekty montowania czekają na kolejne zadanie. Tak wygląda obciążony runner. */
function SlowRender() {
  const until = performance.now() + 10;
  while (performance.now() < until);
  return null;
}

const actEnv = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };

describe("WeightsTab — „Znamy tę osobę”", () => {
  afterEach(() => {
    actEnv.IS_REACT_ACT_ENVIRONMENT = true;
    document.body.innerHTML = "";
  });

  it("ruch suwaka tuż po zamontowaniu nie ginie (bieg 41480150399)", async () => {
    // Poza act(): act() opróżnia efekty od razu i okna by nie było.
    actEnv.IS_REACT_ACT_ENVIRONMENT = false;
    const state = panelState();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    // Mikrozadanie po commicie, jeszcze przed efektami: ten sam moment co
    // `findByLabelText` oddający element do testu pod obciążeniem.
    const moved = new Promise<void>((resolve) => {
      const observer = new MutationObserver(() => {
        const slider = container.querySelector("#ranking-known-client");
        if (!slider) return;
        observer.disconnect();
        fireEvent.change(slider, { target: { value: "9" } });
        resolve();
      });
      observer.observe(container, { childList: true, subtree: true });
    });

    root.render(
      <>
        <SlowRender />
        <WeightsTab
          state={state}
          local={state.published.weights}
          onChange={() => undefined}
          canEdit
          isAdmin={false}
          busy={false}
          actionError={null}
          onDiscard={() => undefined}
          onCheck={() => undefined}
          onSaveKnownPoints={() => undefined}
        />
      </>,
    );
    await moved;

    expect(await screen.findByRole("button", { name: "Zapisz punkty" })).toBeInTheDocument();
    expect(screen.getByLabelText("Zweryfikowana u tego klienta")).toHaveValue("9");
    root.unmount();
  });

  it("nowe wartości z serwera wchodzą na suwaki, te same nie kasują niezapisanego ruchu", () => {
    const tab = (known_points: RankingKnownPoints) => {
      const state = panelState({ known_points });
      return (
        <WeightsTab
          state={state}
          local={state.published.weights}
          onChange={() => undefined}
          canEdit
          isAdmin={false}
          busy={false}
          actionError={null}
          onDiscard={() => undefined}
          onCheck={() => undefined}
          onSaveKnownPoints={() => undefined}
        />
      );
    };
    const saved = { client: 6, note_recent: 8, note_older: 2, max: 15 };
    const { rerender } = render(tab(saved));
    const label = "Zweryfikowana u tego klienta";

    fireEvent.change(screen.getByLabelText(label), { target: { value: "9" } });
    rerender(tab({ ...saved }));
    expect(screen.getByLabelText(label)).toHaveValue("9");

    rerender(tab({ ...saved, client: 10 }));
    expect(screen.getByLabelText(label)).toHaveValue("10");
    expect(screen.queryByRole("button", { name: "Zapisz punkty" })).not.toBeInTheDocument();
  });
});
