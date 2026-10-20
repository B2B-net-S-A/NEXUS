"use client";

import { useScene } from "./SceneContext";
import { itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Szafa serwerowa (administrator): moduły = wymagania. Kliknięty moduł startuje
 * (pasek rozruchu, diody), rosną usługi i uptime, maleją alerty.
 */
export function rackStats(count: number, total: number): {
  temp: string;
  uptime: string;
  services: number;
  alerts: number;
} {
  return {
    temp: `${19 + count}°C · ${count * 180} W`,
    uptime: count === 0 ? "—" : `99,9${count} %`,
    services: count * 7,
    alerts: Math.max(0, total - count),
  };
}

/** Nazwa modułu jak host w szafie: „srv-01”, „srv-02”… */
export function unitHost(index: number): string {
  return `srv-${String(index + 1).padStart(2, "0")}`;
}

export function RackScene() {
  const { items, isOn, toggle, count, total } = useScene();
  const stats = rackStats(count, total);
  return (
    <>
      <SceneFrame label="Szafa serwerowa: włącz to, co już administrowałeś" className="kr-sc-rack">
        <p className="kr-rack-ruler" aria-hidden="true">
          {["42U", "35U", "28U", "21U", "14U", "7U", "1U"].map((u) => (
            <span key={u}>{u}</span>
          ))}
        </p>
        <div className="kr-rack">
          <span className="kr-rack-rail kr-rack-rail-l" aria-hidden="true" />
          <span className="kr-rack-rail kr-rack-rail-r" aria-hidden="true" />
          <p className="kr-rack-head" aria-hidden="true">
            <span>RACK A-07</span>
            <span>{stats.temp}</span>
          </p>
          {items.map((item, i) => {
            const on = isOn(i);
            return (
              <button
                type="button"
                key={item.key}
                className="kr-rack-unit"
                aria-pressed={on}
                aria-label={itemAria(item)}
                data-on={on ? "" : undefined}
                onClick={() => toggle(i)}
              >
                <span className="kr-rack-vent" aria-hidden="true" />
                <span className="kr-rack-body">
                  <span className="kr-rack-n">
                    {unitHost(i)} · {item.name}
                  </span>
                  {item.note ? <span className="kr-rack-d">{item.note}</span> : null}
                  {on ? <span className="kr-rack-boot" aria-hidden="true" /> : null}
                </span>
                <span className="kr-rack-leds" aria-hidden="true">
                  <span className="kr-rack-led kr-rack-led-a" />
                  <span className="kr-rack-led kr-rack-led-b" />
                  <span className="kr-rack-led kr-rack-led-c" />
                </span>
              </button>
            );
          })}
          <p className="kr-rack-stats" aria-hidden="true">
            <span>
              UPTIME
              <b>{stats.uptime}</b>
            </span>
            <span>
              USŁUGI
              <b>{stats.services}</b>
            </span>
            <span>
              ALERTY
              <b className="kr-rack-alert">{stats.alerts}</b>
            </span>
          </p>
        </div>
      </SceneFrame>
      <SceneList
        head={`RACK A-07 · ${count} z ${total} online`}
        hint="dotknij modułu, który już administrowałeś — wystartuje"
        mark={(on) => (on ? "● ONLINE" : "○ OFF")}
      />
    </>
  );
}
