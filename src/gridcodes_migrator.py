"""Safe, UI-independent GridCodes migration engine used by RBM.

The target template always defines the final structure.  Existing values are
preserved only for compatible keys or explicit/high-confidence rename rules;
source files are never changed by this module.
"""

from __future__ import annotations

import fnmatch
import json
import math
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple


APP_VERSION = "1.0"
ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252", "latin-1")
IGNORED_SUFFIXES = {".csv", ".json", ".log", ".zip", ".py", ".md", ".pdf", ".docx", ".xlsx", ".xls"}


class MigrationError(Exception):
    """Expected migration error that can be shown directly to an operator."""


@dataclass
class LayoutItem:
    kind: str
    raw: str = ""
    key: str = ""
    separator: str = "="
    prefix: str = ""
    before: str = ""
    after: str = " "


@dataclass
class ParsedConfig:
    layout: List[LayoutItem]
    values: Dict[str, str]
    duplicates: List[str] = field(default_factory=list)
    encoding: str = ""


@dataclass
class FileReport:
    source: str
    output: str
    source_parameters: int
    template_parameters: int
    unchanged: List[str]
    renamed: List[str]
    added: List[str]
    removed: List[str]
    unresolved_removed: List[str]
    profile_overrides: List[str]
    warnings: List[str]


@dataclass
class MigrationItem:
    source: Path
    relative_output: Path
    content: str
    report: FileReport


@dataclass
class MigrationPlan:
    source: Path
    template: Path
    template_parameters: int
    items: List[MigrationItem]
    errors: List[dict]
    manual_rules: Dict[str, str]
    generated_rules: Dict[str, str]
    project_profile: Dict[str, str]

    def summary(self) -> dict:
        return {
            "source": str(self.source),
            "template": str(self.template),
            "template_parameter_count": self.template_parameters,
            "processed_files": len(self.items),
            "error_count": len(self.errors),
            "manual_rules_loaded": dict(sorted(self.manual_rules.items())),
            "generated_auto_rules": dict(sorted(self.generated_rules.items())),
            "project_profile": dict(sorted(self.project_profile.items())),
            "reports": [asdict(item.report) for item in self.items],
            "errors": self.errors,
        }


