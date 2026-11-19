"use client";
// Rejestr zakładek makiety strony kontraktu. Każda zakładka to osobny plik,
// żeby warianty dało się budować równolegle bez konfliktów.
import type { ComponentType } from "react";
import type { TabKeyA } from "../shell/ShellA";
import type { TabKeyB } from "../shell/ShellB";
import type { TabProps } from "./types";
import { PrzegladA } from "./PrzegladA";
import { PieniadzeA } from "./PieniadzeA";
import { DokumentyA } from "./DokumentyA";
import { AneksyA } from "./AneksyA";
import { OpiekaA } from "./OpiekaA";
import { StartA } from "./StartA";
import { HistoriaA } from "./HistoriaA";
import { AktywnoscB } from "./AktywnoscB";
import { DokumentyB } from "./DokumentyB";
import { AneksyB } from "./AneksyB";
import { OpiekaB } from "./OpiekaB";
import { WejscieB } from "./WejscieB";
import { SprzetB } from "./SprzetB";
import { FakturyB } from "./FakturyB";

export const TAB_COMPONENTS_A: Record<TabKeyA, ComponentType<TabProps>> = {
  przeglad: PrzegladA,
  pieniadze: PieniadzeA,
  dokumenty: DokumentyA,
  aneksy: AneksyA,
  opieka: OpiekaA,
  start: StartA,
  historia: HistoriaA,
};

export const TAB_COMPONENTS_B: Record<TabKeyB, ComponentType<TabProps>> = {
  aktywnosc: AktywnoscB,
  dokumenty: DokumentyB,
  aneksy: AneksyB,
  opieka: OpiekaB,
  wejscie: WejscieB,
  sprzet: SprzetB,
  faktury: FakturyB,
};
