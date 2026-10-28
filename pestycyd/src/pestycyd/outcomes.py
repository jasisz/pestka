from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal


Status = Literal[
    "accept",
    "reject",
    "decline",
    "timeout",
    "crash",
    "error",
    "runner-error",
]

_ACCEPT = re.compile(r"^accepted(?:\s+\d+\s+declarations)?$", re.IGNORECASE)


def parse_verdict(output: str) -> Status | None:
    for line in reversed(output.splitlines()):
        text = line.strip()
        if _ACCEPT.fullmatch(text):
            return "accept"
        if text.lower() == "accepted":
            return "accept"
        if text.lower().startswith("rejected:") or text.lower() == "rejected":
            return "reject"
        if text.lower().startswith("declined:") or text.lower() == "declined":
            return "decline"
    return None


def code_status(code: int, exit_codes: tuple[tuple[int, Status], ...] = ()) -> Status:
    configured = dict(exit_codes)
    if code in configured:
        return configured[code]
    if code == 0:
        return "accept"
    if code == 1:
        return "reject"
    if code == 2:
        return "decline"
    if code < 0 or code in {101, 134, 137, 139}:
        return "crash"
    return "error"


@dataclass(frozen=True)
class Outcome:
    status: Status
    seconds: float
    exit_code: int | None
    verdict: Status | None
    output: str
    error: str | None = None
    feedback: frozenset[str] = frozenset()
    feedback_error: str | None = None

    @property
    def fingerprint(self) -> str:
        normalized = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", self.output[-4096:])
        normalized = re.sub(r"\b\d{4,}\b", "N", normalized)
        material = f"{self.status}\n{self.exit_code}\n{normalized}".encode()
        return hashlib.sha256(material).hexdigest()[:16]

    @property
    def feedback_fingerprint(self) -> str | None:
        if not self.feedback:
            return None
        material = "\n".join(sorted(self.feedback)).encode()
        return hashlib.sha256(material).hexdigest()[:16]

    def json(self) -> dict[str, object]:
        value: dict[str, object] = {
            "status": self.status,
            "seconds": round(self.seconds, 6),
            "exit_code": self.exit_code,
            "verdict": self.verdict,
            "fingerprint": self.fingerprint,
        }
        if self.output:
            value["output"] = self.output[-4096:]
        if self.error:
            value["error"] = self.error
        if self.feedback:
            value["feedback"] = {
                "features": len(self.feedback),
                "fingerprint": self.feedback_fingerprint,
            }
        if self.feedback_error:
            value["feedback_error"] = self.feedback_error
        return value


def classify(
    exit_code: int,
    output: str,
    verdict_mode: str,
    exit_codes: tuple[tuple[int, Status], ...] = (),
) -> tuple[Status, Status | None, str | None]:
    verdict = parse_verdict(output)
    by_code = code_status(exit_code, exit_codes)
    if verdict_mode == "none":
        return by_code, verdict, None
    if verdict is None:
        if verdict_mode == "required":
            if by_code in {"crash", "error"}:
                return by_code, None, None
            return "runner-error", None, "process produced no recognized verdict"
        return by_code, None, None
    if by_code in {"crash", "error"}:
        return by_code, verdict, None
    if verdict != by_code:
        return "runner-error", verdict, f"verdict {verdict} disagrees with exit code {exit_code}"
    return verdict, verdict, None

