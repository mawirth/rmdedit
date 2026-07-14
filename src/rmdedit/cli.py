#!/usr/bin/env python3
"""Small RMarkdown-to-PDF builder using rmarkdown::render and LuaLaTeX."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
SYSTEM_ROOT = Path("/usr/share/rmdedit")
DEFAULT_TEMPLATE = "notiz-neutral"
PROJECT_CONFIG = "rmdedit.json"
SYSTEM_CONFIG = Path("/etc/rmdedit/config.json")
SYSTEM_CONFIG_DIR = Path("/etc/rmdedit/config.d")
USER_CONFIG = Path.home() / ".config" / "rmdedit" / "config.json"
LOCAL_ASSET_DIRS = ("assets", "bilder", "anlagen")
CLEAN_PATTERNS = [
    "*.aux",
    "*.log",
    "*.out",
    "*.toc",
    "*.lof",
    "*.lot",
    "*.bbl",
    "*.blg",
    "*.fls",
    "*.fdb_latexmk",
    "*.synctex.gz",
]
WINDOWS_STATUS_BAD_FUNCTION_TABLE = {-1073741569, 0xC00000FF}


@dataclass(frozen=True)
class TemplateRoot:
    name: str
    path: Path
    assets: Path | None


@dataclass(frozen=True)
class TemplateMatch:
    requested: str
    template: Path
    root: TemplateRoot
    searched: list[Path]


@dataclass(frozen=True)
class PackageRequirement:
    name: str
    operator: str
    version: str


def parse_args(argv: list[str]) -> argparse.Namespace:
    normalized = []
    for arg in argv:
        if arg in {"-force", "-Force"}:
            normalized.append("--force")
        elif arg in {"-clean", "-Clean"}:
            normalized.append("--clean")
        else:
            normalized.append(arg)

    parser = argparse.ArgumentParser(
        prog="rmdedit",
        description="Build RMarkdown files as PDFs with rmarkdown::render and LuaLaTeX.",
    )
    parser.add_argument("inputs", nargs="*", help="Rmd files or directories. Defaults to *.Rmd in the current directory.")
    parser.add_argument("-f", "--force", action="store_true", help="Build even if the PDF is newer than inputs.")
    parser.add_argument("-c", "--clean", action="store_true", help="Remove temporary LaTeX files after processing.")
    parser.add_argument("-o", "--output", help="Output PDF path. Only valid with exactly one input file.")
    parser.add_argument(
        "--skip-requirements",
        action="store_true",
        help="Do not check RPM package requirements declared in YAML.",
    )
    return parser.parse_args(normalized)


def load_config_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Config-Datei ist kein gueltiges JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Config-Datei muss ein JSON-Objekt enthalten: {path}")
    return data


def root_from_config(entry: dict, base_dir: Path) -> TemplateRoot:
    if not isinstance(entry, dict):
        raise RuntimeError("template_roots-Eintraege muessen JSON-Objekte sein.")
    name = str(entry.get("name", "")).strip()
    raw_path = str(entry.get("path", "")).strip()
    if not name or not raw_path:
        raise RuntimeError("Jeder Template-Root braucht 'name' und 'path'.")
    template_path = resolve_config_path(raw_path, base_dir)
    assets = entry.get("assets")
    asset_path = resolve_config_path(str(assets), base_dir) if assets else None
    return TemplateRoot(name=name, path=template_path, assets=asset_path)


def resolve_config_path(raw: str, base_dir: Path) -> Path:
    path = Path(os.path.expanduser(raw))
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def configured_roots() -> list[TemplateRoot]:
    roots: list[TemplateRoot] = []
    project_config = Path.cwd() / PROJECT_CONFIG

    for config_path in [project_config, USER_CONFIG, SYSTEM_CONFIG]:
        config = load_config_file(config_path)
        for entry in config.get("template_roots", []):
            roots.append(root_from_config(entry, config_path.parent))

    roots.append(TemplateRoot("base", rmdedit_root() / "templates", rmdedit_root() / "assets"))

    if SYSTEM_CONFIG_DIR.is_dir():
        for config_path in sorted(SYSTEM_CONFIG_DIR.glob("*.json")):
            config = load_config_file(config_path)
            for entry in config.get("template_roots", []):
                roots.append(root_from_config(entry, config_path.parent))

    return roots


def rmdedit_root() -> Path:
    if (SCRIPT_DIR / "templates").is_dir():
        return SCRIPT_DIR
    if SYSTEM_ROOT.is_dir():
        return SYSTEM_ROOT
    return SCRIPT_DIR


def find_rmd_files(inputs: Iterable[str]) -> list[Path]:
    values = list(inputs)
    if not values:
        return sorted(Path.cwd().glob("*.Rmd"))

    found: list[Path] = []
    for value in values:
        path = Path(value)
        if path.is_dir():
            found.extend(sorted(path.glob("*.Rmd")))
        elif path.is_file() and path.suffix == ".Rmd":
            found.append(path)
        else:
            raise RuntimeError(f"Keine Rmd-Datei oder kein Verzeichnis: {value}")
    return [p.resolve() for p in found]


def read_frontmatter(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    collected = []
    for line in lines[1:]:
        if line.strip() in {"---", "..."}:
            break
        collected.append(line)
    return "\n".join(collected)


def template_name_from_yaml(path: Path) -> str:
    yaml = read_frontmatter(path)
    if not yaml:
        return DEFAULT_TEMPLATE

    legacy = re.search(r"(?m)^rmdedit_template:\s*['\"]?([^'\"\s#]+)", yaml)
    current = None
    lines = yaml.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^rmdedit:\s*(?:#.*)?$", line):
            base_indent = len(line) - len(line.lstrip(" "))
            for child in lines[index + 1 :]:
                stripped = child.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                indent = len(child) - len(child.lstrip(" "))
                if indent <= base_indent:
                    break
                match = re.match(r"^template:\s*['\"]?([^'\"\s#]+)", stripped)
                if match:
                    current = match.group(1)
                    break
            break

    if current:
        return current
    if legacy:
        return legacy.group(1)
    return DEFAULT_TEMPLATE


def rmdedit_section_lines(yaml: str) -> list[str]:
    lines = yaml.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^rmdedit:\s*(?:#.*)?$", line):
            base_indent = len(line) - len(line.lstrip(" "))
            section = []
            for child in lines[index + 1 :]:
                stripped = child.strip()
                if not stripped or stripped.startswith("#"):
                    section.append(child)
                    continue
                indent = len(child) - len(child.lstrip(" "))
                if indent <= base_indent:
                    break
                section.append(child)
            return section
    return []


def package_requirements_from_yaml(path: Path) -> list[PackageRequirement]:
    yaml = read_frontmatter(path)
    if not yaml:
        return []

    section = rmdedit_section_lines(yaml)
    requirements: list[PackageRequirement] = []
    requires_indent = None
    index = 0
    while index < len(section):
        line = section[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if re.match(r"^requires:\s*(?:#.*)?$", stripped):
            requires_indent = indent
            index += 1
            continue
        if requires_indent is None or indent <= requires_indent:
            index += 1
            continue
        if not stripped.startswith("-"):
            index += 1
            continue

        item = stripped[1:].strip()
        if item.startswith("name:"):
            name = unquote(item.split(":", 1)[1].strip())
            version = ""
            child_index = index + 1
            while child_index < len(section):
                child = section[child_index]
                child_stripped = child.strip()
                child_indent = len(child) - len(child.lstrip(" "))
                if child_stripped and child_indent <= indent:
                    break
                if child_stripped.startswith("version:"):
                    version = unquote(child_stripped.split(":", 1)[1].strip())
                child_index += 1
            requirements.append(parse_requirement_parts(name, version))
            index = child_index
            continue

        requirements.append(parse_requirement_text(unquote(item)))
        index += 1

    return requirements


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        return value[1:-1]
    return value


def parse_requirement_text(value: str) -> PackageRequirement:
    match = re.match(r"^([A-Za-z0-9_.+-]+)\s*(>=|<=|=|>|<)\s*([A-Za-z0-9_.:+~%-]+)$", value)
    if not match:
        raise RuntimeError(
            "rmdedit.requires-Eintraege brauchen Paketname, Vergleichsoperator und Version, "
            f"z. B. 'rmdedit >= 0.1.0': {value}"
        )
    return PackageRequirement(name=match.group(1), operator=match.group(2), version=match.group(3))


def parse_requirement_parts(name: str, version: str) -> PackageRequirement:
    if not name:
        raise RuntimeError("rmdedit.requires-Eintrag mit 'name:' braucht einen Paketnamen.")
    match = re.match(r"^(>=|<=|=|>|<)?\s*([A-Za-z0-9_.:+~%-]+)$", version)
    if not match:
        raise RuntimeError(
            f"rmdedit.requires-Eintrag fuer {name} braucht eine Version, z. B. version: '>= 0.1.0'."
        )
    return PackageRequirement(name=name, operator=match.group(1) or ">=", version=match.group(2))


def check_package_requirements(requirements: list[PackageRequirement]) -> None:
    if not requirements:
        return
    if shutil.which("rpm") is None:
        raise RuntimeError("RPM nicht gefunden. Paketvoraussetzungen koennen nicht geprueft werden.")
    if shutil.which("rpmdev-vercmp") is None:
        raise RuntimeError("rpmdev-vercmp nicht gefunden. Bitte rpmdevtools installieren.")

    missing = []
    for requirement in requirements:
        installed = installed_package_version(requirement.name)
        if installed is None or not version_satisfies(installed, requirement.operator, requirement.version):
            missing.append(format_requirement(requirement, installed))

    if missing:
        missing_text = "\n".join(f"  - {item}" for item in missing)
        raise RuntimeError(f"RPM-Paketvoraussetzungen nicht erfuellt:\n{missing_text}")


def installed_package_version(name: str) -> str | None:
    result = subprocess.run(
        ["rpm", "-q", "--queryformat", "%{VERSION}", name],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def version_satisfies(installed: str, operator: str, required: str) -> bool:
    comparison = rpm_version_compare(installed, required)
    if operator == "=":
        return comparison == 0
    if operator == ">=":
        return comparison >= 0
    if operator == "<=":
        return comparison <= 0
    if operator == ">":
        return comparison > 0
    if operator == "<":
        return comparison < 0
    raise RuntimeError(f"Nicht unterstuetzter Vergleichsoperator: {operator}")


def rpm_version_compare(left: str, right: str) -> int:
    result = subprocess.run(
        ["rpmdev-vercmp", left, right],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode == 0:
        return 0
    if result.returncode == 11:
        return 1
    if result.returncode == 12:
        return -1
    raise RuntimeError(f"rpmdev-vercmp fehlgeschlagen fuer {left} und {right}: {result.stdout.strip()}")


def format_requirement(requirement: PackageRequirement, installed: str | None) -> str:
    expected = f"{requirement.name} {requirement.operator} {requirement.version}"
    if installed is None:
        return f"{expected} (nicht installiert)"
    return f"{expected} (installiert: {installed})"


def candidate_names(name: str) -> list[str]:
    if name.endswith(".tex"):
        return [name]
    return [f"template-{name}.tex", f"{name}.tex"]


def resolve_template(requested: str, roots: list[TemplateRoot]) -> TemplateMatch:
    namespace = None
    name = requested
    if "/" in requested:
        namespace, name = requested.split("/", 1)

    active_roots = [root for root in roots if namespace is None or root.name == namespace]
    searched: list[Path] = []
    matches: list[tuple[TemplateRoot, Path]] = []
    for root in active_roots:
        for candidate in candidate_names(name):
            path = (root.path / candidate).resolve()
            searched.append(path)
            if path.exists():
                matches.append((root, path))
                break

    if not matches:
        searched_text = "\n".join(f"  - {path}" for path in searched)
        scope = f" im Namespace '{namespace}'" if namespace else ""
        raise RuntimeError(f"Template '{requested}' nicht gefunden{scope}. Gesuchte Pfade:\n{searched_text}")

    root, path = matches[0]
    return TemplateMatch(requested=requested, template=path, root=root, searched=searched)


def newest_mtime(paths: Iterable[Path]) -> float:
    newest = 0.0
    for path in paths:
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    newest = max(newest, child.stat().st_mtime)
    return newest


def needs_build(rmd: Path, match: TemplateMatch, force: bool, pdf: Path | None = None) -> bool:
    if force:
        return True
    pdf = pdf or rmd.with_suffix(".pdf")
    if not pdf.exists():
        return True
    pdf_mtime = pdf.stat().st_mtime
    roots_to_scan = [rmd, match.root.path]
    if match.root.assets:
        roots_to_scan.append(match.root.assets)
    roots_to_scan.extend(local_asset_dirs(rmd.parent))
    return newest_mtime(roots_to_scan) > pdf_mtime


def local_asset_dirs(directory: Path) -> list[Path]:
    """Fallbezogene Assets neben der Rmd fuer den Aktualitaetscheck."""
    return [directory / name for name in LOCAL_ASSET_DIRS if (directory / name).is_dir()]


def clean_latex_files(directory: Path) -> list[Path]:
    removed: list[Path] = []
    for pattern in CLEAN_PATTERNS:
        for path in directory.glob(pattern):
            if path.is_file():
                path.unlink()
                removed.append(path)
    return removed


def pandoc_path(path: PurePath) -> str:
    """Return a path that is safe to embed in Pandoc/LaTeX variables."""
    return path.as_posix()


def file_state(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def complete_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                return False
            handle.seek(max(0, path.stat().st_size - 1024))
            return b"%%EOF" in handle.read()
    except (OSError, ValueError):
        return False


def recoverable_windows_r_shutdown(
    returncode: int,
    pdf: Path,
    previous_state: tuple[int, int] | None,
) -> bool:
    """Recognize the known Windows R shutdown crash after a valid render."""
    return (
        sys.platform == "win32"
        and returncode in WINDOWS_STATUS_BAD_FUNCTION_TABLE
        and file_state(pdf) != previous_state
        and complete_pdf(pdf)
    )


def render(rmd: Path, match: TemplateMatch, output: Path | None = None) -> subprocess.CompletedProcess[str]:
    if shutil.which("Rscript") is None:
        raise RuntimeError("Rscript nicht gefunden. Bitte R installieren oder Rscript in PATH aufnehmen.")

    assets = match.root.assets or Path("")
    fonts = assets / "fonts" if assets else Path("")
    logos = assets / "logos" if assets else Path("")
    cache = tex_cache_dir()

    r_expr = (
        "args <- commandArgs(trailingOnly = TRUE); "
        "options(tinytex.install_packages = FALSE); "
        "fmt <- rmarkdown::pdf_document("
        "template = args[[2]], latex_engine = 'lualatex', "
        "pandoc_args = c('-V', paste0('rmdedit-assets=', args[[3]]), "
        "'-V', paste0('rmdedit-fonts=', args[[4]]), "
        "'-V', paste0('rmdedit-logos=', args[[5]]))); "
        "output <- if (length(args) >= 6 && nzchar(args[[6]])) args[[6]] else ''; "
        "if (nzchar(output)) { "
        "rmarkdown::render(args[[1]], output_format = fmt, output_file = basename(output), "
        "output_dir = dirname(output), quiet = TRUE) "
        "} else { "
        "rmarkdown::render(args[[1]], output_format = fmt, quiet = TRUE) "
        "}"
    )

    env = os.environ.copy()
    root = rmdedit_root()
    env["RMDEDIT_ROOT"] = str(root)
    textblocks = match.root.path.parent / "textbausteine"
    textblock_assets = match.root.path.parent / "assets" / "textbausteine"
    if textblocks.is_dir():
        env["RMDEDIT_TEXTBLOCKS"] = str(textblocks)
    if textblock_assets.is_dir():
        env["RMDEDIT_TEXTBLOCK_ASSETS"] = str(textblock_assets)
    env.update(tex_environment(match.template.parent, cache, env))

    return subprocess.run(
        [
            "Rscript",
            "-e",
            r_expr,
            str(rmd),
            str(match.template),
            pandoc_path(assets),
            pandoc_path(fonts),
            pandoc_path(logos),
            str(output) if output else "",
        ],
        cwd=str(rmd.parent),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def tex_cache_dir() -> Path:
    root = rmdedit_root()
    if os.access(root, os.W_OK):
        cache = root / ".texlive-cache"
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "rmdedit" / "texlive-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def tex_environment(template_dir: Path, cache: Path, env: dict[str, str]) -> dict[str, str]:
    existing_texinputs = env.get("TEXINPUTS", "")
    root = rmdedit_root()
    return {
        "TEXINPUTS": f"{template_dir}{os.pathsep}{root / 'templates'}{os.pathsep}{existing_texinputs}",
        "TEXMFVAR": str(cache),
        "TEXMFCACHE": str(cache),
    }


def tail(text: str, lines: int = 30) -> str:
    parts = text.rstrip().splitlines()
    return "\n".join(parts[-lines:])


def process_file(
    rmd: Path,
    roots: list[TemplateRoot],
    force: bool,
    clean: bool,
    skip_requirements: bool,
    output: Path | None = None,
) -> bool:
    if not skip_requirements:
        check_package_requirements(package_requirements_from_yaml(rmd))
    template_name = template_name_from_yaml(rmd)
    match = resolve_template(template_name, roots)
    pdf = output or rmd.with_suffix(".pdf")

    if needs_build(rmd, match, force, pdf):
        print(f"Baue {rmd} mit Template {template_name} ({match.template})", flush=True)
        previous_pdf_state = file_state(pdf)
        result = render(rmd, match, output)
        recovered_shutdown = recoverable_windows_r_shutdown(
            result.returncode, pdf, previous_pdf_state
        )
        if result.returncode != 0 and not recovered_shutdown:
            print(f"Fehler beim Bauen von {rmd}", file=sys.stderr)
            print(f"Template: {template_name}", file=sys.stderr)
            print(f"Template-Pfad: {match.template}", file=sys.stderr)
            print(tail(result.stdout), file=sys.stderr)
            if clean:
                removed = clean_latex_files(rmd.parent)
                print(f"Clean: {len(removed)} temporaere Datei(en) entfernt in {rmd.parent}.")
            return False
        if recovered_shutdown:
            print(
                "Warnung: Rscript meldete beim Beenden unter Windows "
                "STATUS_BAD_FUNCTION_TABLE; das neu erzeugte PDF ist vollstaendig."
            )
        print(f"Erzeugt: {pdf}")
    else:
        print(f"Ueberspringe {rmd}: {pdf.name} ist aktuell.")

    if clean:
        removed = clean_latex_files(rmd.parent)
        print(f"Clean: {len(removed)} temporaere Datei(en) entfernt in {rmd.parent}.")
    return True


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        files = find_rmd_files(args.inputs)
        if not files:
            print("Keine .Rmd-Dateien gefunden.", file=sys.stderr)
            return 1
        output = resolve_config_path(args.output, Path.cwd()) if args.output else None
        if output and len(files) != 1:
            raise RuntimeError("--output kann nur mit genau einer .Rmd-Datei verwendet werden.")
        if output and output.suffix.lower() != ".pdf":
            raise RuntimeError("--output muss auf eine .pdf-Datei zeigen.")
        roots = configured_roots()
        ok = True
        for rmd in files:
            ok = process_file(rmd, roots, args.force, args.clean, args.skip_requirements, output) and ok
        return 0 if ok else 1
    except RuntimeError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
