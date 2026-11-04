"""Validate a complete material review inside the Agent session."""
from collections import defaultdict

from pydantic import ValidationError

from .adapters.innoagent import InnoAgentAdapter
from .agent import AgentResult, Evidence, _blocks_from_attachments, validate_evidence
from .material_rules import validate_rule_checks
from .review_errors import ReviewFailure

def _location(value):
    return value["file_id"], value.get("page_number"), value.get("paragraph_id")


def _without_whitespace(text):
    positions = [index for index, char in enumerate(text) if not char.isspace()]
    return "".join(text[index] for index in positions), positions


def align_evidence(checks, blocks):
    """Restore source text only for unambiguous same-file matches; record every change."""
    by_file = defaultdict(list)
    for index, block in enumerate(blocks):
        by_file[block["file_id"]].append((index, block))
    normalized = {}
    changes, issues = [], []
    for check in checks:
        for index, evidence in enumerate(check.evidence):
            supplied = evidence.model_dump()
            source = by_file[evidence.file_id]
            if any(_location(block) == _location(supplied) and evidence.quote in block["text"]
                   for _, block in source):
                continue
            candidates = {}
            needle, _ = _without_whitespace(evidence.quote)
            if needle:
                for block_index, block in source:
                    if block_index not in normalized:
                        normalized[block_index] = _without_whitespace(block["text"])
                    text, offsets = normalized[block_index]
                    start = text.find(needle)
                    while start >= 0:
                        candidate = {key: block[key] for key in ("file_id", "page_number", "paragraph_id")}
                        candidate["quote"] = block["text"][offsets[start]:offsets[start + len(needle) - 1] + 1]
                        candidates[(*_location(candidate), candidate["quote"])] = candidate
                        start = text.find(needle, start + 1)
            at_location = {key: value for key, value in candidates.items()
                           if _location(value) == _location(supplied)}
            if at_location:
                candidates = at_location
            if len(candidates) != 1:
                issues.append({
                    "rule_id": check.rule_id, "evidence_index": index,
                    "issue": "no_unique_same_file_source_match",
                    "file_id": evidence.file_id, "page_number": evidence.page_number,
                    "paragraph_id": evidence.paragraph_id,
                })
                continue
            corrected = next(iter(candidates.values()))
            try:
                check.evidence[index] = Evidence.model_validate(corrected)
            except ValidationError:
                issues.append({"rule_id": check.rule_id, "evidence_index": index,
                               "issue": "source_quote_exceeds_output_limit"})
                continue
            changes.append({"rule_id": check.rule_id, "supplied": supplied, "source": corrected})
    if issues:
        raise ReviewFailure("EVIDENCE_INVALID", {"validation_issues": issues})
    return changes


def review(config, payload, execution=None):
    validated = {}

    def validate_result(result):
        try:
            parsed = AgentResult.model_validate(result)
        except ValidationError as exc:
            raise ReviewFailure("OUTPUT_INVALID", {"validation_issues": [
                {"location": list(error["loc"]), "issue": error["type"]}
                for error in exc.errors(include_input=False, include_context=False, include_url=False)
            ]})
        try:
            blocks = _blocks_from_attachments(payload["attachments"])
            changes = align_evidence(parsed.checks, blocks)
            validate_evidence(parsed.checks, blocks)
            validate_rule_checks(parsed.checks, payload, [
                {**attachment, "id": attachment["file_id"]} for attachment in payload["attachments"]
            ])
        except ReviewFailure:
            raise
        except ValueError as exc:
            code = str(exc) if str(exc) in ("RULE_INCOMPLETE", "EVIDENCE_INVALID") else "EVIDENCE_INVALID"
            raise ReviewFailure(code, {"validation_issues": [{
                "issue": "check_rule_coverage_applicability_and_evidence_roles",
                "rules": [{"id": rule["id"], "evidence_roles": rule.get("evidence_roles", [])}
                          for rule in payload["requirements"]["review_rules"]],
            }]})
        validated.update(checks=[check.model_dump() for check in parsed.checks], changes=changes)
        return {"checks": validated["checks"]}

    metadata = {}
    try:
        result, metadata = InnoAgentAdapter(
            config, validate_result=validate_result, execution=execution,
        ).review(payload, AgentResult.model_json_schema())
        if not validated:
            validate_result(result)
    except ReviewFailure as exc:
        exc.metadata = {**metadata, **exc.metadata}
        raise
    metadata["evidence_alignments"] = validated["changes"]
    return validated["checks"], metadata
