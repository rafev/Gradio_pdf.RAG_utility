/**
 * Citations look like [paper-id p.3]. We turn them into `#cite:` links the markdown renderer shows as chips.
 * Long ids sometimes come back abbreviated ("[bouman-social... p.4]"), so a trailing "..."/"…" marks a
 * prefix that resolvePaperId() expands against the corpus.
 */
const CITATION_RE = /\[([a-z0-9][a-z0-9-]*)(\.\.\.|…)? p\.\s?(\d+)\](?!\()/g;

export interface Citation {
  paperId: string;
  page: number;
  partial: boolean;
}

export function linkifyCitations(markdown: string): string {
  return markdown.replace(CITATION_RE, (_m, id: string, ellipsis: string | undefined, page: string) =>
    ellipsis ? `[${id}… p.${page}](#cite:${id}~:${page})` : `[${id} p.${page}](#cite:${id}:${page})`,
  );
}

export function parseCitationHref(href: string | undefined): Citation | null {
  if (!href?.startsWith("#cite:")) return null;
  const [, rawId, page] = href.split(":");
  const n = Number(page);
  if (!rawId || !Number.isFinite(n)) return null;
  const partial = rawId.endsWith("~");
  return { paperId: partial ? rawId.slice(0, -1) : rawId, page: n, partial };
}

/** Exact id if known; otherwise the single corpus paper id starting with the given prefix. */
export function resolvePaperId(id: string, paperIds: readonly string[]): string | null {
  if (paperIds.includes(id)) return id;
  const matches = paperIds.filter((p) => p.startsWith(id));
  return matches.length === 1 ? matches[0] : null;
}
