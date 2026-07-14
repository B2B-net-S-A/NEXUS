#!/usr/bin/env node

import { spawnSync } from "node:child_process"
import { readFileSync, writeFileSync } from "node:fs"
import { resolve } from "node:path"

const ROOT_SCHEMAS = [
  "AnalyticsPeriodSchema",
  "AnalyticsQuality",
  "CallsData",
  "ClientFinanceData",
  "ClientOperationsData",
  "DeliveryLeadPerformanceData",
  "ExecutiveBoardData",
  "FinanceClientsData",
  "FinanceSummaryData",
  "FinanceTrendData",
  "FinancialAdjustmentsData",
  "MetricsMetaData",
  "OverviewData",
  "PersonalKpiData",
  "PipelineSnapshotData",
  "RecentHiresData",
  "RecruitmentFunnelData",
  "RecruitmentUserData",
  "SourcesData",
  "TeamCallsData",
  "TeamKpisData",
  "TendersData",
]

const args = process.argv.slice(2)
const checkOnly = args.includes("--check")
const schemaArgIndex = args.indexOf("--schema")
const schemaPath = schemaArgIndex >= 0 ? args[schemaArgIndex + 1] : null
const outputPath = resolve("src/lib/analytics.generated.ts")

function loadOpenApi() {
  if (schemaPath) return JSON.parse(readFileSync(resolve(schemaPath), "utf8"))

  const python = process.env.PYTHON ?? "python"
  const result = spawnSync(
    python,
    [
      "-c",
      "import json; from app.main import app; print(json.dumps(app.openapi()))",
    ],
    {
      cwd: resolve("../backend"),
      encoding: "utf8",
      env: { ...process.env, PYTHONPATH: "." },
      maxBuffer: 64 * 1024 * 1024,
    },
  )
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "unknown Python error").trim()
    throw new Error(
      `Could not export backend OpenAPI. Install backend dependencies or pass --schema <openapi.json>.\n${detail}`,
    )
  }
  return JSON.parse(result.stdout)
}

function refName(ref) {
  const prefix = "#/components/schemas/"
  if (!ref.startsWith(prefix)) throw new Error(`Unsupported schema ref: ${ref}`)
  return ref.slice(prefix.length)
}

function collectReferencedSchemas(schema, target) {
  if (!schema || typeof schema !== "object") return
  if (typeof schema.$ref === "string") {
    target.add(refName(schema.$ref))
  }
  for (const value of Object.values(schema)) {
    if (Array.isArray(value)) {
      value.forEach((item) => collectReferencedSchemas(item, target))
    } else if (value && typeof value === "object") {
      collectReferencedSchemas(value, target)
    }
  }
}

function propertyName(name) {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name) ? name : JSON.stringify(name)
}

function literal(value) {
  return typeof value === "string" ? JSON.stringify(value) : String(value)
}

function schemaToType(schema) {
  if (!schema || typeof schema !== "object") return "unknown"
  if (typeof schema.$ref === "string") return refName(schema.$ref)
  if (Object.hasOwn(schema, "const")) return literal(schema.const)
  if (Array.isArray(schema.enum)) return schema.enum.map(literal).join(" | ")
  if (Array.isArray(schema.anyOf)) {
    return schema.anyOf.map(schemaToType).join(" | ")
  }
  if (Array.isArray(schema.oneOf)) {
    return schema.oneOf.map(schemaToType).join(" | ")
  }
  if (Array.isArray(schema.allOf)) {
    return schema.allOf.map(schemaToType).join(" & ")
  }
  if (Array.isArray(schema.type)) {
    return schema.type.map((type) => schemaToType({ ...schema, type })).join(" | ")
  }
  if (schema.type === "null") return "null"
  if (schema.type === "string") return "string"
  if (schema.type === "integer" || schema.type === "number") return "number"
  if (schema.type === "boolean") return "boolean"
  if (schema.type === "array") {
    const itemType = schemaToType(schema.items)
    return itemType.includes(" | ") ? `Array<${itemType}>` : `${itemType}[]`
  }
  if (schema.type === "object" || schema.properties || schema.additionalProperties) {
    if (schema.properties) {
      const required = new Set(schema.required ?? [])
      const fields = Object.entries(schema.properties).map(
        ([name, value]) =>
          `${propertyName(name)}${required.has(name) ? "" : "?"}: ${schemaToType(value)}`,
      )
      return `{ ${fields.join("; ")} }`
    }
    if (schema.additionalProperties === true) return "Record<string, unknown>"
    if (schema.additionalProperties) {
      return `Record<string, ${schemaToType(schema.additionalProperties)}>`
    }
    return "Record<string, never>"
  }
  return "unknown"
}

