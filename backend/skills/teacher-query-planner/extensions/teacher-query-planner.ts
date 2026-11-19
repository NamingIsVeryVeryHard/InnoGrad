import { readFile } from "node:fs/promises";
import { basename, isAbsolute, join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const proxyTool = "mcp";
const server = "innograd_teacher";
const domainTool = "query_papers";
const invalidArguments = "TEACHER_QUERY_ARGS_INVALID: args 必须是 JSON 对象或其 JSON 字符串，并且只含一个 spec 或 patch 对象。";

type Binding = {
	session: string;
	registration: { dispose(): Promise<void> };
};

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function queryArguments(value: unknown): Record<string, unknown> | undefined {
	let decoded = value;
	if (typeof value === "string") {
		try {
			decoded = JSON.parse(value);
		} catch {
			return;
		}
	}
	return isRecord(decoded) ? decoded : undefined;
}

function origin(context: ExtensionContext) {
	const file = context.sessionManager.getSessionFile();
	return file && basename(file);
}

export default function (pi: ExtensionAPI) {
	const directory = process.env.TEACHER_AGENT_GRANT_DIR;
	const endpoint = process.env.TEACHER_AGENT_MCP_URL;
	const adapterPath = process.env.TEACHER_AGENT_MCP_ADAPTER;
	let binding: Binding | undefined;

	async function dispose() {
		const previous = binding;
		binding = undefined;
		await previous?.registration.dispose();
	}

	pi.on("before_agent_start", async (event, context) => {
		pi.setActiveTools([]);
		event.systemPromptOptions.selectedTools = [];
		await dispose();
		const session = origin(context);
		if (!session) return;
		if (!directory || !isAbsolute(directory) || !endpoint || !adapterPath || !isAbsolute(adapterPath)) {
			throw new Error("Teacher MCP configuration unavailable.");
		}
		let token: string;
		try {
			token = await readFile(join(directory, session), "utf8");
		} catch (error) {
			if (isRecord(error) && error.code === "ENOENT") return;
			throw new Error("Teacher query authorization unavailable.");
		}
		if (!/^[A-Za-z0-9_-]+$/.test(token)) throw new Error("Teacher query authorization unavailable.");

		const adapter: unknown = await import(adapterPath);
		if (!isRecord(adapter) || typeof adapter.registerMcpServer !== "function") {
			throw new Error("Teacher MCP adapter unavailable.");
		}
		const registration: Binding["registration"] = adapter.registerMcpServer({
			pi,
			name: server,
			definition: {
				url: endpoint,
				httpTransport: "streamable-http",
				lifecycle: "lazy",
				headers: { Authorization: `Bearer ${token}` },
			},
		});
		binding = { session, registration };
		pi.setActiveTools([proxyTool]);
		event.systemPromptOptions.selectedTools = [proxyTool];
	});

	pi.on("tool_call", (event, context) => {
		const input: unknown = event.input;
		if (event.toolName === proxyTool && binding && binding.session === origin(context)
			&& isRecord(input) && Object.keys(input).sort().join(",") === "args,server,tool"
			&& input.server === server && input.tool === domainTool) {
			const args = queryArguments(input.args);
			if (!args) return { block: true, reason: invalidArguments };
			input.args = args;
			return;
		}
		return { block: true, terminate: true, reason: "Teacher tool unavailable." };
	});
	pi.on("agent_end", async (_event, context) => {
		if (binding?.session === origin(context)) await dispose();
	});
	pi.on("session_shutdown", dispose);
}
