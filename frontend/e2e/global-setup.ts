/** Fail fast with a useful message when the API behind the UI is not running. */
export default async function globalSetup() {
  const base = process.env.E2E_BASE_URL ?? "http://localhost:3000";
  let status = 0;
  try {
    status = (await fetch(`${base}/backend/health`)).status;
  } catch {
    /* reported below */
  }
  if (status !== 200) {
    throw new Error(
      `The ragleitus API is not reachable through ${base}/backend (status ${status || "none"}). ` +
        "Start it first (see Frontend > End-to-end tests in the README).",
    );
  }
}
