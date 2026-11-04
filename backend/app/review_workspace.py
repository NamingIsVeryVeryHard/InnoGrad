"""Complete input files and verified read coverage for one Agent workspace."""
import hashlib
import json
import posixpath

from .review_errors import ReviewFailure


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


class ReviewWorkspace:
    def __init__(self, package, output_schema):
        self.files = {"review/package.json": _json(package)}
        attachments, sources = [], []
        for index, attachment in enumerate(package.get("attachments", []), 1):
            path = f"review/sources/{index:03d}.txt"
            blocks = []
            for block in attachment["content"]:
                location = {key: block.get(key) for key in ("page_number", "paragraph_id")}
                location["file_id"] = attachment["file_id"]
                blocks.append("=== SOURCE BLOCK " + json.dumps(location, ensure_ascii=False) + " ===\n" + block["text"])
            self.files[path] = "\n\n".join(blocks)
            attachments.append({
                **{key: value for key, value in attachment.items() if key != "content"},
                "source_path": path, "block_count": len(blocks),
            })
            sources.append({
                "path": path, "file_id": attachment["file_id"], "block_count": len(blocks),
                "line_count": len(self.files[path].split("\n")),
                "sha256": hashlib.sha256(self.files[path].encode()).hexdigest(),
            })
        self.files["review/manifest.json"] = _json({
            "review_context": {**{key: value for key, value in package.items() if key != "attachments"},
                               "attachments": attachments},
            "source_files": sources,
        })
        self.files["review/output-schema.json"] = _json(output_schema)
        self.lines = {path: text.split("\n") for path, text in self.files.items()}
        self.seen = {path: set() for path in self.files}
        self.required = ["review/manifest.json", *(source["path"] for source in sources)]
        self.calls, self.trace = {}, []
        self.source_blocks = sum(source["block_count"] for source in sources)

    def record(self, event, workspace_id):
        """Count only successful native read results matching the uploaded source."""
        call_id = event.get("toolCallId")
        if event.get("type") == "tool_start":
            self.calls[call_id] = event
            return
        if event.get("type") != "tool_end":
            return
        start = self.calls.pop(call_id, {})
        if start.get("toolName") != "read" or event.get("toolName") != "read":
            self.trace.append({"tool": event.get("toolName"), "is_error": bool(event.get("isError"))})
            return
        args, result = start.get("args"), event.get("result")
        args = args if isinstance(args, dict) else {}
        result = result if isinstance(result, dict) else {}
        raw_path = args.get("path")
        path = posixpath.normpath(raw_path) if isinstance(raw_path, str) else "<invalid path>"
        if path.startswith("/") and f"/{workspace_id}/" in path:
            path = path.split(f"/{workspace_id}/", 1)[1]
        offset, limit = args.get("offset", 1), args.get("limit")
        count = 0
        if (path in self.lines and not event.get("isError") and isinstance(result, dict)
                and type(offset) is int and offset >= 1
                and (limit is None or type(limit) is int and limit > 0)):
            lines = self.lines[path]
            truncation = (result.get("details") or {}).get("truncation") or {}
            if not truncation.get("firstLineExceedsLimit") and offset <= len(lines):
                count = min(limit or len(lines), len(lines) - offset + 1)
                if truncation.get("truncated"):
                    count = truncation.get("outputLines", 0)
                text = "\n".join(part.get("text", "") for part in result.get("content", [])
                                 if part.get("type") == "text")
                if type(count) is not int or count <= 0 or count > len(lines) - offset + 1:
                    count = 0
                elif not text.startswith("\n".join(lines[offset - 1:offset - 1 + count])):
                    count = 0
                if count:
                    self.seen[path].update(range(offset, offset + count))
        self.trace.append({
            "tool": "read", "path": path, "offset": offset, "lines_verified": count,
            "is_error": bool(event.get("isError")),
        })

    def coverage(self):
        def complete(path):
            return len(self.seen[path]) == len(self.lines[path])

        canonical_complete = complete("review/package.json")
        return {
            "complete": canonical_complete or all(complete(path) for path in self.required),
            "source_blocks": self.source_blocks,
            "canonical_package_read": canonical_complete,
            "files": [
                {"path": path, "lines": len(self.lines[path]), "read_lines": len(self.seen[path])}
                for path in self.required
            ],
        }

    def validate_coverage(self):
        if self.coverage()["complete"]:
            return
        issues = []
        for path in self.required:
            missing = sorted(set(range(1, len(self.lines[path]) + 1)) - self.seen[path])
            ranges = []
            for line in missing:
                if ranges and line == ranges[-1][1] + 1:
                    ranges[-1][1] = line
                else:
                    ranges.append([line, line])
            if ranges:
                issues.append({"issue": "source_not_fully_read", "path": path, "unread_line_ranges": ranges})
        raise ReviewFailure("COVERAGE_INCOMPLETE", {"validation_issues": issues})
