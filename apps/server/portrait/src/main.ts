import { createPortraitServer } from './server.js';

const port = Number(process.env.PORTRAIT_PORT ?? 3001);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORTRAIT_PORT must be an integer between 1 and 65535');
const app = await createPortraitServer();
for (const event of ['SIGINT', 'SIGTERM'] as const) {
  process.once(event, () => { void app.close().then(() => process.exit(0)); });
}
await app.listen({ host: '127.0.0.1', port });
console.log(`画像 API: http://127.0.0.1:${port}/docs`);
