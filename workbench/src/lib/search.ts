/**
 * S5c r2/r3 (user request), shared 2026-09-09 with the F2-B browse dialog:
 * the panel search matcher — a literal substring wins, then a subsequence
 * match (query chars in order, gaps allowed: "ndl" → needle); `/pattern/`
 * is an explicit case-insensitive regex, an INVALID pattern falls back to
 * the literal string (a broken regex must never blank a panel).
 *
 * Rank: 0 = no match, 1 = subsequence, 2 = substring/regex (higher first).
 */
export function fuzzyRank(query: string, hay: string): 0 | 1 | 2 {
  if (!query) return 2;
  if (hay.includes(query)) return 2;
  let i = 0;
  for (const ch of hay) {
    if (ch === query[i]) i += 1;
    if (i === query.length) return 1;
  }
  return 0;
}

/** Build the matcher for a raw search-box value; null = no filter. */
export function buildSearchMatcher(
  raw: string,
): ((hay: string) => 0 | 1 | 2) | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const m = /^\/(.+)\/$/.exec(trimmed);
  if (m) {
    try {
      const re = new RegExp(m[1], "i");
      return (hay: string) => (re.test(hay) ? 2 : 0);
    } catch {
      return (hay: string) => (hay.includes(trimmed.toLowerCase()) ? 2 : 0);
    }
  }
  const q = trimmed.toLowerCase();
  return (hay: string) => fuzzyRank(q, hay);
}
