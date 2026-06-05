/**
 * Liczba → słownie (PL + EN) dla Generatora Umów B2B („stawka słownie").
 * Obsługuje 0–999 999 (z zapasem dla stawek godzinowych). Forma mianownikowa.
 */

const PL_ONES = [
  "zero",
  "jeden",
  "dwa",
  "trzy",
  "cztery",
  "pięć",
  "sześć",
  "siedem",
  "osiem",
  "dziewięć",
];
const PL_TEENS = [
  "dziesięć",
  "jedenaście",
  "dwanaście",
  "trzynaście",
  "czternaście",
  "piętnaście",
  "szesnaście",
  "siedemnaście",
  "osiemnaście",
  "dziewiętnaście",
];
const PL_TENS = [
  "",
  "",
  "dwadzieścia",
  "trzydzieści",
  "czterdzieści",
  "pięćdziesiąt",
  "sześćdziesiąt",
  "siedemdziesiąt",
  "osiemdziesiąt",
  "dziewięćdziesiąt",
];
const PL_HUNDREDS = [
  "",
  "sto",
  "dwieście",
  "trzysta",
  "czterysta",
  "pięćset",
  "sześćset",
  "siedemset",
  "osiemset",
  "dziewięćset",
];

function plUnder1000(n: number): string {
  const parts: string[] = [];
  const h = Math.floor(n / 100);
  const rest = n % 100;
  if (h) parts.push(PL_HUNDREDS[h]);
  if (rest >= 10 && rest < 20) {
    parts.push(PL_TEENS[rest - 10]);
  } else {
    const tn = Math.floor(rest / 10);
    const o = rest % 10;
    if (tn) parts.push(PL_TENS[tn]);
    if (o) parts.push(PL_ONES[o]);
  }
  return parts.join(" ");
}

function plThousands(n: number): string {
  // n = liczba tysięcy (1–999)
  if (n === 1) return "tysiąc";
  const last = n % 10;
  const last2 = n % 100;
  const word = last >= 2 && last <= 4 && !(last2 >= 12 && last2 <= 14)
    ? "tysiące"
    : "tysięcy";
  return `${plUnder1000(n)} ${word}`;
}

export function liczbaSlownie(num: number | null | undefined): string {
  if (num == null || Number.isNaN(num)) return "";
  const n = Math.floor(Math.abs(num));
  if (n === 0) return "zero";
  const th = Math.floor(n / 1000);
  const rest = n % 1000;
  const parts: string[] = [];
  if (th) parts.push(plThousands(th));
  if (rest) parts.push(plUnder1000(rest));
  return parts.join(" ").trim();
}

const EN_ONES = [
  "zero",
  "one",
  "two",
  "three",
  "four",
  "five",
  "six",
  "seven",
  "eight",
  "nine",
];
const EN_TEENS = [
  "ten",
  "eleven",
  "twelve",
  "thirteen",
  "fourteen",
  "fifteen",
  "sixteen",
  "seventeen",
  "eighteen",
  "nineteen",
];
const EN_TENS = [
  "",
  "",
  "twenty",
  "thirty",
  "forty",
  "fifty",
  "sixty",
  "seventy",
  "eighty",
  "ninety",
];

function enUnder1000(n: number): string {
  const parts: string[] = [];
  const h = Math.floor(n / 100);
  const rest = n % 100;
  if (h) parts.push(`${EN_ONES[h]} hundred`);
  if (rest >= 10 && rest < 20) {
    parts.push(EN_TEENS[rest - 10]);
  } else {
    const tn = Math.floor(rest / 10);
    const o = rest % 10;
    if (tn) parts.push(EN_TENS[tn]);
    if (o) parts.push(EN_ONES[o]);
  }
  return parts.join(" ");
}

export function numberToWordsEn(num: number | null | undefined): string {
  if (num == null || Number.isNaN(num)) return "";
  const n = Math.floor(Math.abs(num));
  if (n === 0) return "zero";
  const th = Math.floor(n / 1000);
  const rest = n % 1000;
  const parts: string[] = [];
  if (th) parts.push(`${enUnder1000(th)} thousand`);
  if (rest) parts.push(enUnder1000(rest));
  return parts.join(" ").trim();
}

/** Stawka słownie w danym języku ("pl" | "en"). */
export function rateInWords(amount: number | null | undefined, lang: string): string {
  return lang === "en" ? numberToWordsEn(amount) : liczbaSlownie(amount);
}
