"""Versioned, frozen review requirements shared by submission and execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2] / "agent-skills" / "material-review"
SKILL_VERSION = "material-review-5"
RULE_SET = "v2"


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def freeze_requirements(kind, requirements=None):
    result = deepcopy(requirements or {})
    if "review_rules" not in result:
        manifest = json.loads((SKILL_ROOT / "references" / "rules" / f"{kind}-{RULE_SET}.json").read_text())
        result["review_rules"] = manifest["rules"]
        result["rule_version"] = manifest["version"]
    result.setdefault("version", f"{kind}-{RULE_SET}")
    result["rules_hash"] = canonical_hash(result["review_rules"])
    return result


def required_roles(snapshot):
    if snapshot["kind"] == "annual":
        return {"annual_report"}
    roles = {"paper_fulltext"}
    state = snapshot["form"].get("publication_status")
    if state == "accepted":
        roles.add("acceptance_notice")
    elif state == "published":
        roles.add("publication_page")
    return roles


def not_applicable(rule, snapshot):
    condition = rule.get("not_applicable_when")
    return bool(
        condition == "no_references" and not snapshot.get("references")
        or condition == "submitted" and snapshot["form"].get("publication_status") == "submitted"
        or condition == "proofs_not_required"
        and not snapshot.get("requirements", {}).get("proof_attachments_required")
    )


def requires_correction(rule, conclusion):
    """Blocking rules return the material to the student; advisory findings only become hints.

    Rules frozen before levels existed default to blocking with correction on uncertainty.
    """
    if rule.get("level", "blocking") != "blocking":
        return False
    if conclusion == "non_compliant":
        return True
    return conclusion == "unable_to_determine" and rule.get("on_uncertain", "correction") == "correction"


def validate_rule_checks(checks, snapshot, files):
    rules = snapshot.get("requirements", {}).get("review_rules", [])
    if not rules or snapshot["requirements"].get("rules_hash") != canonical_hash(rules):
        raise ValueError("RULE_INCOMPLETE")
    by_id = {rule["id"]: rule for rule in rules}
    if len(checks) != len(by_id) or {c.rule_id for c in checks} != set(by_id):
        raise ValueError("RULE_INCOMPLETE")
    roles = {f["id"]: f["role"] for f in files}
    for check in checks:
        rule = by_id[check.rule_id]
        if check.conclusion == "not_applicable":
            if not not_applicable(rule, snapshot) or not check.explanation.strip():
                raise ValueError("RULE_INCOMPLETE")
        elif check.conclusion in ("compliant", "non_compliant"):
            accepted_roles = rule.get("evidence_roles", [])
            if not check.evidence or any(e.file_id not in roles for e in check.evidence):
                raise ValueError("EVIDENCE_INVALID")
            if accepted_roles and not any(roles[e.file_id] in accepted_roles for e in check.evidence):
                raise ValueError("EVIDENCE_INVALID")
