import { render, within } from "@testing-library/react";
import { vi } from "vitest";

import type { CareerThemeId } from "../../themes";
import { CareerScene, CareerSceneScore } from "../CareerScene";
import { leftoverNice, processSteps, sceneItems } from "../model";
import { CareerSceneProvider } from "../SceneContext";

export const MUST = [
  { name: "Java Spring Boot", note: "min. 5 lat komercyjnie" },
  { name: "Kafka", note: "architektura zdarzeniowa" },
  { name: "PostgreSQL", note: "schemat i zapytania" },
  { name: "English", note: null },
];
export const NICE = ["Kubernetes", "AWS", "płatności"];

/** Scena z wynikiem, na tych samych danych co strona (4 wymagania + 1 mile widziane). */
export function renderScene(theme: CareerThemeId, opts: { must?: typeof MUST; nice?: string[]; process?: boolean } = {}) {
  const must = opts.must ?? MUST;
  const nice = opts.nice ?? NICE;
  const items = sceneItems(must, nice);
  const utils = render(
    <CareerSceneProvider
      theme={theme}
      items={items}
      extraNice={leftoverNice(nice, items)}
      steps={opts.process === false ? [] : processSteps("Marta", "B2B")}
      recruiterFirstName="Marta"
      login="marta@b2bnetwork"
      handle="senior-java-developer"
    >
      <CareerScene />
      <CareerSceneScore />
    </CareerSceneProvider>,
  );
  return {
    ...utils,
    full: () => within(utils.getByTestId("scene-full")),
    compact: () => within(utils.getByTestId("scene-compact")),
    score: () => within(utils.getByTestId("scene-score")),
  };
}

/** `matchMedia` w jsdom nie istnieje — ustawiamy, które zapytania pasują. */
export function mockMatchMedia(matching: (query: string) => boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: matching(query),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })),
  );
}
