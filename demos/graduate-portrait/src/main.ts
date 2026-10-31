import { createPortraitServer } from './server.js';
import { loadProjectEnv } from '../skill-bridge.mjs';
import { parseStartupOptions } from './startup.js';

const { port, timeoutMs } = parseStartupOptions(await loadProjectEnv());
const app = await createPortraitServer({ timeoutMs });
for (const event of ['SIGINT', 'SIGTERM'] as const) {
  process.once(event, () => { void app.close().then(() => process.exit(0)); });
}
await app.listen({ host: '127.0.0.1', port });
console.log(`画像 Skill Demo: http://127.0.0.1:${port}/docs/`);
