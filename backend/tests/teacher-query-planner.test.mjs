import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import register from "../skills/teacher-query-planner/extensions/teacher-query-planner.ts";

const endpoint = "https://teacher.example/api/v1/teacher-agent/mcp";
const query = { server: "innograd_teacher", tool: "query_papers", args: { spec: {} } };

async function fixture(testContext) {
	const directory = await mkdtemp(join(tmpdir(), "teacher-mcp-test-"));
	testContext.after(() => rm(directory, { recursive: true, force: true }));
	const adapter = join(directory, "adapter.mjs");
	await writeFile(adapter, `
		export function registerMcpServer({ pi, name, definition }) {
			const registration = { name, definition, disposed: false, async dispose() { this.disposed = true; } };
			pi.registrations.push(registration);
			return registration;
		}
	`);
	await writeFile(join(directory, "first.jsonl"), "first-token", { mode: 0o600 });
	await writeFile(join(directory, "second.jsonl"), "second-token", { mode: 0o600 });
	testContext.mock.property(process, "env", {
		...process.env,
		TEACHER_AGENT_GRANT_DIR: directory,
		TEACHER_AGENT_MCP_URL: endpoint,
		TEACHER_AGENT_MCP_ADAPTER: adapter,
	});
	const hooks = new Map();
	const pi = {
		registrations: [],
		setActiveTools(names) { this.active = names; },
		on(name, handler) { hooks.set(name, handler); },
		registerTool() { assert.fail("the adapter already registers mcp"); },
	};
	register(pi);
	const sessionContext = name => ({ sessionManager: { getSessionFile: () => join("/sessions", name) } });
	const start = async ctx => {
		const event = { systemPromptOptions: { selectedTools: ["other"] } };
		await hooks.get("before_agent_start")(event, ctx);
		assert.deepEqual(event.systemPromptOptions.selectedTools, pi.active);
	};
	const call = (ctx, input = query, toolName = "mcp") => hooks.get("tool_call")({ toolName, input }, ctx);
	return { pi, hooks, sessionContext, start, call };
}

test("teacher MCP registration uses the originating session's grant and disposes it", async testContext => {
	const { pi, hooks, sessionContext, start, call } = await fixture(testContext);
	const first = sessionContext("first.jsonl");
	const second = sessionContext("second.jsonl");
	await start(first);
	assert.deepEqual(pi.active, ["mcp"]);
	assert.deepEqual(pi.registrations[0].definition, {
		url: endpoint, httpTransport: "streamable-http", lifecycle: "lazy",
		headers: { Authorization: "Bearer first-token" },
	});
	assert.equal(pi.registrations[0].name, "innograd_teacher");
	assert.equal(call(first), undefined);
	assert.equal(call(second).block, true);
	await start(second);
	assert.equal(pi.registrations[0].disposed, true);
	assert.equal(pi.registrations[1].definition.headers.Authorization, "Bearer second-token");
	assert.equal(call(first).block, true);
	await hooks.get("agent_end")({}, second);
	assert.equal(pi.registrations[1].disposed, true);
	assert.equal(call(second).block, true);
	await start(sessionContext("ungranted.jsonl"));
	assert.deepEqual(pi.active, []);
	assert.equal(pi.registrations.length, 2);
});

test("teacher MCP tool hook denies foreign targets and lets the model repair inner arguments", async testContext => {
	const { pi, hooks, sessionContext, start, call } = await fixture(testContext);
	const session = sessionContext("first.jsonl");
	await start(session);
	for (const rejected of [
		{ ...query, server: "other" }, { ...query, tool: "other" },
		{ ...query, mode: "call" }, { server: query.server, tool: query.tool },
	]) {
		assert.equal(call(session, rejected).terminate, true);
	}
	assert.equal(call(session, query, "query_papers").terminate, true);
	assert.equal(call(session), undefined);
	for (const args of ["{}", '{"spec":{},"patch":{}}', '{"patch":true}', { spec: {}, extra: true }]) {
		const input = { ...query, args };
		assert.equal(call(session, input), undefined);
		assert.deepEqual(input.args, typeof args === "string" ? JSON.parse(args) : args);
	}
	for (const args of [null, [], '{"spec":{"page":NaN}}', '{"spec":']) {
		const result = call(session, { ...query, args });
		assert.equal(result.block, true);
		assert.notEqual(result.terminate, true);
		assert.match(result.reason, /^TEACHER_QUERY_ARGS_INVALID:/);
	}
	for (const key of ["spec", "patch"]) {
		const input = { ...query, args: JSON.stringify({ [key]: {} }) };
		assert.equal(call(session, input), undefined);
		assert.deepEqual(input.args, { [key]: {} });
	}
	await hooks.get("session_shutdown")({}, session);
	assert.equal(pi.registrations[0].disposed, true);
});
