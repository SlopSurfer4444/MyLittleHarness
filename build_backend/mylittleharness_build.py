from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_PATH_SAFE_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_PATH_SAFE_VERSION = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._+-]*[A-Za-z0-9])?$")
_PATH_FORBIDDEN_CHARS = {"/", "\\", ":"}
_SDIST_FILE_NAMES = (
    "AGENTS.md",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "RELEASE_NOTES.md",
    "pyproject.toml",
    "uv.lock",
)
_SDIST_DIR_NAMES = (".agents", ".mylittleharness", "build_backend", "docs", "project", "src", "tests")
_SDIST_EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
_SDIST_EXCLUDED_RELS = {
    ".mylittleharness/generated",
    ".mylittleharness/runtime",
}


def get_requires_for_build_wheel(config_settings: object | None = None) -> list[str]:
    return []


def get_requires_for_build_sdist(config_settings: object | None = None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings: object | None = None) -> str:
    dist_info = _dist_info_name()
    target = _safe_output_path(Path(metadata_directory), dist_info)
    target.mkdir(parents=True, exist_ok=True)
    _write_metadata_files(target)
    return dist_info


def build_wheel(
    wheel_directory: str,
    config_settings: object | None = None,
    metadata_directory: str | None = None,
) -> str:
    name, version = _package_identity()
    wheel_name = f"{name}-{version}-py3-none-any.whl"
    wheel_path = _safe_output_path(Path(wheel_directory), wheel_name)
    dist_info = _dist_info_name()
    records: list[tuple[str, bytes]] = []

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for rel_path, data in _package_source_payloads():
            wheel.writestr(rel_path, data)
            records.append((rel_path, data))
        for rel_path, data in _metadata_file_payloads(dist_info):
            wheel.writestr(rel_path, data)
            records.append((rel_path, data))
        record_path = f"{dist_info}/RECORD"
        wheel.writestr(record_path, _record_payload(records, record_path))
    return wheel_name


def build_sdist(sdist_directory: str, config_settings: object | None = None) -> str:
    name, version = _package_identity()
    archive_name = f"{name}-{version}.tar.gz"
    archive_path = _safe_output_path(Path(sdist_directory), archive_name)
    root_prefix = f"{name}-{version}"

    with tarfile.open(archive_path, "w:gz") as archive:
        for rel_path, data in _sdist_payloads():
            archive.addfile(_tar_info(f"{root_prefix}/{rel_path}", data), io.BytesIO(data))
    return archive_name


def _project_metadata() -> dict[str, object]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml [project] table is required")
    return project


def _dist_info_name() -> str:
    name, version = _package_identity()
    return f"{name}-{version}.dist-info"


def _write_metadata_files(target: Path) -> None:
    for rel_path, data in _metadata_file_payloads(target.name):
        (target.parent / rel_path).write_bytes(data)


def _metadata_file_payloads(dist_info: str) -> list[tuple[str, bytes]]:
    project = _project_metadata()
    metadata_lines = [
        "Metadata-Version: 2.1",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
        f"Summary: {_metadata_header_value(project.get('description', ''), 'project.description')}",
        f"Requires-Python: {_metadata_header_value(project.get('requires-python', '>=3.11'), 'project.requires-python')}",
    ]
    license_text = _license_metadata_value(project)
    if license_text:
        metadata_lines.append(f"License: {license_text}")
    for classifier in _classifier_metadata_values(project):
        metadata_lines.append(f"Classifier: {classifier}")
    metadata_lines.append("")
    metadata = "\n".join(metadata_lines).encode("utf-8")
    wheel = "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: mylittleharness-build",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    ).encode("utf-8")
    entry_points = "\n".join(
        [
            "[console_scripts]",
            "mylittleharness = mylittleharness.cli:main",
            "",
        ]
    ).encode("utf-8")
    top_level = b"mylittleharness\n"
    payloads = [
        (f"{dist_info}/METADATA", metadata),
        (f"{dist_info}/WHEEL", wheel),
        (f"{dist_info}/entry_points.txt", entry_points),
        (f"{dist_info}/top_level.txt", top_level),
    ]
    license_path = ROOT / "LICENSE"
    if license_path.is_file():
        payloads.append((f"{dist_info}/LICENSE", license_path.read_bytes()))
    return payloads


def _license_metadata_value(project: dict[str, object]) -> str:
    license_value = project.get("license")
    if license_value is None:
        return ""
    if isinstance(license_value, str):
        return _metadata_header_value(license_value, "project.license")
    if isinstance(license_value, dict) and "text" in license_value:
        return _metadata_header_value(license_value["text"], "project.license.text")
    raise ValueError("project.license must be a string or a table with text")


