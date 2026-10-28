from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


class FindingStore:
    def __init__(self, root: Path):
        self.root = root
        self.findings = root / "findings"

    def _save(
        self, directory: str, schema: str, content: str, metadata: dict[str, object]
    ) -> tuple[str, bool]:
        digest = digest_text(content)
        root = self.root / directory
        case = root / f"{digest}.ndjson"
        sidecar = root / f"{digest}.json"
        created = not case.exists()
        if created:
            value = dict(metadata)
            value["schema"] = schema
            value["sha256"] = digest
            value["created_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            atomic_text(case, content)
            atomic_text(sidecar, json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        self.append_run({"kind": directory, "sha256": digest, "novel": created, **metadata})
        return digest, created

    def save(self, content: str, metadata: dict[str, object]) -> tuple[str, bool]:
        return self._save("findings", "pestycyd-finding-1", content, metadata)

    def save_corpus(self, content: str, metadata: dict[str, object]) -> tuple[str, bool]:
        return self._save("corpus", "pestycyd-corpus-1", content, metadata)

    def append_run(self, value: dict[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        row = {
            "schema": "pestycyd-run-1",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            **value,
        }
        with (self.root / "runs.jsonl").open("a") as stream:
            stream.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")

