import type { ParamRow } from "@/lib/career/format";

/** Panel // PARAMETRY: wiersze „etykieta … [wartość]" z bordową kreską. */
export function ParamsPanel({ rows }: { rows: ParamRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="kr-params">
      <h2 className="kr-params-head" style={{ margin: 0, fontWeight: 400 }}>
        {"// PARAMETRY"}
      </h2>
      <dl style={{ margin: 0, display: "contents" }}>
        {rows.map((row) => (
          <div className="kr-kv" key={row.key}>
            <span className="kr-kv-row">
              <dt className="kr-g">{row.label}</dt>
              <dd style={{ margin: 0 }}>[{row.value}]</dd>
            </span>
            <span className="kr-kv-bar" aria-hidden="true" />
          </div>
        ))}
      </dl>
    </div>
  );
}
