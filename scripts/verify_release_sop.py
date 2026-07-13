from __future__ import annotations

from collections.abc import Callable
import json
import re
import sys
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "docs/sop/README.md",
    "docs/sop/01-demand-intake-and-priority.md",
    "docs/sop/02-production-branch-versioning.md",
    "docs/sop/03-change-analysis-and-tdd.md",
    "docs/sop/04-subagent-review-template.md",
    "docs/sop/05-release-package-and-hash.md",
    "docs/sop/06-production-deploy-runbook.md",
    "docs/sop/07-rollback-and-incident-review.md",
    "docs/sop/08-business-acceptance-templates.md",
    "ops/releases/README.md",
    "ops/releases/V3.0.79.md",
    "ops/releases/V3.0.80.md",
    "ops/releases/V3.0.78.md",
    "ops/releases/V3.0.77.md",
    "ops/releases/V3.0.76.md",
    "ops/releases/V3.0.75.md",
    "ops/releases/V3.0.74.md",
    "ops/releases/V3.0.73.md",
    "ops/releases/V3.0.72.md",
    "ops/releases/V3.0.71.md",
    "ops/releases/V3.0.70.md",
    "ops/releases/V3.0.69.md",
    "ops/releases/V3.0.68.md",
    "ops/releases/V3.0.67.md",
    "ops/releases/V3.0.66.md",
    "ops/releases/V3.0.65.md",
    "ops/releases/V3.0.64.md",
    "ops/releases/V3.0.63.md",
    "ops/releases/V3.0.62.md",
    "ops/releases/V3.0.61.md",
    "ops/releases/V3.0.60.md",
    "ops/releases/V3.0.59.md",
    "ops/releases/V3.0.58.md",
    "ops/releases/V3.0.56.md",
    "ops/releases/V3.0.55.md",
    "ops/releases/V3.0.54.md",
    "ops/releases/V3.0.53.md",
    "ops/releases/V3.0.52.md",
    "ops/releases/V3.0.51.md",
    "ops/releases/V3.0.50.md",
    "ops/releases/V3.0.49.md",
    "ops/releases/V3.0.48.md",
    "ops/releases/V3.0.47.md",
    "ops/releases/V3.0.46.md",
    "ops/releases/V3.0.45.md",
    "ops/releases/V3.0.44.md",
    "ops/releases/V3.0.42.md",
    "ops/releases/V3.0.41.md",
    "ops/releases/V3.0.40.md",
    "ops/releases/V3.0.39.md",
    "ops/releases/V3.0.38.md",
    "ops/releases/V3.0.37.md",
    "ops/incidents/P0-template.md",
    "scripts/production_backup.sh",
    "scripts/cleanup_old_releases.sh",
    "scripts/production_health_check.py",
    "scripts/verify_release_retention_policy.py",
    "scripts/verify_project_board_data_center_photos.js",
    "scripts/verify_project_board_unmatched_review.js",
    "scripts/verify_dialog_information_integration.js",
    "v2-web/public/version.json",
]

