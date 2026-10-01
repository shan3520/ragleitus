import { parseSseChunk, readSse } from "../sse";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((c) => controller.enqueue(encoder.encode(c)));
      controller.close();
    },
  });
}

describe("parseSseChunk", () => {
  it("parses complete events and keeps the partial remainder", () => {
    const { events, rest } = parseSseChunk('event: token\ndata: {"text":"Hi"}\n\nevent: done\ndata: {"a"');
    expect(events).toEqual([{ event: "token", data: '{"text":"Hi"}' }]);
    expect(rest).toBe('event: done\ndata: {"a"');
  });

  it("handles CRLF, comments, default event names and multi-line data", () => {
    const { events } = parseSseChunk(": keep-alive\r\n\r\ndata: line1\r\ndata: line2\r\n\r\n");
    expect(events).toEqual([{ event: "message", data: "line1\nline2" }]);
  });
});

describe("readSse", () => {
  it("reassembles events split across network chunks", async () => {
    const events = [];
    for await (const e of readSse(streamOf("event: tok", 'en\ndata: {"text":"A"}\n', "\nevent: done\ndata: {}\n\n"))) {
      events.push(e);
    }
    expect(events).toEqual([
      { event: "token", data: '{"text":"A"}' },
      { event: "done", data: "{}" },
    ]);
  });

  it("emits a final event that lacks the trailing blank line", async () => {
    const events = [];
    for await (const e of readSse(streamOf('event: done\ndata: {"x":1}'))) events.push(e);
    expect(events).toEqual([{ event: "done", data: '{"x":1}' }]);
  });
});
