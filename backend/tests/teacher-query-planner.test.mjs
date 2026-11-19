import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import register from "../skills/teacher-query-planner/extensions/teacher-query-planner.ts";

test("query_papers adds copyable references for every metric from its own run", async (context) => {
	const directory = await mkdtemp(join(tmpdir(), "teacher-grants-"));
	const callback = "https://teacher.example/tools/query-papers";
	const sessionFile = "test-session.jsonl";
	context.after(() => rm(directory, { recursive: true, force: true }));
	context.mock.property(process, "env", { ...process.env, TEACHER_AGENT_GRANT_DIR: directory, TEACHER_AGENT_CALLBACK_URL: callback });
	await writeFile(join(directory, sessionFile), "test-token", { mode: 0o600 });

	let tool;
	register({ registerTool(value) { tool = value; }, on() {} });
	const ctx = { sessionManager: { getSessionFile: () => join("/sessions", sessionFile) } };
	const requests = [{ spec: { domain: "paper" } }, { patch: { operation: "aggregate" } }];
	const runs = [
		{ query_run_id: "run-ALPHA_7", metrics: { paper_record_count: 0, paper_student_count: 0 } },
		{ query_run_id: "run-BETA_8", metrics: { paper_record_count: 9 } },
	];
	const rows = { breakdown: [], items: [{ student_name: "陈同学" }], portrait: null };
	let reply;
	const fetch = context.mock.method(globalThis, "fetch", async (url, options) => {
		assert.equal(url, callback);
		assert.equal(options.method, "POST");
		assert.equal(options.headers.Authorization, "Bearer test-token");
		return Response.json(reply);
	});
	for (const [index, run] of runs.entries()) {
		reply = { ...run, ...rows };
		const result = await tool.execute(`call-${index}`, requests[index], undefined, undefined, ctx);
		assert.deepEqual(JSON.parse(fetch.mock.calls[index].arguments[1].body), requests[index]);
		assert.deepEqual(JSON.parse(result.content[0].text), {
			...reply,
			metric_refs: index === 0
				? { paper_record_count: "[run-ALPHA_7:paper_record_count]", paper_student_count: "[run-ALPHA_7:paper_student_count]" }
				: { paper_record_count: "[run-BETA_8:paper_record_count]" },
		});
	}
	for (const invalid of [
		{ query_run_id: "bad:id", metrics: { count: 1 } },
		{ query_run_id: "run-ok", metrics: { "bad:key": 1 } },
		{ query_run_id: "run-ok", metrics: { count: "1" } },
	]) {
		reply = invalid;
		await assert.rejects(tool.execute("invalid", requests[0], undefined, undefined, ctx), /Paper query failed/);
	}
});
