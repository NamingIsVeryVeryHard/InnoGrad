export function parseStartupOptions(env: Record<string, string | undefined>) {
  const port = Number(env.PORTRAIT_PORT ?? 3001);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('PORTRAIT_PORT must be an integer between 1 and 65535');
  }
  const timeoutMs = Number(env.PORTRAIT_JOB_TIMEOUT_MS ?? 300_000);
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 900_000) {
    throw new Error('PORTRAIT_JOB_TIMEOUT_MS must be an integer between 1000 and 900000');
  }
  return { port, timeoutMs };
}