def _classifier_metadata_values(project: dict[str, object]) -> list[str]:
    classifiers = project.get("classifiers", [])
    if not isinstance(classifiers, list):
        raise ValueError("project.classifiers must be a list")
    return [_metadata_header_value(classifier, "project.classifiers") for classifier in classifiers]


def _metadata_header_value(value: object, field: str) -> str:
    text = str(value)
    if "\r" in text or "\n" in text or any(ord(char) < 32 for char in text):
        raise ValueError(f"{field} must be a single-line metadata value")
    return text


def _record_payload(records: list[tuple[str, bytes]], record_path: str) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for rel_path, data in records:
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
        writer.writerow([rel_path, f"sha256={digest}", str(len(data))])
    writer.writerow([record_path, "", ""])
    return output.getvalue()


def _tar_info(arcname: str, data: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _normalized_name(name: object) -> str:
    return str(name).replace("-", "_")


def _package_identity() -> tuple[str, str]:
    project = _project_metadata()
    name = _validated_distribution_name(project.get("name"))
    version = _validated_version(project.get("version"))
    return name, version


def _validated_distribution_name(value: object) -> str:
    raw = _path_safe_text(value, "project.name")
    normalized = _normalized_name(raw)
    if not _PATH_SAFE_NAME.fullmatch(normalized):
        raise ValueError(f"project.name must normalize to a path-safe distribution name: {raw!r}")
    return normalized


def _validated_version(value: object) -> str:
    version = _path_safe_text(value, "project.version")
    if not _PATH_SAFE_VERSION.fullmatch(version):
        raise ValueError(f"project.version must be path-safe: {version!r}")
    return version


def _path_safe_text(value: object, field: str) -> str:
    text = str(value)
    if not text or text != text.strip():
        raise ValueError(f"{field} must be a non-empty path-safe value")
    if ".." in text or any(char in text for char in _PATH_FORBIDDEN_CHARS) or any(ord(char) < 32 for char in text):
        raise ValueError(f"{field} must not contain path separators, parent segments, drive prefixes, or control characters")
    return text


def _safe_output_path(directory: Path, filename: str) -> Path:
    output_dir = directory.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate = output_dir / filename
    try:
        candidate.resolve(strict=False).relative_to(output_dir)
    except ValueError as exc:
        raise ValueError(f"build output path escapes the requested output directory: {filename}") from exc
    return candidate


def _package_source_payloads() -> list[tuple[str, bytes]]:
    package_dir = ROOT / "src/mylittleharness"
    source_dir = ROOT / "src"
    package_resolved = package_dir.resolve()
    payloads: list[tuple[str, bytes]] = []
    for path in sorted(package_dir.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        rel_path = path.relative_to(source_dir).as_posix()
        if path.is_symlink():
            raise ValueError(f"refusing symlinked package source member: {rel_path}")
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(package_resolved)
        except ValueError as exc:
            raise ValueError(f"package source member escapes package root: {rel_path}") from exc
        payloads.append((rel_path, path.read_bytes()))
    return payloads


def _sdist_payloads() -> list[tuple[str, bytes]]:
    root_resolved = ROOT.resolve()
    files: set[Path] = set()
    for name in _SDIST_FILE_NAMES:
        path = ROOT / name
        if path.is_file():
            files.add(path)
    for directory_name in _SDIST_DIR_NAMES:
        directory = ROOT / directory_name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_dir():
                continue
            rel_path = path.relative_to(ROOT)
            rel = rel_path.as_posix()
            if _sdist_excluded(rel_path):
                continue
            if path.is_symlink():
                raise ValueError(f"refusing symlinked source distribution member: {rel}")
            try:
                path.resolve().relative_to(root_resolved)
            except ValueError as exc:
                raise ValueError(f"source distribution member escapes project root: {rel}") from exc
            files.add(path)

    payloads: list[tuple[str, bytes]] = []
    for path in sorted(files, key=lambda candidate: candidate.relative_to(ROOT).as_posix()):
        rel_path = path.relative_to(ROOT).as_posix()
        payloads.append((rel_path, path.read_bytes()))
    return payloads


def _sdist_excluded(rel_path: Path) -> bool:
    rel_text = rel_path.as_posix()
    if any(rel_text == excluded or rel_text.startswith(f"{excluded}/") for excluded in _SDIST_EXCLUDED_RELS):
        return True
    return any(part in _SDIST_EXCLUDED_PARTS for part in rel_path.parts)