RELEASE_TABLE_ROW_PATTERN = re.compile(
    r"^\|\s*(?P<evidence>[^|]+?)\s*\|\s*(?P<value>[^|]*)\s*\|\s*$", re.MULTILINE
)
DEPLOYED_BASELINE_MARKER = "当前已部署生产版本"
RELEASE_CANDIDATE_MARKER = "当前发布候选版本"
ENGLISH_DEPLOYED_BASELINE_MARKER = "Deployed production baseline"
ENGLISH_RELEASE_CANDIDATE_MARKER = "Release candidate"
STATUS_FIELD_LABELS = {
    "Status": "Status",
    "Deployment state": "Deployment state",
    "Deployment status": "Deployment status",
    "Release status": "Release status",
    "Release": "Release",
    "Deployment": "Deployment",
    "状态": "状态",
    "部署状态": "部署状态",
    "发布状态": "发布状态",
    "上线状态": "上线状态",
    "部署": "部署",
    "发布": "发布",
    "上线": "上线",
}
EVIDENCE_FIELD_LABELS = {
    "SHA256": "SHA256",
    "Backup directory": "Backup directory",
    "Release directory": "Release directory",
    "Public health check": "Public health check",
}
VERSION_TOKEN_PATTERN = re.compile(r"\bV\d+\.\d+\.\d+\b", re.IGNORECASE)
SEMANTIC_VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
MANIFEST_VERSION_LINE_PATTERN = re.compile(r"^- Version:\s*(?P<version>.*?)\s*$", re.MULTILINE)
DEPLOYMENT_CLAIM_PATTERN = re.compile(
    r"\b(?:deployed|shipped|released)\b"
    r"|\b(?:is|are|was|were|went|has\s+been|have\s+been)\s+(?:now\s+)?live(?:\s+(?:in|on))?\s+production\b"
    r"|\b(?:has|have)\s+gone\s+live(?:\s+(?:in|on))?\s+production\b"
    r"|已部署|已发布|已上线|(?:生产(?:环境)?\s*)?(?:部署|发布|上线)已完成"
    r"|已(?:在)?生产(?:环境)?(?:正式)?(?:部署|发布|上线|生效)"
    r"|已完成(?:生产(?:环境)?)?(?:部署|发布|上线)"
    r"|现已(?:在)?生产(?:环境)?(?:正式)?生效",
    re.IGNORECASE,
)
NEGATED_ENGLISH_CLAIM_PATTERN = re.compile(
    r"\b(?:not|never)\s+(?:(?:yet|currently|ever|actually|successfully|fully)\s+)*"
    r"(?:(?:been|be)\s+)?(?:deployed|shipped|released)\b"
    r"|\b(?:not|never)\s+(?:(?:yet|currently|ever|actually|successfully|fully)\s+)*"
    r"(?:go|gone|be)?\s*live(?:\s+(?:in|on))?\s+production\b",
    re.IGNORECASE,
)
NEGATED_CHINESE_CLAIM_PATTERN = re.compile(
    r"(?:未|尚未)(?:在)?(?:生产(?:环境)?)?(?:正式)?(?:部署|发布|上线|生效)"
    r"|(?:未|尚未)完成(?:生产(?:环境)?)?(?:部署|发布|上线)"
)
CONDITIONAL_ENGLISH_CLAIM_PATTERN = re.compile(r"\b(?:can|could|may|might|if|unless)\b", re.IGNORECASE)
CONDITIONAL_CHINESE_CLAIM_PATTERN = re.compile(
    r"(?:可以|可能|或许|也许|若|如果|假如|倘若|除非|否则|仅当|只要|待)"
    r"|可(?=[^,，;；。.!?！？\n]{0,24}(?:部署|发布|上线|生效))"
)
PENDING_STATUS_PATTERN = re.compile(r"\bpending\b|待(?:部署|发布|上线|验证)|未(?:部署|发布|上线)", re.IGNORECASE)
FUTURE_DEPLOYMENT_PATTERN = re.compile(
    r"\b(?:will|would|shall|going\s+to|to\s+be|scheduled\s+to|planned\s+to)\s+"
    r"(?:(?:be\s+)?(?:deployed|shipped|released)|go\s+live(?:\s+(?:in|on))?\s+production)\b"
    r"|\b(?:before|after|until|once)\b[^,;.!?\n]{0,120}\b(?:deployed|shipped|released)\b"
    r"|(?:将|计划|拟)(?:于[^,，;；。.!?！？\n]{0,20})?(?:在生产(?:环境)?)?(?:部署|发布|上线|生效)",
    re.IGNORECASE,
)
CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"([,，;；。.!?！？\n]+|\b(?:and|but|however|then|while|yet)\b|(?:并且|并于|并|但是|然而|但|却|然后)|于(?=(?:今日|现已|生产)))",
    re.IGNORECASE,
)
CLAUSE_SCOPE_RESET_PATTERN = re.compile(r"[。.!?！？\n]|\b(?:but|however|yet)\b|(?:但是|然而|但|却)", re.IGNORECASE)
RELEASE_RECORD_VERSION_PATTERN = re.compile(r"^#\s*(?P<version>V\d+\.\d+\.\d+)\b", re.MULTILINE)
PLACEHOLDER_PATTERN = re.compile(r"\b(?:tbd|todo|pending|n/?a|unknown)\b|待补充|待验证|(?:^|\s)-(?:$|\s)", re.IGNORECASE)
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
BACKUP_DIRECTORY_PATTERN = re.compile(r"/opt/module-manager-v2/backups/[A-Za-z0-9._-]+")
RELEASE_DIRECTORY_PATTERN = re.compile(r"/opt/module-manager-v2/releases/[A-Za-z0-9._-]+")
PUBLIC_HEALTH_URL_PATTERN = re.compile(r"https://(?:www\.)?sgcc\.online/health(?:[/?#\s]|$)", re.IGNORECASE)
SUCCESS_STATUS_PATTERN = re.compile(r"\b(?:passed|pass|success|successful|healthy|ok)\b|通过|成功", re.IGNORECASE)


