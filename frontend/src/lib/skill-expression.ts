/**
 * Boolean skill-expression parser for the candidate "Umiejętności" filter.
 *
 * Recruiters type a small boolean expression into one box and we resolve it into
 * three skill-scoped buckets that the backend matches against the candidate's
 * skills / verified_tech / tags JSONB (NOT free CV text):
 *
 *   - `must`      — every term required (AND).
 *   - `anyGroups` — each inner array is one OR-group; groups AND together.
 *   - `none`      — none of these may be present (NOT).
 *
 * Grammar (case-insensitive operators, evaluated left-to-right):
 *   - whitespace / comma     → AND separator (new term)
 *   - `AND`                  → explicit AND separator (same as a space)
 *   - `OR`                   → the next term joins the PREVIOUS group into an OR
 *   - `NOT` / leading `-`    → exclude the next term
 *   - `"two words"`          → quoted multi-word skill kept as one term
 *
 * Examples (matching the agreed UX):
 *   Python AND React  → must: [Python, React]
 *   Python OR Java    → anyGroups: [[Python, Java]]
 *   Python NOT PHP    → must: [Python], none: [PHP]
 *   React Vue -PHP    → must: [React, Vue], none: [PHP]
 *   (A OR B) AND C    → must: [C], anyGroups: [[A, B]]   (parens are cosmetic)
 *
 * Left-to-right binding keeps the mental model simple — there is no operator
 * precedence beyond "OR chains the current group, everything else starts a new
 * one". This is intentionally less powerful than a full boolean algebra so the
 * result is always predictable from reading the text once.
 */

export interface SkillBuckets {
  /** AND terms — every one must be present. */
  must: string[];
  /** OR-groups — each group is OR'd internally; groups AND together. */
  anyGroups: string[][];
  /** NOT terms — none may be present. */
  none: string[];
}

export const EMPTY_SKILL_BUCKETS: SkillBuckets = {
  must: [],
  anyGroups: [],
  none: [],
};

const OPERATORS: ReadonlySet<string> = new Set(["and", "or", "not"]);

interface Token {
  /** Raw term text (quotes/`-` already stripped for terms). */
  text: string;
  /** True when the token came from a `"..."` literal — never an operator. */
  quoted: boolean;
  /** True when the term carried a leading `-` (shorthand NOT). */
  neg: boolean;
}

const isSeparator = (ch: string): boolean => /\s/.test(ch) || ch === ",";

/**
 * Hand-rolled tokenizer so `"Spring Boot"`, `-PHP`, `-"Spring Boot"` and bare
 * comma/space-separated words all tokenize correctly. A regex split can't keep
 * quoted runs together while also honoring a leading `-`.
 */
function tokenize(input: string): Token[] {
  const tokens: Token[] = [];
  const s = input;
  const n = s.length;
  let i = 0;
  while (i < n) {
    while (i < n && isSeparator(s[i])) i++;
    if (i >= n) break;

    let neg = false;
    if (s[i] === "-") {
      neg = true;
      i++;
    }

    if (i < n && s[i] === '"') {
      i++; // opening quote
      const start = i;
      while (i < n && s[i] !== '"') i++;
      const text = s.slice(start, i);
      if (i < n) i++; // closing quote
      tokens.push({ text, quoted: true, neg });
    } else {
      const start = i;
      while (i < n && !isSeparator(s[i])) i++;
      const text = s.slice(start, i);
      // A lone "-" (no term followed) is noise — drop it.
      if (text.length > 0) tokens.push({ text, quoted: false, neg });
    }
  }
  return tokens;
}

const cleanTerm = (raw: string): string => raw.trim().replace(/\s+/g, " ");

const pushUniqueCI = (list: string[], term: string): void => {
  const key = term.toLowerCase();
  if (!list.some((x) => x.toLowerCase() === key)) list.push(term);
};

const dedupeCI = (terms: string[]): string[] => {
  const out: string[] = [];
  for (const t of terms) pushUniqueCI(out, t);
  return out;
};

/**
 * Parse a boolean skill expression into `{ must, anyGroups, none }`.
 * Always returns a well-formed object — an empty / whitespace expression
 * yields empty buckets.
 */
export function parseSkillExpression(expr: string | null | undefined): SkillBuckets {
  const tokens = tokenize(expr ?? "");
  const groups: string[][] = []; // positive groups (OR within, AND across)
  const none: string[] = [];
  let orPending = false;
  let notPending = false;

  const pushPositive = (term: string): void => {
    if (orPending && groups.length > 0) {
      groups[groups.length - 1].push(term);
    } else {
      groups.push([term]);
    }
    orPending = false;
  };

  for (const tk of tokens) {
    const lower = tk.text.toLowerCase();
    if (!tk.quoted && OPERATORS.has(lower)) {
      if (lower === "or") orPending = true;
      else if (lower === "not") notPending = true;
      // "and" is just a separator → nothing pending.
      else orPending = false;
      continue;
    }

    const term = cleanTerm(tk.text);
    if (!term) continue;

    if (tk.neg || notPending) {
      notPending = false;
      orPending = false; // NOT breaks any pending OR chain
      pushUniqueCI(none, term);
    } else {
      pushPositive(term);
    }
  }

  const must: string[] = [];
  const anyGroups: string[][] = [];
  for (const group of groups) {
    const uniq = dedupeCI(group);
    if (uniq.length === 0) continue;
    if (uniq.length === 1) pushUniqueCI(must, uniq[0]);
    else anyGroups.push(uniq);
  }

  return { must, anyGroups, none };
}

/** A term needs quoting on re-serialization if it has spaces or looks like an operator. */
const quoteIfNeeded = (term: string): string => {
  const needs = /\s/.test(term) || OPERATORS.has(term.toLowerCase());
  return needs ? `"${term}"` : term;
};

/**
 * Render buckets back into a canonical expression string. Used to reconstruct
 * the box text from legacy `?skills=a,b` URLs and to rebuild the expression
 * after a chip is removed. Round-trips through `parseSkillExpression`.
 */
export function serializeSkillBuckets(buckets: SkillBuckets): string {
  const positive: string[] = [];
  for (const m of buckets.must) positive.push(quoteIfNeeded(m));
  for (const group of buckets.anyGroups) {
    positive.push(group.map(quoteIfNeeded).join(" OR "));
  }
  let out = positive.join(" AND ");
  for (const n of buckets.none) {
    const neg = `NOT ${quoteIfNeeded(n)}`;
    out = out ? `${out} ${neg}` : neg;
  }
  return out.trim();
}

/** True when the expression resolves to at least one skill constraint. */
export function hasSkillConstraints(buckets: SkillBuckets): boolean {
  return (
    buckets.must.length > 0 ||
    buckets.anyGroups.length > 0 ||
    buckets.none.length > 0
  );
}

/** Total number of distinct skill constraints (each OR-group counts once). */
export function countSkillConstraints(buckets: SkillBuckets): number {
  return buckets.must.length + buckets.anyGroups.length + buckets.none.length;
}
