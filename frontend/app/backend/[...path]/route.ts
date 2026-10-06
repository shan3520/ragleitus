/**
 * Forwards /backend/* to the FastAPI server.
 *
 * The browser only ever talks to this origin, so no CORS configuration is
 * needed and the API address is read at runtime from API_URL (not baked into
 * the client bundle at build time). Request and response bodies are streamed
 * through untouched, which keeps uploads and server-sent events working.
 */

const API_URL = () => (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");

// Hop-by-hop headers must not be forwarded (RFC 9110 §7.6.1), and Host must
// describe the upstream, not this server.
const DROP_REQUEST_HEADERS = ["host", "connection", "keep-alive", "transfer-encoding", "upgrade", "content-length"];
const DROP_RESPONSE_HEADERS = ["connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length"];

async function forward(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const incoming = new URL(request.url);
  const target = `${API_URL()}/${path.map(encodeURIComponent).join("/")}${incoming.search}`;

  const headers = new Headers(request.headers);
  DROP_REQUEST_HEADERS.forEach((h) => headers.delete(h));

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Required by Node's fetch when the body is a stream.
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
      cache: "no-store",
      signal: request.signal,
    } as RequestInit);
  } catch {
    return Response.json({ detail: "The ragleitus API is not reachable." }, { status: 502 });
  }

  const responseHeaders = new Headers(upstream.headers);
  DROP_RESPONSE_HEADERS.forEach((h) => responseHeaders.delete(h));
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: responseHeaders });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
