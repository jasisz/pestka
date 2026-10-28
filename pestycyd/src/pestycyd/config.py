from __future__ import annotations

import hashlib
import json
import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .outcomes import Status


VERDICT_MODES = {"required", "optional", "none"}
FEEDBACK_FORMATS = {"lines", "bitmap", "bitmap-chunks"}
EXIT_STATUSES = {"accept", "reject", "decline", "crash", "error"}


@dataclass(frozen=True)
class FeedbackSpec:
    format: str
    path: str | None = None
    command: tuple[str, ...] | None = None
    required: bool = False

    def public(self) -> dict[str, object]:
        return {
            "format": self.format,
            "path": self.path,
            "command": None if self.command is None else list(self.command),
            "required": self.required,
        }


@dataclass(frozen=True)
class KernelSpec:
    name: str
    command: tuple[str, ...]
    cwd: Path
    timeout: float
    verdict: str
    enabled: bool = True
    exit_codes: tuple[tuple[int, Status], ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    probe: tuple[str, ...] | None = None
    feedback: FeedbackSpec | None = None

    def expand(self, value: str, path: Path, run_dir: Path) -> str:
        return value.replace("{file}", str(path)).replace("{run_dir}", str(run_dir))

    def argv(self, path: Path, run_dir: Path) -> list[str]:
        return [self.expand(part, path, run_dir) for part in self.command]

    def environment(self, run_dir: Path, path: Path) -> dict[str, str]:
        values = os.environ.copy()
        for key, value in self.env:
            values[key] = self.expand(value, path, run_dir)
        return values

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": list(self.command),
            "cwd": str(self.cwd),
            "timeout": self.timeout,
            "verdict": self.verdict,
            "enabled": self.enabled,
            "exit_codes": {status: code for code, status in self.exit_codes},
            "env": dict(self.env),
            "probe": None if self.probe is None else list(self.probe),
            "feedback": None if self.feedback is None else self.feedback.public(),
            "executable": executable_fingerprint(self),
        }


@dataclass(frozen=True)
class Config:
    path: Path
    state: Path
    kernels: tuple[KernelSpec, ...]

    def selected(self, names: list[str] | None) -> tuple[KernelSpec, ...]:
        if not names:
            return tuple(kernel for kernel in self.kernels if kernel.enabled)
        wanted = set(names)
        found = tuple(kernel for kernel in self.kernels if kernel.name in wanted)
        missing = wanted.difference(kernel.name for kernel in found)
        if missing:
            raise ValueError(f"unknown kernels: {', '.join(sorted(missing))}")
        return found


