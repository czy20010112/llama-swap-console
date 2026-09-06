from __future__ import annotations

import gc
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from gguf import GGUFReader


_AUXILIARY_GGUF_ARCHITECTURES = {
    "bert",
    "clip",
    "dflash",
    "eagle",
    "eagle3",
    "nomic-bert",
    "reranker",
}


@dataclass(frozen=True)
class DiscoveredModel:
    candidate_id: str
    path: str
    kind: Literal["gguf", "huggingface"]
    backend: Literal["llama_cpp", "vllm"]
    size_bytes: int
    complete: bool
    reason: str | None = None
    quantization: str | None = None
    has_mtp: bool = False
    metadata_readable: bool = True
    architecture: str | None = None
    gguf_file_type: int | None = None
    quantization_version: int | None = None


class ModelScanner:
    def __init__(self, roots: Iterable[Path]) -> None:
        self.roots = tuple(Path(root) for root in roots)

    def scan(
        self, registered_paths: Iterable[Path | str] = ()
    ) -> list[DiscoveredModel]:
        registered = {self._normalize(Path(path)) for path in registered_paths}
        candidates: list[DiscoveredModel] = []
        seen: set[str] = set()
        for root in sorted(self.roots, key=lambda path: str(path)):
            if not root.is_dir():
                continue
            for directory, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = sorted(
                    name
                    for name in dirnames
                    if not (Path(directory) / name).is_symlink()
                )
                filenames.sort()
                current = Path(directory)
                hf_candidate = self._scan_hf(current, filenames)
                if hf_candidate is not None:
                    self._add(hf_candidate, registered, seen, candidates)
                for filename in filenames:
                    if filename.lower().endswith(".gguf"):
                        path = current / filename
                        normalized = self._normalize(path)
                        if normalized in registered or normalized in seen:
                            continue
                        self._add(
                            self._scan_gguf(path),
                            registered,
                            seen,
                            candidates,
                        )
        return sorted(candidates, key=lambda item: self._normalize(Path(item.path)))

    def _add(
        self,
        candidate: DiscoveredModel,
        registered: set[str],
        seen: set[str],
        candidates: list[DiscoveredModel],
    ) -> None:
        if self._is_auxiliary(candidate):
            return
        normalized = self._normalize(Path(candidate.path))
        if normalized in registered or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(candidate)

    @staticmethod
    def _is_auxiliary(candidate: DiscoveredModel) -> bool:
        architecture = (candidate.architecture or "").casefold()
        if architecture in _AUXILIARY_GGUF_ARCHITECTURES or any(
            marker in architecture
            for marker in ("embedding", "rerank", "reward", "bge")
        ):
            return True
        if candidate.kind != "gguf" or candidate.metadata_readable:
            return False
        name = Path(candidate.path).name.casefold()
        return any(
            marker in name
            for marker in ("mmproj", "embed", "rerank", "dflash", "draft", "eagle")
        )

    def _scan_gguf(self, path: Path) -> DiscoveredModel:
        architecture: str | None = None
        file_type: int | None = None
        quantization_version: int | None = None
        readable = True
        reason: str | None = None
        reader: GGUFReader | None = None
        try:
            reader = GGUFReader(path)
            architecture = self._field(reader, "general.architecture", str)
            file_type = self._field(reader, "general.file_type", int)
            quantization_version = self._field(
                reader, "general.quantization_version", int
            )
        except Exception:
            readable = False
            reason = "GGUF metadata is unreadable"
        finally:
            del reader
            gc.collect()
        return DiscoveredModel(
            candidate_id=self._candidate_id(path),
            path=str(path.resolve(strict=False)),
            kind="gguf",
            backend="llama_cpp",
            size_bytes=path.stat().st_size,
            complete=True,
            reason=reason,
            metadata_readable=readable,
            architecture=architecture,
            gguf_file_type=file_type,
            quantization_version=quantization_version,
        )

    def _scan_hf(
        self, directory: Path, filenames: list[str]
    ) -> DiscoveredModel | None:
        names = set(filenames)
        if "config.json" not in names or not self._has_tokenizer(names):
            return None
        index_path = directory / "model.safetensors.index.json"
        full_weights = sorted(
            name
            for name in names
            if name.endswith(".safetensors")
            and "mtp" not in name.lower()
            and not self._is_download_marker(name)
        )
        if not index_path.is_file() and not full_weights:
            return None

        complete = True
        reason: str | None = None
        required_shards: set[str] = set()
        if any(self._is_download_marker(name) for name in names):
            complete = False
            reason = "Download is incomplete"
        elif index_path.is_file():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
                weight_map = index.get("weight_map", {})
                if not isinstance(weight_map, dict):
                    raise ValueError("weight_map must be an object")
                required_shards = {str(value) for value in weight_map.values()}
                missing = sorted(name for name in required_shards if name not in names)
                if missing:
                    complete = False
                    reason = f"Missing safetensors shard: {', '.join(missing)}"
            except (OSError, ValueError, json.JSONDecodeError):
                complete = False
                reason = "Safetensors index is unreadable"

        quantization: str | None = None
        architecture: str | None = None
        try:
            config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
            architecture_value = config.get("model_type")
            architecture = str(architecture_value) if architecture_value else None
            quant_config = config.get("quantization_config")
            if isinstance(quant_config, dict) and quant_config.get("quant_method"):
                quantization = str(quant_config["quant_method"])
        except (OSError, ValueError, json.JSONDecodeError):
            complete = False
            reason = "Model config is unreadable"

        weight_names = {
            name
            for name in names
            if name.endswith(".safetensors") and not self._is_download_marker(name)
        }
        size_bytes = sum(
            (directory / name).stat().st_size
            for name in weight_names
            if (directory / name).is_file()
        )
        return DiscoveredModel(
            candidate_id=self._candidate_id(directory),
            path=str(directory.resolve(strict=False)),
            kind="huggingface",
            backend="vllm",
            size_bytes=size_bytes,
            complete=complete,
            reason=reason,
            quantization=quantization,
            has_mtp=any(
                "mtp" in name.lower() and name.endswith(".safetensors")
                for name in names
            ),
            architecture=architecture,
        )

    @staticmethod
    def _field(reader: GGUFReader, key: str, expected: type) -> str | int | None:
        field = reader.fields.get(key)
        if field is None:
            return None
        value = field.contents()
        return expected(value)

    @staticmethod
    def _has_tokenizer(names: set[str]) -> bool:
        return bool(
            names
            & {
                "tokenizer.json",
                "tokenizer_config.json",
                "tokenizer.model",
                "vocab.json",
            }
        )

    @staticmethod
    def _is_download_marker(name: str) -> bool:
        lowered = name.lower()
        return lowered.endswith((".part", ".crdownload", ".tmp"))

    @classmethod
    def _candidate_id(cls, path: Path) -> str:
        return hashlib.sha256(cls._normalize(path).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _normalize(path: Path) -> str:
        return os.path.normcase(str(path.resolve(strict=False)))