def fail(message: str) -> None:
    raise AssertionError(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def normalize_claim_text(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(
        r"\b(is|are|was|were|has|have|had|do|does|did|can|could|would|should|must)n't\b",
        r"\1 not",
        text,
    )
    return text.replace("won't", "will not").replace("cannot", "can not")


def is_label_character(char: str) -> bool:
    return char.isalnum() or "\u3400" <= char <= "\u9fff"


def strip_optional_markdown_bullet(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lstrip()
    if normalized[:1] in {"-", "*", "+"}:
        return normalized[1:].lstrip()
    return normalized


def strip_decorative_prefix(value: str) -> str:
    while value and not is_label_character(value[0]) and value[0] not in {"/", "-"}:
        value = value[1:]
    return value


def compact_label(value: str) -> str:
    return "".join(char.casefold() for char in unicodedata.normalize("NFKC", value) if is_label_character(char))


def label_suffix(value: str, label: str) -> str | None:
    text = strip_decorative_prefix(strip_optional_markdown_bullet(value))
    expected = compact_label(label)
    index = 0
    for char in expected:
        while index < len(text) and not is_label_character(text[index]):
            index += 1
        if index >= len(text) or text[index].casefold() != char:
            return None
        index += 1
    return text[index:]


def parse_known_label_value(value: str, labels: dict[str, str]) -> tuple[str, str] | None:
    for label in sorted(labels, key=lambda item: len(compact_label(item)), reverse=True):
        suffix = label_suffix(value, label)
        if suffix is None or not suffix or is_label_character(suffix[0]):
            continue
        parsed_value = strip_decorative_prefix(suffix).strip()
        if parsed_value:
            return labels[label], parsed_value
    return None


def parse_known_label(value: str, labels: dict[str, str]) -> str | None:
    for label in sorted(labels, key=lambda item: len(compact_label(item)), reverse=True):
        suffix = label_suffix(value, label)
        if suffix is not None and not strip_decorative_prefix(suffix).strip():
            return labels[label]
    return None


def parse_marker_version(value: str) -> str | None:
    match = re.match(r"(?P<version>V\d+\.\d+\.\d+)(?P<trailing>.*)$", unicodedata.normalize("NFKC", value))
    if match is None or strip_decorative_prefix(match.group("trailing")).strip():
        return None
    return match.group("version")


def parse_agents_marker(agents: str, marker: str, marker_name: str) -> str:
    matches = []
    for line in agents.splitlines():
        parsed = parse_known_label_value(line, {marker: marker})
        if parsed is None:
            continue
        _, value = parsed
        version = parse_marker_version(value)
        if version is not None:
            matches.append(version)
    if len(matches) != 1:
        fail(f"AGENTS.md must define exactly one {marker_name} marker")
    return matches[0]


def deployed_production_baseline(agents: str) -> str:
    english = parse_agents_marker(
        agents,
        ENGLISH_DEPLOYED_BASELINE_MARKER,
        "English deployed production baseline",
    )
    chinese = parse_agents_marker(agents, DEPLOYED_BASELINE_MARKER, "deployed production baseline")
    if english != chinese:
        fail("AGENTS.md English and Chinese deployed production baseline markers must agree")
    return chinese


def release_candidate(agents: str) -> str:
    english = parse_agents_marker(
        agents,
        ENGLISH_RELEASE_CANDIDATE_MARKER,
        "English release candidate",
    )
    chinese = parse_agents_marker(agents, RELEASE_CANDIDATE_MARKER, "release candidate")
    if english != chinese:
        fail("AGENTS.md English and Chinese release candidate markers must agree")
    return chinese


def release_record_status(record: str) -> str:
    claims = []
    all_labels = {**STATUS_FIELD_LABELS, **EVIDENCE_FIELD_LABELS}
    for line in record.splitlines():
        if line.lstrip().startswith("|"):
            continue
        parsed = parse_known_label_value(line, all_labels)
        if parsed is not None and parsed[0] in STATUS_FIELD_LABELS.values():
            claims.append(parsed[1])
    for match in RELEASE_TABLE_ROW_PATTERN.finditer(record):
        field = parse_known_label(match.group("evidence"), STATUS_FIELD_LABELS)
        if field is not None:
            claims.append(match.group("value").strip())
    if not claims:
        fail("release record must include a status-like field")
    if len(claims) != 1:
        fail("release record must not contain multiple status-like claims")
    return claims[0]


def release_record_evidence(record: str) -> dict[str, list[str]]:
    evidence = {field: [] for field in EVIDENCE_FIELD_LABELS.values()}
    for match in RELEASE_TABLE_ROW_PATTERN.finditer(record):
        field = parse_known_label(match.group("evidence"), EVIDENCE_FIELD_LABELS)
        if field is not None:
            evidence[field].append(match.group("value").strip())
    all_labels = {**STATUS_FIELD_LABELS, **EVIDENCE_FIELD_LABELS}
    for line in record.splitlines():
        if line.lstrip().startswith("|"):
            continue
        parsed = parse_known_label_value(line, all_labels)
        if parsed is not None and parsed[0] in evidence:
            evidence[parsed[0]].append(parsed[1])
    return evidence


def is_placeholder(value: str) -> bool:
    return PLACEHOLDER_PATTERN.search(value) is not None


def clause_has_conditional_language(clause: str) -> bool:
    normalized = normalize_claim_text(clause)
    return bool(
        CONDITIONAL_ENGLISH_CLAIM_PATTERN.search(normalized)
        or CONDITIONAL_CHINESE_CLAIM_PATTERN.search(normalized)
    )


def semantic_claim_clauses(value: str) -> list[tuple[str, bool]]:
    protected = VERSION_TOKEN_PATTERN.sub(lambda match: match.group(0).replace(".", "\ue000"), normalize_claim_text(value))
    parts = CLAUSE_BOUNDARY_PATTERN.split(protected)
    clauses: list[tuple[str, bool]] = []
    conditional_scope = False
    for index in range(0, len(parts), 2):
        clause = parts[index].replace("\ue000", ".").strip()
        clause_is_conditional = clause_has_conditional_language(clause)
        if clause:
            clauses.append((clause, conditional_scope or clause_is_conditional))
        if clause_is_conditional:
            conditional_scope = True
        boundary = parts[index + 1] if index + 1 < len(parts) else ""
        if CLAUSE_SCOPE_RESET_PATTERN.search(boundary):
            conditional_scope = False
    return clauses


def claim_clauses(value: str) -> list[str]:
    return [clause for clause, _ in semantic_claim_clauses(value)]


def clause_has_affirmative_deployment_claim(clause: str) -> bool:
    normalized = normalize_claim_text(clause)
    if not DEPLOYMENT_CLAIM_PATTERN.search(normalized):
        return False
    if clause_has_conditional_language(normalized):
        return False
    if NEGATED_ENGLISH_CLAIM_PATTERN.search(normalized) or NEGATED_CHINESE_CLAIM_PATTERN.search(normalized):
        return False
    if FUTURE_DEPLOYMENT_PATTERN.search(normalized):
        return False
    return True


def has_deployment_claim(status: str) -> bool:
    return any(
        not conditional and clause_has_affirmative_deployment_claim(clause)
        for clause, conditional in semantic_claim_clauses(status)
    )


def status_is_pending(status: str) -> bool:
    normalized = normalize_claim_text(status)
    return bool(PENDING_STATUS_PATTERN.search(normalized)) or bool(
        NEGATED_ENGLISH_CLAIM_PATTERN.search(normalized) or NEGATED_CHINESE_CLAIM_PATTERN.search(normalized)
    )


def release_record_has_affirmative_version_deployment_prose(record: str) -> bool:
    version_match = RELEASE_RECORD_VERSION_PATTERN.search(record)
    if version_match is None:
        return False
    version = normalize_claim_text(version_match.group("version"))
    active_versions: set[str] = set()
    prose = "\n".join(line for line in record.splitlines() if not line.lstrip().startswith("|"))
    for clause, conditional in semantic_claim_clauses(prose):
        clause_versions = {
            normalize_claim_text(match.group(0))
            for match in VERSION_TOKEN_PATTERN.finditer(clause)
        }
        if clause_versions:
            active_versions = clause_versions
        if not conditional and version in active_versions and clause_has_affirmative_deployment_claim(clause):
            return True
    return False


def runtime_version_from_artifact(value: str) -> str:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                fail("Version artifact must contain one unambiguous machine-readable runtime version")
            result[key] = item
        return result

    try:
        payload = json.loads(value, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError("Version artifact must contain one unambiguous machine-readable runtime version") from exc
    if not isinstance(payload, dict) or set(payload) != {"version"}:
        fail("Version artifact must contain one unambiguous machine-readable runtime version")
    version = payload.get("version")
    if not isinstance(version, str) or SEMANTIC_VERSION_PATTERN.fullmatch(version) is None:
        fail("Version artifact must contain one unambiguous machine-readable runtime version")
    return version


def valid_sha256(value: str) -> bool:
    return not is_placeholder(value) and SHA256_PATTERN.fullmatch(value.strip()) is not None


def valid_backup_directory(value: str) -> bool:
    path = value.strip()
    return (
        not is_placeholder(path)
        and BACKUP_DIRECTORY_PATTERN.fullmatch(path) is not None
        and path.rsplit("/", 1)[-1] not in {".", ".."}
    )


def valid_release_directory(value: str) -> bool:
    path = value.strip()
    return (
        not is_placeholder(path)
        and RELEASE_DIRECTORY_PATTERN.fullmatch(path) is not None
        and path.rsplit("/", 1)[-1] not in {".", ".."}
    )


def valid_public_health_evidence(value: str) -> bool:
    return (
        not is_placeholder(value)
        and PUBLIC_HEALTH_URL_PATTERN.search(value) is not None
        and SUCCESS_STATUS_PATTERN.search(value) is not None
        and not PENDING_STATUS_PATTERN.search(value)
    )


def has_single_valid_evidence(
    evidence: dict[str, list[str]], field: str, validator: Callable[[str], bool]
) -> bool:
    values = evidence[field]
    return len(values) == 1 and validator(values[0])


def release_record_claims_deployed_without_live_evidence(record: str) -> bool:
    status = release_record_status(record)
    deployment_claimed = has_deployment_claim(status)
    prose_claimed = release_record_has_affirmative_version_deployment_prose(record)
    if (deployment_claimed or prose_claimed) and status_is_pending(status):
        fail("release record contains contradictory pending and deployment claims")
    if not deployment_claimed and not prose_claimed:
        return False
    evidence = release_record_evidence(record)
    return not (
        has_single_valid_evidence(evidence, "SHA256", valid_sha256)
        and has_single_valid_evidence(evidence, "Backup directory", valid_backup_directory)
        and has_single_valid_evidence(evidence, "Release directory", valid_release_directory)
        and has_single_valid_evidence(evidence, "Public health check", valid_public_health_evidence)
    )


def main() -> int:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    if missing:
        fail("Missing SOP files: " + ", ".join(missing))

    readme = read("README.md")
    if "build/server-release/" not in readme:
        fail("README must document build/server-release as the production package path")
    if "docs/sop/README.md" not in readme:
        fail("README must link the SOP index")

    gate = read("scripts/run-client-acceptance-gate.ps1")
    if "build\\client-release" in gate or "module-manager-v2-client-demo" in gate:
        fail("run-client-acceptance-gate.ps1 still references the legacy client-release package path")
    if "build\\server-release" not in gate:
        fail("run-client-acceptance-gate.ps1 must verify the server-release package")

    release_verifier = read("scripts/verify-client-release.py")
    if "build/client-release" in release_verifier or "module-manager-v2-client-demo" in release_verifier:
        fail("verify-client-release.py must not default to legacy client-release packages")
    build_script = read("scripts/build-client-release.ps1")
    if "scripts\\verify_admin_release_notes.js" not in build_script:
        fail("build-client-release.ps1 must copy scripts\\verify_admin_release_notes.js")
    if "scripts/verify_admin_release_notes.js" not in release_verifier:
        fail("verify-client-release.py must require scripts/verify_admin_release_notes.js")
    if "scripts\\verify_project_board_unmatched_review.js" not in build_script:
        fail("build-client-release.ps1 must copy scripts\\verify_project_board_unmatched_review.js")
    if "scripts/verify_project_board_unmatched_review.js" not in release_verifier:
        fail("verify-client-release.py must require scripts/verify_project_board_unmatched_review.js")
    if "scripts\\verify_dialog_information_integration.js" not in build_script:
        fail("build-client-release.ps1 must copy scripts\\verify_dialog_information_integration.js")
    if "scripts/verify_dialog_information_integration.js" not in release_verifier:
        fail("verify-client-release.py must require scripts/verify_dialog_information_integration.js")
    for artifact in ["v2-api/app/static/vue/version.json", "v2-web/public/version.json"]:
        if artifact not in release_verifier:
            fail(f"verify-client-release.py must require {artifact}")
    for artifact in ["v2-web\\public\\version.json", "v2-api\\app\\static\\vue\\version.json"]:
        if artifact not in build_script:
            fail(f"build-client-release.ps1 must verify the version artifact: {artifact}")
    for path in [
        "docs/sop/01-demand-intake-and-priority.md",
        "docs/sop/02-production-branch-versioning.md",
        "docs/sop/03-change-analysis-and-tdd.md",
        "docs/sop/04-subagent-review-template.md",
        "docs/sop/05-release-package-and-hash.md",
        "docs/sop/06-production-deploy-runbook.md",
        "docs/sop/07-rollback-and-incident-review.md",
        "docs/sop/08-business-acceptance-templates.md",
        "ops/releases/V3.0.79.md",
        "ops/releases/V3.0.78.md",
        "ops/releases/V3.0.77.md",
        "ops/releases/V3.0.76.md",
        "ops/releases/V3.0.75.md",
        "ops/releases/V3.0.74.md",
        "ops/releases/V3.0.73.md",
        "ops/releases/V3.0.72.md",
        "ops/releases/V3.0.71.md",
        "ops/releases/V3.0.70.md",
        "ops/releases/V3.0.69.md",
        "ops/releases/V3.0.68.md",
        "ops/releases/V3.0.67.md",
        "ops/releases/V3.0.66.md",
        "ops/releases/V3.0.65.md",
        "ops/releases/V3.0.64.md",
        "ops/releases/V3.0.63.md",
        "ops/releases/V3.0.62.md",
        "ops/releases/V3.0.61.md",
        "ops/releases/V3.0.60.md",
        "ops/releases/V3.0.59.md",
        "ops/releases/V3.0.58.md",
        "ops/releases/V3.0.56.md",
        "ops/releases/V3.0.55.md",
        "ops/releases/V3.0.54.md",
        "ops/releases/V3.0.53.md",
        "ops/releases/V3.0.52.md",
        "ops/releases/V3.0.51.md",
        "ops/releases/V3.0.50.md",
        "ops/releases/V3.0.49.md",
        "ops/releases/V3.0.48.md",
        "ops/releases/V3.0.47.md",
        "ops/releases/V3.0.45.md",
        "ops/releases/V3.0.46.md",
        "ops/releases/V3.0.44.md",
        "ops/releases/V3.0.42.md",
        "ops/releases/V3.0.41.md",
        "ops/releases/V3.0.40.md",
        "ops/releases/V3.0.39.md",
        "ops/releases/V3.0.38.md",
        "ops/releases/V3.0.37.md",
    ]:
        if path not in release_verifier:
            fail(f"verify-client-release.py must require {path}")

    stale_sop_hits = [
        path
        for path in [
            "docs/sop/README.md",
            "docs/sop/02-production-branch-versioning.md",
            "docs/sop/05-release-package-and-hash.md",
            "docs/sop/06-production-deploy-runbook.md",
        ]
        if "3.0.38" in read(path) or "V3.0.38" in read(path)
    ]
    if stale_sop_hits:
        fail("SOP files must not keep stale V3.0.38 deployment examples: " + ", ".join(stale_sop_hits))

    agents = read("AGENTS.md")
    if deployed_production_baseline(agents) != "V3.0.79":
        fail("AGENTS.md deployed production baseline must be V3.0.79 before deployment")
    candidate = release_candidate(agents)
    if candidate != "V3.0.80":
        fail("AGENTS.md release candidate must be V3.0.80")
    if "ops/releases" not in agents:
        fail("AGENTS.md must reference production release records")

    v3080_record = read("ops/releases/V3.0.80.md")
    if release_record_status(v3080_record).casefold() != "pending":
        fail("V3.0.80 release record status must remain explicitly pending before deployment")
    if release_record_claims_deployed_without_live_evidence(v3080_record):
        fail("V3.0.80 release record claims deployed without complete live evidence")

    source_runtime_version = runtime_version_from_artifact(read("v2-web/public/version.json"))
    if f"V{source_runtime_version}" != candidate:
        fail("Vue source runtime version artifact must match the AGENTS.md release candidate")
    version_surface_markers = {
        "scripts/build-client-release.ps1": f'[string]$Version = "{source_runtime_version}"',
        "v2-web/package.json": f'"version": "{source_runtime_version}"',
        "v2-web/src/constants/releaseNotes.ts": f"APP_VERSION = '{source_runtime_version}'",
        "v2-web/index.html": f"<title>Module Manager V{source_runtime_version}</title>",
        "v2-api/app/main.py": f'version="{source_runtime_version}"',
        "v2-api/app/services/ops_status.py": f'return "{source_runtime_version}"',
    }
    for path, marker in version_surface_markers.items():
        if marker not in read(path):
            fail(f"Version update surface {path} must match {source_runtime_version}")

    manifest_versions = [
        match.group("version")
        for match in MANIFEST_VERSION_LINE_PATTERN.finditer(read("RELEASE_MANIFEST.md"))
    ]
    if manifest_versions != [source_runtime_version]:
        fail("Root RELEASE_MANIFEST.md must define the candidate version exactly once")

    retention_runbook = read("docs/sop/06-production-deploy-runbook.md")
    for text in ["Production Release Retention", "cleanup_old_releases.sh", "keep 5", "--dry-run"]:
        if text not in retention_runbook:
            fail(f"deploy runbook must document release retention: {text}")

    print("[OK] release SOP files and references are consistent")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