def _string_list(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{where} must be a non-empty string array")
    return tuple(value)


def load_config(path: Path) -> Config:
    path = path.resolve()
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    if raw.get("version") != 1:
        raise ValueError("configuration needs version = 1")
    base = path.parent
    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("[defaults] must be a table")
    default_timeout = float(defaults.get("timeout", 20.0))
    state_value = defaults.get("state", ".pestycyd")
    if not isinstance(state_value, str):
        raise ValueError("defaults.state must be a string")
    state = (base / state_value).resolve()
    kernel_tables = raw.get("kernels")
    if not isinstance(kernel_tables, dict) or not kernel_tables:
        raise ValueError("configuration needs at least one [kernels.NAME] table")
    kernels: list[KernelSpec] = []
    for name, table in kernel_tables.items():
        if not isinstance(name, str) or not isinstance(table, dict):
            raise ValueError("invalid kernel table")
        command = _string_list(table.get("command"), f"kernels.{name}.command")
        verdict = table.get("verdict", "required")
        if verdict not in VERDICT_MODES:
            raise ValueError(f"kernels.{name}.verdict must be required, optional, or none")
        cwd_value = table.get("cwd", ".")
        if not isinstance(cwd_value, str):
            raise ValueError(f"kernels.{name}.cwd must be a string")
        env_value = table.get("env", {})
        if not isinstance(env_value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env_value.items()
        ):
            raise ValueError(f"kernels.{name}.env must be a string table")
        if not any("{file}" in part for part in command) and not any(
            "{file}" in value for value in env_value.values()
        ):
            raise ValueError(f"kernels.{name} command or environment must contain {{file}}")
        probe_value = table.get("probe")
        probe = None if probe_value is None else _string_list(probe_value, f"kernels.{name}.probe")
        feedback_value = table.get("feedback")
        feedback = None
        if feedback_value is not None:
            if not isinstance(feedback_value, dict):
                raise ValueError(f"kernels.{name}.feedback must be a table")
            feedback_format = feedback_value.get("format", "lines")
            if not isinstance(feedback_format, str) or feedback_format not in FEEDBACK_FORMATS:
                raise ValueError(
                    f"kernels.{name}.feedback.format must be lines, bitmap or bitmap-chunks"
                )
            feedback_path = feedback_value.get("path")
            feedback_command_value = feedback_value.get("command")
            if feedback_path is not None and not isinstance(feedback_path, str):
                raise ValueError(f"kernels.{name}.feedback.path must be a string")
            feedback_command = (
                None
                if feedback_command_value is None
                else _string_list(feedback_command_value, f"kernels.{name}.feedback.command")
            )
            if (feedback_path is None) == (feedback_command is None):
                raise ValueError(
                    f"kernels.{name}.feedback needs exactly one of path or command"
                )
            if feedback_path is not None and "{run_dir}" not in feedback_path:
                raise ValueError(f"kernels.{name}.feedback.path must contain {{run_dir}}")
            required = feedback_value.get("required", False)
            if not isinstance(required, bool):
                raise ValueError(f"kernels.{name}.feedback.required must be boolean")
            feedback = FeedbackSpec(
                format=str(feedback_format),
                path=feedback_path,
                command=feedback_command,
                required=required,
            )
        timeout = float(table.get("timeout", default_timeout))
        if timeout <= 0:
            raise ValueError(f"kernels.{name}.timeout must be positive")
        enabled = table.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"kernels.{name}.enabled must be boolean")
        exit_codes_value = table.get("exit_codes", {})
        if not isinstance(exit_codes_value, dict):
            raise ValueError(f"kernels.{name}.exit_codes must be a table")
        parsed_exit_codes: list[tuple[int, Status]] = []
        seen_codes: set[int] = set()
        for status, code in exit_codes_value.items():
            if status not in EXIT_STATUSES or not isinstance(code, int) or isinstance(code, bool):
                raise ValueError(
                    f"kernels.{name}.exit_codes needs status = integer entries"
                )
            if code in seen_codes:
                raise ValueError(f"kernels.{name}.exit_codes maps exit {code} more than once")
            seen_codes.add(code)
            parsed_exit_codes.append((code, status))  # type: ignore[arg-type]
        kernels.append(
            KernelSpec(
                name=name,
                command=command,
                cwd=(base / cwd_value).resolve(),
                timeout=timeout,
                verdict=str(verdict),
                enabled=enabled,
                exit_codes=tuple(sorted(parsed_exit_codes)),
                env=tuple(sorted(env_value.items())),
                probe=probe,
                feedback=feedback,
            )
        )
    return Config(path=path, state=state, kernels=tuple(kernels))


def executable_fingerprint(spec: KernelSpec) -> dict[str, object] | None:
    program = Path(spec.command[0])
    if not program.is_absolute():
        local = spec.cwd / program
        resolved = shutil.which(spec.command[0]) if "/" not in spec.command[0] else None
        program = local if local.exists() or resolved is None else Path(resolved)
    try:
        real = program.resolve(strict=True)
        if not real.is_file():
            return None
        digest = hashlib.sha256()
        with real.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        stat = real.stat()
        return {"path": str(real), "sha256": digest.hexdigest(), "bytes": stat.st_size}
    except OSError:
        return None


def snapshot(config: Config, kernels: tuple[KernelSpec, ...]) -> str:
    value = {"config": str(config.path), "kernels": [kernel.public() for kernel in kernels]}
    return json.dumps(value, sort_keys=True, ensure_ascii=False)

