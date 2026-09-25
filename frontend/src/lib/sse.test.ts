import { describe, expect, it } from "vitest";
import { linkifyCitations, parseCitationHref, resolvePaperId } from "./citations";
import { SSEParser } from "./sse";

describe("SSEParser", () => {
  it("parses events split across chunks and skips heartbeats", () => {
    const p = new SSEParser();
    expect(p.feed('event: text\ndata: {"type":"te')).toEqual([]);
    const out = p.feed('xt","delta":"hi"}\n\n: ping\n\nevent: done\r\ndata: {"type":"done"}\r\n\r\n');
    expect(out).toEqual([
      { event: "text", data: '{"type":"text","delta":"hi"}' },
      { event: "done", data: '{"type":"done"}' },
    ]);
  });

  it("joins multi-line data and flushes a trailing message", () => {
    const p = new SSEParser();
    expect(p.feed("data: a\ndata: b\n\n")).toEqual([{ event: "message", data: "a\nb" }]);
    expect(p.feed("data: tail")).toEqual([]);
    expect(p.end()).toEqual([{ event: "message", data: "tail" }]);
  });
});

describe("citations", () => {
  it("linkifies [paper p.N] but leaves markdown links alone", () => {
    const md = "RAG works [rag-paper p.3] [dpr p. 12]; see [docs](https://x.y).";
    expect(linkifyCitations(md)).toBe(
      "RAG works [rag-paper p.3](#cite:rag-paper:3) [dpr p.12](#cite:dpr:12); see [docs](https://x.y).",
    );
  });

  it("parses cite hrefs", () => {
    expect(parseCitationHref("#cite:rag-paper:3")).toEqual({ paperId: "rag-paper", page: 3, partial: false });
    expect(parseCitationHref("https://example.com")).toBeNull();
  });

  it("handles abbreviated ids and resolves them by unique prefix", () => {
    const md = linkifyCitations("HbA1c rose [bouman... p.4] and [schnurbein… p.6].");
    expect(md).toBe("HbA1c rose [bouman… p.4](#cite:bouman~:4) and [schnurbein… p.6](#cite:schnurbein~:6).");
    expect(parseCitationHref("#cite:bouman~:4")).toEqual({ paperId: "bouman", page: 4, partial: true });
    const ids = ["bouman-social-jet-lag-and-changes", "schnurbein-sleep-and-glycemic", "roenneberg-2003", "roenneberg-how-can"];
    expect(resolvePaperId("bouman", ids)).toBe("bouman-social-jet-lag-and-changes");
    expect(resolvePaperId("roenneberg", ids)).toBeNull(); // ambiguous
    expect(resolvePaperId("roenneberg-2003", ids)).toBe("roenneberg-2003");
  });
});
