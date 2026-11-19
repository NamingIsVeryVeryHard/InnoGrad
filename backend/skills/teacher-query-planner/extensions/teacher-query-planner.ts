import { readFile } from "node:fs/promises";
import { basename, isAbsolute, join } from "node:path";
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

const Filter = Type.Union([Type.Object({
	field: Type.Literal("degree"),
	operator: Type.Literal("eq"),
	value: Type.Union([Type.Literal("博士"), Type.Literal("硕士"), Type.Literal("未标注")]),
}), Type.Object({
	field: Type.Union([
		Type.Literal("publication_status"), Type.Literal("review_status"), Type.Literal("student_id"),
		Type.Literal("student_name"), Type.Literal("student_number"),
		Type.Literal("year"), Type.Literal("major"), Type.Literal("direction"), Type.Literal("stage"),
		Type.Literal("journal"), Type.Literal("title"), Type.Literal("has_doi"), Type.Literal("simulation"),
	]),
	operator: Type.String({ minLength: 1 }),
	value: Type.Union([
		Type.String(),
		Type.Boolean(),
		Type.Array(Type.String()),
	]),
}), Type.Object({
	field: Type.Literal("degree"),
	operator: Type.Literal("in"),
	value: Type.Array(Type.Union([Type.Literal("博士"), Type.Literal("硕士"), Type.Literal("未标注")])),
})]);

const DistinctSubject = Type.Union([Type.Literal("paper_record"), Type.Literal("student")]);

const QuerySpec = Type.Partial(Type.Object({
	domain: Type.Literal("paper"),
	operation: Type.Union([
		Type.Literal("aggregate"),
		Type.Literal("list"),
		Type.Literal("portrait"),
	]),
	basis: Type.Union([
		Type.Literal("current_effective_archives"),
		Type.Literal("submitted_latest"),
	]),
	time_range: Type.Optional(Type.Object({
		from: Type.String({ pattern: "^\\d{4}-\\d{2}-\\d{2}$" }),
		to: Type.String({ pattern: "^\\d{4}-\\d{2}-\\d{2}$" }),
		field: Type.String({ minLength: 1 }),
	})),
	filters: Type.Array(Filter),
	group_by: Type.Array(Type.String()),
	distinct_subject: DistinctSubject,
	include: Type.Array(Type.String()),
	sort: Type.Object({
		field: Type.String({ minLength: 1 }),
		direction: Type.Union([Type.Literal("asc"), Type.Literal("desc")]),
	}),
	page: Type.Integer({ minimum: 1 }),
	page_size: Type.Integer({ minimum: 1 }),
}, { additionalProperties: false }));

const QueryPatch = Type.Object({
	operation: Type.Optional(Type.Union([
		Type.Literal("aggregate"),
		Type.Literal("list"),
		Type.Literal("portrait"),
	])),
	basis: Type.Optional(Type.Union([
		Type.Literal("current_effective_archives"),
		Type.Literal("submitted_latest"),
	])),
	time_range: Type.Optional(Type.Object({
		from: Type.String({ pattern: "^\\d{4}-\\d{2}-\\d{2}$" }),
		to: Type.String({ pattern: "^\\d{4}-\\d{2}-\\d{2}$" }),
		field: Type.String({ minLength: 1 }),
	})),
	clear_time_range: Type.Optional(Type.Boolean()),
	set_filters: Type.Optional(Type.Array(Filter)),
	remove_filter_fields: Type.Optional(Type.Array(Type.String())),
	group_by: Type.Optional(Type.Array(Type.String())),
	distinct_subject: Type.Optional(DistinctSubject),
	include: Type.Optional(Type.Array(Type.String())),
	sort: Type.Optional(Type.Object({
		field: Type.String({ minLength: 1 }),
		direction: Type.Union([Type.Literal("asc"), Type.Literal("desc")]),
	})),
	page: Type.Optional(Type.Integer({ minimum: 1 })),
	page_size: Type.Optional(Type.Integer({ minimum: 1 })),
	reset_page: Type.Optional(Type.Boolean()),
}, { additionalProperties: false });

export default function (pi: ExtensionAPI) {
	const directory = process.env.TEACHER_AGENT_GRANT_DIR;
	const callback = process.env.TEACHER_AGENT_CALLBACK_URL;
	let calls = 0;
	pi.registerTool(defineTool({
		name: "query_papers",
		label: "Query papers",
		description: "Run a paper query. Send exactly one spec for a new query or one patch to refine the previous query.",
		parameters: Type.Object({
			spec: Type.Optional(QuerySpec),
			patch: Type.Optional(QueryPatch),
		}, { additionalProperties: false }),
		executionMode: "sequential",
		async execute(_id, params, signal, _update, ctx) {
			if (++calls > 5) throw new Error("Paper query limit reached.");
			if ((params.spec === undefined) === (params.patch === undefined)) {
				throw new Error("Supply exactly one spec or patch.");
			}
			const file = ctx.sessionManager.getSessionFile();
			if (!file || !directory || !isAbsolute(directory) || !callback) {
				throw new Error("Paper query authorization unavailable.");
			}
			try {
				const token = await readFile(join(directory, basename(file)), "utf8");
				const response = await fetch(callback, {
					method: "POST",
					redirect: "error",
					headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
					body: JSON.stringify(params),
					signal,
				});
				if (!response.ok) throw new Error();
				const { query_run_id, metrics, breakdown, items, portrait } = await response.json();
				if (typeof query_run_id !== "string" || !/^[A-Za-z0-9_-]+$/.test(query_run_id)
					|| !metrics || typeof metrics !== "object" || Array.isArray(metrics)
					|| !Object.entries(metrics).every(([key, value]) => /^[A-Za-z0-9_]+$/.test(key) && Number.isSafeInteger(value))) {
					throw new Error();
				}
				const metric_refs = Object.fromEntries(Object.keys(metrics).map(key => [key, `[${query_run_id}:${key}]`]));
				const result = { query_run_id, metrics, metric_refs, breakdown, items, portrait };
				return { content: [{ type: "text", text: JSON.stringify(result) }], details: {} };
			} catch {
				throw new Error("Paper query failed.");
			}
		},
	}));
	pi.on("session_start", () => pi.setActiveTools(["query_papers"]));
	pi.on("before_agent_start", (event) => {
		calls = 0;
		event.systemPromptOptions.selectedTools = ["query_papers"];
		pi.setActiveTools(["query_papers"]);
	});
	pi.on("tool_call", (event) => {
		if (event.toolName !== "query_papers") return { block: true, terminate: true, reason: "Only paper queries are enabled." };
	});
}
