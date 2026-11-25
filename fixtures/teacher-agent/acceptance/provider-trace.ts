import { appendFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function register(pi: ExtensionAPI) {
  pi.on("before_provider_request", ({ payload }) => {
    const path = process.env.ACCEPTANCE_TRACE_PATH;
    if (!path) return;
    const request = payload && typeof payload === "object" ? payload : {};
    const tools = "tools" in request && Array.isArray(request.tools) ? request.tools : [];
    const messages = "messages" in request && Array.isArray(request.messages) ? request.messages : [];
    const fields = ["model", "input", "messages", "tools", "tool_choice", "stream",
      "temperature", "max_tokens", "max_output_tokens", "reasoning"];
    const row = {
      event: "provider_request",
      params_type: Array.isArray(payload) ? "array" : typeof payload,
      fields: fields.filter((key) => Object.hasOwn(request, key)),
      other_fields: Object.keys(request).filter((key) => !fields.includes(key)).length,
      tools_type: "tools" in request ? (Array.isArray(request.tools) ? "array" : typeof request.tools) : "undefined",
      tool_count: tools.length,
      exposes_mcp: tools.some((tool) => (tool?.function?.name ?? tool?.name) === "mcp"),
      message_count: messages.length,
      has_system: messages.some((message) => message?.role === "system"),
    };
    appendFileSync(path, `${JSON.stringify(row)}\n`, { mode: 0o600 });
  });
}
