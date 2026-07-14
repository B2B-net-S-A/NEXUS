#!/usr/bin/env node

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs"
import { dirname, extname, relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const FRONTEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..")

// Token-first boundary for the design system and every migrated candidate
// presentation surface. Keeping the profile/list monoliths here prevents raw
// palette utilities from creeping back while they are gradually extracted.
const TARGETS = [
  "src/components/ds",
  "src/components/candidates/preview",
  "src/app/preview/candidates",
  "src/app/preview/candidate-profile",
  "src/components/SuggestedJobsWidget.tsx",
  "src/components/v2/pages/CandidatesListV2.tsx",
  "src/components/v2/pages/CandidatesTiles.tsx",
  "src/components/v2/pages/CandidateDetailV2.tsx",
  "src/components/v2/pages/CandidateQuickView.tsx",
  "src/components/v2/pages/CandidateProfileHeader.tsx",
  "src/components/v2/CandidateNav.tsx",
  "src/components/v2/candidates/CandidateTabsRail.tsx",
]

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx"])
const PALETTE =
  /\b(?:bg|text|border(?:-[trblxy])?|ring(?:-offset)?|outline|divide(?:-[xy])?|from|via|to|fill|stroke)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}(?:\/\d{1,3})?\b/g
const RAW_HEX = /#[0-9a-f]{3,8}\b/gi
const RAW_WHITE_BLACK = /\b(?:bg|text|border(?:-[trblxy])?|fill|stroke)-(?:white|black)(?:\/\d{1,3})?\b/g

function collect(path) {
  if (!existsSync(path)) return []
  if (statSync(path).isFile()) return SOURCE_EXTENSIONS.has(extname(path)) ? [path] : []
  return readdirSync(path, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name.startsWith(".") || entry.name === "__tests__") return []
    return collect(resolve(path, entry.name))
  })
}

const failures = []
const files = TARGETS.flatMap((target) => collect(resolve(FRONTEND_ROOT, target)))

for (const file of files) {
  const source = readFileSync(file, "utf8")
  const lines = source.split(/\r?\n/)

  for (const [index, line] of lines.entries()) {
    const matches = [
      ...line.matchAll(PALETTE),
      ...line.matchAll(RAW_HEX),
      ...line.matchAll(RAW_WHITE_BLACK),
    ]
    for (const match of matches) {
      failures.push({
        file: relative(FRONTEND_ROOT, file),
        line: index + 1,
        token: match[0],
      })
    }
  }
}

if (failures.length > 0) {
  console.error("Token guard: found raw palette usage in DS/candidate presentation surfaces:\n")
  for (const failure of failures) {
    console.error(`  ${failure.file}:${failure.line}  ${failure.token}`)
  }
  console.error("\nUse semantic utilities such as bg-card, text-muted-foreground, bg-success-muted or text-brand-linkedin.")
  process.exit(1)
}

console.log(`Token guard passed (${files.length} files checked).`)
