"use client";

import type { ComponentType } from "react";

import type { CareerThemeId } from "../themes";
import { BoardScene } from "./BoardScene";
import { C4Scene } from "./C4Scene";
import { ConstellationScene } from "./ConstellationScene";
import { GlitchScene } from "./GlitchScene";
import { PaperScene } from "./PaperScene";
import { PlanScene } from "./PlanScene";
import { useScene } from "./SceneContext";
import { GlitchBug, SceneScore } from "./SceneParts";
import { SequenceScene } from "./SequenceScene";
import { TerminalScene } from "./TerminalScene";
import { TopologyScene } from "./TopologyScene";

/** Sceny gotowe w tym wydaniu; reszta szablonów — sam wygląd (kolejne PR-y). */
const SCENES: Partial<Record<CareerThemeId, ComponentType>> = {
  terminal: TerminalScene,
  sekwencja: SequenceScene,
  glitch: GlitchScene,
  konstelacja: ConstellationScene,
  c4: C4Scene,
  topologia: TopologyScene,
  tablica: BoardScene,
  plan: PlanScene,
  papier: PaperScene,
};

/** Podpis wyniku przy „Aplikuj” — językiem roli. */
const SCORE_LABELS: Partial<Record<CareerThemeId, string>> = {
  terminal: "Twoje dopasowanie",
  sekwencja: "Komunikaty obsłużone",
  glitch: "Testy zaliczone",
  konstelacja: "Gwiazdy połączone",
  c4: "Zaprojektowane",
  topologia: "Łącza zestawione",
  tablica: "W „Mam to”",
  plan: "Zakres pokryty",
  papier: "Kroki na PASS",
};

/** Dla testu: mapa scen zgadza się z `CAREER_SCENE_IDS` (model.ts, czytany też na serwerze). */
export const SCENE_COMPONENT_IDS = Object.keys(SCENES);

/** Scena roli w hero; nic, gdy szablon jeszcze jej nie ma albo nie ma czego zaznaczać. */
export function CareerScene() {
  const { theme, total } = useScene();
  const Scene = SCENES[theme];
  if (!Scene || total === 0) return null;
  return (
    <div className="kr-scene" data-kr-scene={theme}>
      <Scene />
    </div>
  );
}

/** Wynik „x z 5” i „Aplikuj” w panelu parametrów. */
export function CareerSceneScore() {
  const { theme } = useScene();
  const label =
    theme === "glitch" ? (
      <GlitchBug index={2} wrong="Tetsy zaliczone" right="Testy zaliczone" what="literówka w podpisie wyniku" />
    ) : (
      (SCORE_LABELS[theme] ?? "Twoje dopasowanie")
    );
  return <SceneScore label={label} />;
}
