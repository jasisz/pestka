from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import KernelSpec
from .outcomes import Outcome, classify


FEEDBACK_MAX_BYTES = 16 * 1024 * 1024
OUTPUT_TAIL_BYTES = 4096


def _output_tail(path: Path) -> str:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - OUTPUT_TAIL_BYTES))
        return stream.read().decode(errors="replace")


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


def _feedback_features(data: bytes, format: str) -> frozenset[str]:
    if format == "lines":
        return frozenset(
            f"{hashlib.sha256(b'line\\0' + line.strip()).hexdigest()[:16]}:"
            f"{line.strip().decode(errors='replace')[:160]}"
            for line in data.splitlines()
            if line.strip()
        )
    if format == "bitmap-chunks":
        chunk_size = 64
        header_size = 2 * chunk_size
        return frozenset(
            f"{offset // chunk_size}:{hashlib.sha256(chunk).hexdigest()[:16]}"
            for offset in range(header_size, len(data), chunk_size)
            if any(chunk := data[offset : offset + chunk_size])
        )
    buckets = (1, 2, 3, 7, 15, 31, 127, 255)
    return frozenset(
        f"{index}:{next(limit for limit in buckets if value <= limit)}"
        for index, value in enumerate(data)
        if value
    )


def collect_feedback(
    kernel: KernelSpec, path: Path, run_dir: Path
) -> tuple[frozenset[str], str | None]:
    spec = kernel.feedback
    if spec is None:
        return frozenset(), None
    try:
        if spec.path is not None:
            feedback_path = Path(kernel.expand(spec.path, path, run_dir))
            if not feedback_path.exists():
                message = f"feedback file not created: {feedback_path}"
                return frozenset(), message if spec.required else None
            if feedback_path.stat().st_size > FEEDBACK_MAX_BYTES:
                raise ValueError(f"feedback exceeds {FEEDBACK_MAX_BYTES} bytes")
            data = feedback_path.read_bytes()
        else:
            assert spec.command is not None
            stdout_path = run_dir / "feedback.out"
            stderr_path = run_dir / "feedback.err"
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    [kernel.expand(part, path, run_dir) for part in spec.command],
                    cwd=kernel.cwd,
                    env=kernel.environment(run_dir, path),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=os.name == "posix",
                )
                try:
                    return_code = process.wait(timeout=min(kernel.timeout, 20.0))
                except subprocess.TimeoutExpired:
                    _kill_process_group(process)
                    process.wait()
                    raise ValueError("feedback command timed out")
            if return_code != 0:
                raise ValueError(
                    f"feedback command exited {return_code}: {_output_tail(stderr_path)[-1024:]}"
                )
            if stdout_path.stat().st_size > FEEDBACK_MAX_BYTES:
                raise ValueError(f"feedback exceeds {FEEDBACK_MAX_BYTES} bytes")
            data = stdout_path.read_bytes()
        return _feedback_features(data, spec.format), None
    except (OSError, subprocess.TimeoutExpired, ValueError) as failure:
        return frozenset(), str(failure)


def run_kernel(kernel: KernelSpec, path: Path) -> Outcome:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix=f"pestycyd-{kernel.name}-") as raw_dir:
        run_dir = Path(raw_dir)
        resolved = path.resolve()
        output_path = run_dir / "process.log"
        try:
            with output_path.open("wb") as output_stream:
                process = subprocess.Popen(
                    kernel.argv(resolved, run_dir),
                    cwd=kernel.cwd,
                    env=kernel.environment(run_dir, resolved),
                    stdin=subprocess.DEVNULL,
                    stdout=output_stream,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
                try:
                    exit_code = process.wait(timeout=kernel.timeout)
                    timed_out = False
                except subprocess.TimeoutExpired:
                    _kill_process_group(process)
                    process.wait()
                    exit_code = None
                    timed_out = True
            output = _output_tail(output_path)
            feedback, feedback_error = collect_feedback(kernel, resolved, run_dir)
            if timed_out:
                return Outcome(
                    status="timeout",
                    seconds=time.perf_counter() - started,
                    exit_code=None,
                    verdict=None,
                    output=output,
                    error=f"timeout after {kernel.timeout:g}s",
                    feedback=feedback,
                    feedback_error=feedback_error,
                )
            assert exit_code is not None
            status, verdict, error = classify(
                exit_code, output, kernel.verdict, kernel.exit_codes
            )
            if feedback_error and kernel.feedback is not None and kernel.feedback.required:
                status = "runner-error"
                error = f"required feedback failed: {feedback_error}"
            return Outcome(
                status=status,
                seconds=time.perf_counter() - started,
                exit_code=exit_code,
                verdict=verdict,
                output=output,
                error=error,
                feedback=feedback,
                feedback_error=feedback_error,
            )
        except OSError as failure:
            return Outcome(
                status="runner-error",
                seconds=time.perf_counter() - started,
                exit_code=None,
                verdict=None,
                output="",
                error=str(failure),
            )


def run_matrix(
    kernels: tuple[KernelSpec, ...], path: Path, workers: int | None = None
) -> dict[str, Outcome]:
    count = max(1, min(len(kernels), workers or len(kernels)))
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [(kernel.name, pool.submit(run_kernel, kernel, path)) for kernel in kernels]
        return {name: future.result() for name, future in futures}


def run_probe(kernel: KernelSpec) -> tuple[bool, str]:
    if kernel.probe is None:
        program = kernel.command[0]
        try:
            completed = subprocess.run(
                [program, "--help"],
                cwd=kernel.cwd,
                env=kernel.environment(kernel.cwd, kernel.cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=min(kernel.timeout, 10.0),
                check=False,
            )
            return True, f"launchable (exit {completed.returncode})"
        except (OSError, subprocess.TimeoutExpired) as failure:
            return False, str(failure)
    try:
        completed = subprocess.run(
            list(kernel.probe),
            cwd=kernel.cwd,
            env=kernel.environment(kernel.cwd, kernel.cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=min(kernel.timeout, 20.0),
            check=False,
        )
        tail = (completed.stdout or "").strip().splitlines()
        message = tail[-1] if tail else f"exit {completed.returncode}"
        return completed.returncode == 0, message
    except (OSError, subprocess.TimeoutExpired) as failure:
        return False, str(failure)

