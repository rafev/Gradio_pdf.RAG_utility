/** Incremental parser for a text/event-stream body (works with fetch + POST, unlike EventSource). */
export interface SSEMessage {
  event: string;
  data: string;
}

export class SSEParser {
  private buffer = "";

  /** Feed a decoded chunk; returns the complete messages it finished. */
  feed(chunk: string): SSEMessage[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const out: SSEMessage[] = [];
    let sep: number;
    while ((sep = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, sep);
      this.buffer = this.buffer.slice(sep + 2);
      const msg = parseBlock(block);
      if (msg) out.push(msg);
    }
    return out;
  }

  /** Flush a trailing message that wasn't terminated by a blank line. */
  end(): SSEMessage[] {
    const rest = this.buffer.trim();
    this.buffer = "";
    const msg = rest ? parseBlock(rest) : null;
    return msg ? [msg] : [];
  }
}

function parseBlock(block: string): SSEMessage | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // comment / heartbeat
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}