function renderNamedSchema(name, schema) {
  if (schema.type === "object" || schema.properties) {
    const required = new Set(schema.required ?? [])
    const properties = Object.entries(schema.properties ?? {}).map(
      ([property, value]) =>
        `  ${propertyName(property)}${required.has(property) ? "" : "?"}: ${schemaToType(value)}`,
    )
    return `export interface ${name} {\n${properties.join("\n")}\n}`
  }
  return `export type ${name} = ${schemaToType(schema)}`
}

function generate(spec) {
  const schemas = spec?.components?.schemas
  if (!schemas || typeof schemas !== "object") {
    throw new Error("OpenAPI document has no components.schemas")
  }

  const selected = new Set(ROOT_SCHEMAS)
  for (const root of ROOT_SCHEMAS) {
    if (!schemas[root]) throw new Error(`OpenAPI is missing analytics schema ${root}`)
  }

  let previousSize = -1
  while (selected.size !== previousSize) {
    previousSize = selected.size
    for (const name of [...selected]) {
      collectReferencedSchemas(schemas[name], selected)
    }
  }

  const missing = [...selected].filter((name) => !schemas[name])
  if (missing.length) {
    throw new Error(`OpenAPI contains unresolved analytics refs: ${missing.join(", ")}`)
  }

  const body = [...selected]
    .sort((left, right) => left.localeCompare(right))
    .map((name) => renderNamedSchema(name, schemas[name]))
    .join("\n\n")

  return [
    "// AUTO-GENERATED from backend OpenAPI by scripts/generate-analytics-types.mjs.",
    "// Do not edit this file by hand; run `npm run analytics:types:generate`.",
    "",
    body,
    "",
  ].join("\n")
}

function declarationsByName(source) {
  const firstExport = source.indexOf("export ")
  if (firstExport < 0) return new Map()
  return new Map(
    source
      .slice(firstExport)
      .split(/\n\n(?=export (?:interface|type) )/)
      .map((declaration) => {
        const match = declaration.match(/^export (?:interface|type) ([A-Za-z0-9_$]+)/)
        if (!match) throw new Error(`Could not parse generated declaration: ${declaration}`)
        return [match[1], declaration.replace(/\s+/g, "")]
      }),
  )
}

try {
  const generated = generate(loadOpenApi())
  if (checkOnly) {
    const current = readFileSync(outputPath, "utf8")
    const currentDeclarations = declarationsByName(current)
    const generatedDeclarations = declarationsByName(generated)
    const drift = [...new Set([...currentDeclarations.keys(), ...generatedDeclarations.keys()])]
      .filter((name) => currentDeclarations.get(name) !== generatedDeclarations.get(name))
    if (drift.length > 0) {
      console.error(
        `Analytics OpenAPI types are stale (${drift.join(", ")}). Run \`npm run analytics:types:generate\` and commit the result.`,
      )
      process.exit(1)
    }
    console.log("Analytics OpenAPI types are up to date.")
  } else {
    writeFileSync(outputPath, generated)
    console.log(`Generated ${outputPath}`)
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : error)
  process.exit(1)
}