def _decode(path: Path) -> Tuple[str, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MigrationError(f"Cannot read {path}: {exc}") from exc
    for encoding in ENCODINGS:
        try:
            text = raw.decode(encoding).lstrip("\ufeff")
        except UnicodeDecodeError:
            continue
        if text and text.count("\x00") / len(text) > 0.01 and not encoding.startswith("utf-16"):
            continue
        return text, encoding
    raise MigrationError(f"Cannot decode configuration file: {path}")


def parse_file(path: Path) -> ParsedConfig:
    text, encoding = _decode(path)
    layout: List[LayoutItem] = []
    values: Dict[str, str] = {}
    duplicates: List[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            layout.append(LayoutItem("blank", raw=""))
            continue
        if stripped.startswith(("#", ";")):
            layout.append(LayoutItem("comment", raw=line))
            continue
        match = re.match(r"^(\s*)([^=:#]+?)(\s*)([=:])(\s*)(.*)$", line)
        if not match or not match.group(2).strip():
            layout.append(LayoutItem("other", raw=line))
            continue
        prefix, raw_key, before, separator, after, value = match.groups()
        key = raw_key.strip()
        if key in values:
            duplicates.append(key)
        values[key] = value.strip()
        layout.append(LayoutItem("entry", key=key, separator=separator, prefix=prefix, before=before, after=after))
    # split() creates one final empty item for a terminal LF; retain only
    # meaningful layout while the renderer adds exactly one final LF.
    while layout and layout[-1].kind == "blank":
        layout.pop()
    return ParsedConfig(layout, values, sorted(set(duplicates)), encoding)


def render_template(template: ParsedConfig, values: Dict[str, str]) -> str:
    lines = []
    for item in template.layout:
        if item.kind == "entry":
            lines.append(f"{item.prefix}{item.key}{item.before}{item.separator}{item.after}{values.get(item.key, '')}")
        else:
            lines.append(item.raw)
    return "\n".join(lines).rstrip("\n") + "\n"


def _normalize_key(key: str) -> str:
    normalized = key.replace("ThreePhase", "3Ph").replace("SinglePhase", "1Ph")
    return re.sub(r"[^A-Za-z0-9]", "", normalized).lower()


def _similarity(old_key: str, new_key: str) -> float:
    old_normalized = _normalize_key(old_key)
    new_normalized = _normalize_key(new_key)
    score = SequenceMatcher(None, old_normalized, new_normalized).ratio()
    old_tokens = set(re.findall(r"[a-z]+|\d+", old_normalized))
    new_tokens = set(re.findall(r"[a-z]+|\d+", new_normalized))
    if old_tokens or new_tokens:
        score = (score * 0.7) + (0.3 * len(old_tokens & new_tokens) / len(old_tokens | new_tokens))
    if old_normalized in new_normalized or new_normalized in old_normalized:
        score += 0.05
    return min(score, 1.0)


def _auto_rules(source: ParsedConfig, template: ParsedConfig, manual_rules: Dict[str, str]) -> Dict[str, str]:
    old_only = set(source.values) - set(template.values) - set(manual_rules)
    new_only = set(template.values) - set(source.values) - set(manual_rules.values())
    suggestions = {}
    used = set()
    for old_key in sorted(old_only):
        candidates = sorted(((_similarity(old_key, new_key), new_key) for new_key in new_only - used), reverse=True)
        if not candidates or candidates[0][0] < 0.78:
            continue
        if len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= 0.10:
            suggestions[old_key] = candidates[0][1]
            used.add(candidates[0][1])
    return suggestions


def _load_manual_rules(path: Optional[Path]) -> Dict[str, str]:
    if path is None:
        return {}
    try:
        payload = json.loads(_decode(path)[0])
    except (ValueError, OSError) as exc:
        raise MigrationError(f"Invalid manual rules file: {exc}") from exc
    rules = payload.get("rename_rules", {})
    if not isinstance(rules, dict):
        raise MigrationError("manual rules must contain a rename_rules object")
    return {str(old): str(new) for old, new in rules.items()}


def _input_files(source: Path, pattern: str) -> List[Path]:
    if not source.exists():
        raise MigrationError(f"Source does not exist: {source}")
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise MigrationError(f"Source is not a file or folder: {source}")
    return sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() not in IGNORED_SUFFIXES and fnmatch.fnmatch(path.name, pattern))


def _vehicle_filename(filename: str, vehicle_name: str) -> str:
    """Optionally replace the vehicle segment in a GC_<vehicle>_<test> name."""
    if not vehicle_name:
        return filename
    match = re.match(r"^(GC_)[^_]+(_.+)$", filename)
    return f"{match.group(1)}{vehicle_name}{match.group(2)}" if match else filename


def _relative_output(source_file: Path, source_root: Path, vehicle_name: str) -> Path:
    relative = Path(source_file.name) if source_root.is_file() else source_file.relative_to(source_root)
    return relative.with_name(_vehicle_filename(relative.name, vehicle_name))


def _power_override(value: Optional[str], field: str) -> Optional[str]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise MigrationError(f"{field} must be a positive numeric value") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise MigrationError(f"{field} must be a positive numeric value")
    return str(int(parsed)) if parsed.is_integer() else f"{parsed:g}"


def _migrate_one(
    source_path: Path,
    relative_output: Path,
    template: ParsedConfig,
    manual_rules: Dict[str, str],
    power_overrides: Dict[str, str],
) -> Tuple[MigrationItem, Dict[str, str]]:
    source = parse_file(source_path)
    if not source.values:
        raise MigrationError("No key/value parameters found")
    automatic = _auto_rules(source, template, manual_rules)
    rules = {**automatic, **manual_rules}
    valid_rules = {old: new for old, new in rules.items() if new in template.values}
    values = dict(template.values)
    common = sorted(set(source.values) & set(template.values))
    for key in common:
        values[key] = source.values[key]
    renamed, warnings = [], []
    applied_overrides = []
    for key, value in power_overrides.items():
        if key in template.values:
            values[key] = value
            applied_overrides.append(f"{key}={value}")
        else:
            warnings.append(f"Profile override ignored because {key} is absent from the template")
    used_targets = set()
    for old, new in sorted(valid_rules.items()):
        if old not in source.values or new in source.values or new in used_targets:
            continue
        values[new] = source.values[old]
        used_targets.add(new)
        renamed.append(f"{old} -> {new}")
    old_only = sorted(set(source.values) - set(template.values))
    renamed_sources = {rule.split(" -> ", 1)[0] for rule in renamed}
    unresolved = [key for key in old_only if key not in renamed_sources]
    if source.duplicates:
        warnings.append("Duplicate source keys: " + ", ".join(source.duplicates))
    invalid = sorted(set(rules.values()) - set(template.values))
    if invalid:
        warnings.append("Ignored rule targets absent from template: " + ", ".join(invalid))
    report = FileReport(
        source=str(source_path), output=str(relative_output), source_parameters=len(source.values),
        template_parameters=len(template.values), unchanged=common, renamed=renamed,
        added=sorted((set(template.values) - set(source.values)) - used_targets),
        removed=old_only, unresolved_removed=unresolved,
        profile_overrides=applied_overrides, warnings=warnings,
    )
    return MigrationItem(source_path, relative_output, render_template(template, values), report), automatic


def analyze_migration(
    source: str | Path,
    template_path: str | Path,
    manual_rules_path: Optional[str | Path] = None,
    pattern: str = "*",
    vehicle_name: str = "",
    power_max_1ph_var: Optional[str] = None,
    power_max_3ph_var: Optional[str] = None,
) -> MigrationPlan:
    """Analyze all selected files without creating or changing output files."""
    source_path = Path(source).expanduser().resolve()
    template_file = Path(template_path).expanduser().resolve()
    template = parse_file(template_file)
    if not template.values:
        raise MigrationError("The target template contains no usable parameters")
    if template.duplicates:
        raise MigrationError("The target template has duplicate keys: " + ", ".join(template.duplicates))
    manual = _load_manual_rules(Path(manual_rules_path).expanduser().resolve() if manual_rules_path else None)
    vehicle_name = vehicle_name.strip()
    if vehicle_name and not re.fullmatch(r"[A-Za-z0-9-]+", vehicle_name):
        raise MigrationError("Vehicle name may contain only letters, digits, and hyphens")
    power_overrides = {
        key: value
        for key, value in (
            ("PowerMax_1Ph_VAr", _power_override(power_max_1ph_var, "PowerMax 1Ph")),
            ("PowerMax_3Ph_VAr", _power_override(power_max_3ph_var, "PowerMax 3Ph")),
        )
        if value is not None
    }
    profile = {"vehicle_name": vehicle_name, **power_overrides}
    items, errors, generated = [], [], {}
    files = _input_files(source_path, pattern)
    if not files:
        raise MigrationError("No configuration files were found in the selected source")
    for file_path in files:
        try:
            item, automatic = _migrate_one(
                file_path,
                _relative_output(file_path, source_path, vehicle_name),
                template,
                manual,
                power_overrides,
            )
            items.append(item)
            for old, new in automatic.items():
                if old not in generated:
                    generated[old] = new
        except MigrationError as exc:
            errors.append({"file": str(file_path), "error": str(exc)})
    return MigrationPlan(
        source_path, template_file, len(template.values), items, errors,
        manual, generated, profile,
    )


def export_plan(plan: MigrationPlan, output_dir: str | Path) -> Tuple[Path, Path]:
    """Export analysed files and a report, refusing to overwrite the source."""
    target = Path(output_dir).expanduser().resolve()
    if target == plan.source or (plan.source.is_file() and target / plan.source.name == plan.source):
        raise MigrationError("Output folder must be different from the source")
    if plan.source.is_dir():
        try:
            target.relative_to(plan.source)
        except ValueError:
            pass
        else:
            raise MigrationError("Output folder must not be inside the source folder")
    if not plan.items:
        raise MigrationError("There are no successfully analysed files to export")
    target.mkdir(parents=True, exist_ok=True)
    for item in plan.items:
        destination = target / item.relative_output
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(item.content)
    report_path = target / "migration_report.json"
    report_path.write_text(json.dumps(plan.summary(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target, report_path
