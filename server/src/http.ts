export function json(body: unknown, status = 200, headers: HeadersInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      ...headers,
    },
  });
}

export function notFound(): Response {
  return json({ error: "Not found" }, 404);
}

export function methodNotAllowed(): Response {
  return json({ error: "Method not allowed" }, 405);
}

export function badRequest(msg: string): Response {
  return json({ error: msg }, 400);
}

export function unauthorized(msg = "Unauthorized"): Response {
  return json({ error: msg }, 401);
}

export async function readJson<T = any>(req: Request): Promise<T> {
  try {
    return (await req.json()) as T;
  } catch {
    throw new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
}

export function now(): number {
  return Math.floor(Date.now() / 1000);
}
