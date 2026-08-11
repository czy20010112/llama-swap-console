from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from llama_swap_console.schemas import (
    LlamaCppSettings,
    ModelSettings,
    SpeculativeSettings,
    VllmSettings,
)


class CommandDecodeError(Exception):
    """A command cannot be represented by the structured editor."""


class CommandRoundTripError(Exception):
    """Encoding a decoded command would lose structured information."""


@dataclass(frozen=True)
class FlagSpec:
    field: str
    kind: Literal["str", "int", "float", "bool", "json"] = "str"


COMMON_FLAGS = {
    "--port": FlagSpec("port_token"),
}

LLAMA_FLAGS = {
    "-m": FlagSpec("model_path"),
    "--model": FlagSpec("model_path"),
    "-c": FlagSpec("context_length", "int"),
    "--ctx-size": FlagSpec("context_length", "int"),
    "-ngl": FlagSpec("n_gpu_layers", "int"),
    "--n-gpu-layers": FlagSpec("n_gpu_layers", "int"),
    "--flash-attn": FlagSpec("flash_attn"),
    "--cache-type-k": FlagSpec("cache_type_k"),
    "--cache-type-v": FlagSpec("cache_type_v"),
    "--jinja": FlagSpec("jinja", "bool"),
    "--mmproj": FlagSpec("mmproj"),
    "--model-draft": FlagSpec("model_draft"),
    "--spec-type": FlagSpec("spec_type"),
    "--spec-draft-n-max": FlagSpec("spec_draft_n_max", "int"),
    "--temp": FlagSpec("temperature", "float"),
    "--top-p": FlagSpec("top_p", "float"),
    "--top-k": FlagSpec("top_k", "int"),
    "--min-p": FlagSpec("min_p", "float"),
    "--repeat-penalty": FlagSpec("repeat_penalty", "float"),
}

VLLM_FLAGS = {
    "--model": FlagSpec("model_path"),
    "--max-model-len": FlagSpec("context_length", "int"),
    "--gpu-memory-utilization": FlagSpec("gpu_memory_utilization", "float"),
    "--kv-cache-dtype": FlagSpec("kv_cache_dtype"),
    "--dtype": FlagSpec("dtype"),
    "--quantization": FlagSpec("quantization"),
    "--max-num-seqs": FlagSpec("max_num_seqs", "int"),
    "--max-num-batched-tokens": FlagSpec("max_num_batched_tokens", "int"),
    "--enable-chunked-prefill": FlagSpec("enable_chunked_prefill", "bool"),
    "--trust-remote-code": FlagSpec("trust_remote_code", "bool"),
    "--reasoning-parser": FlagSpec("reasoning_parser"),
    "--enable-auto-tool-choice": FlagSpec("enable_auto_tool_choice", "bool"),
    "--tool-call-parser": FlagSpec("tool_call_parser"),
    "--speculative-config": FlagSpec("speculative", "json"),
    "--safetensors-load-strategy": FlagSpec("safetensors_load_strategy"),
}

_TEMPLATE_TOKEN = re.compile(r"^\$\{[A-Z][A-Z0-9_]*\}$")


class CommandCodec:
    def decode(self, command: str) -> ModelSettings:
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError as error:
            raise CommandDecodeError(f"Unable to parse command: {error}") from error
        if not tokens:
            raise CommandDecodeError("Command is empty")

        backend = self._detect_backend(tokens)
        backend_flags = VLLM_FLAGS if backend == "vllm" else LLAMA_FLAGS
        all_flags = {**COMMON_FLAGS, **backend_flags}
        positional_index = self._vllm_positional_model(tokens) if backend == "vllm" else None
        if positional_index is not None:
            launch_tokens = tuple(tokens[:positional_index])
            first_flag = positional_index + 1
            common: dict[str, Any] = {
                "model_path": tokens[positional_index],
                "model_argument": "positional",
                "context_length": 4096,
                "port_token": "${PORT}",
            }
        else:
            first_flag = self._first_known_flag(tokens, all_flags)
            if first_flag is None:
                raise CommandDecodeError("Command has no recognized model flag")
            launch_tokens = tuple(tokens[:first_flag])
            common = {
                "model_argument": "flag",
                "context_length": 4096,
                "port_token": "${PORT}",
            }
        specific: dict[str, Any] = {}
        unknown: list[str] = []
        index = first_flag
        while index < len(tokens):
            raw_flag, inline_value = self._split_flag(tokens[index])
            spec = all_flags.get(raw_flag)
            if spec is None:
                unknown.append(tokens[index])
                index += 1
                continue
            if spec.kind == "bool":
                value: Any = True
                index += 1
            else:
                if inline_value is not None:
                    raw_value = inline_value
                    index += 1
                else:
                    if index + 1 >= len(tokens):
                        raise CommandDecodeError(f"Missing value for {raw_flag}")
                    raw_value = tokens[index + 1]
                    index += 2
                value = self._convert_value(raw_flag, raw_value, spec.kind)
            target = common if spec.field in {"model_path", "context_length", "port_token"} else specific
            target[spec.field] = value

        if not common.get("model_path"):
            raise CommandDecodeError("Command does not specify a model path")
        try:
            if backend == "vllm":
                specific["speculative"] = self._speculative(specific.get("speculative"))
                return ModelSettings(
                    backend=backend,
                    launch_tokens=launch_tokens,
                    unknown_tokens=tuple(unknown),
                    vllm=VllmSettings(**specific),
                    **common,
                )
            return ModelSettings(
                backend=backend,
                launch_tokens=launch_tokens,
                unknown_tokens=tuple(unknown),
                llama_cpp=LlamaCppSettings(**specific),
                **common,
            )
        except ValidationError as error:
            raise CommandDecodeError(f"Command validation failed: {error}") from error

    def encode(self, settings: ModelSettings) -> str:
        tokens = list(settings.launch_tokens)
        if settings.backend == "llama_cpp":
            assert settings.llama_cpp is not None
            values = settings.llama_cpp
            tokens.extend(["--model", settings.model_path, "--port", settings.port_token])
            self._append(tokens, "--ctx-size", settings.context_length)
            for flag, field in (
                ("--n-gpu-layers", "n_gpu_layers"),
                ("--flash-attn", "flash_attn"),
                ("--cache-type-k", "cache_type_k"),
                ("--cache-type-v", "cache_type_v"),
                ("--jinja", "jinja"),
                ("--mmproj", "mmproj"),
                ("--model-draft", "model_draft"),
                ("--spec-type", "spec_type"),
                ("--spec-draft-n-max", "spec_draft_n_max"),
                ("--temp", "temperature"),
                ("--top-p", "top_p"),
                ("--top-k", "top_k"),
                ("--min-p", "min_p"),
                ("--repeat-penalty", "repeat_penalty"),
            ):
                self._append(tokens, flag, getattr(values, field))
        else:
            assert settings.vllm is not None
            values = settings.vllm
            if settings.model_argument == "positional":
                tokens.append(settings.model_path)
            else:
                tokens.extend(["--model", settings.model_path])
            tokens.extend(["--port", settings.port_token])
            self._append(tokens, "--max-model-len", settings.context_length)
            for flag, field in (
                ("--gpu-memory-utilization", "gpu_memory_utilization"),
                ("--kv-cache-dtype", "kv_cache_dtype"),
                ("--dtype", "dtype"),
                ("--quantization", "quantization"),
                ("--max-num-seqs", "max_num_seqs"),
                ("--max-num-batched-tokens", "max_num_batched_tokens"),
                ("--enable-chunked-prefill", "enable_chunked_prefill"),
                ("--trust-remote-code", "trust_remote_code"),
                ("--reasoning-parser", "reasoning_parser"),
                ("--enable-auto-tool-choice", "enable_auto_tool_choice"),
                ("--tool-call-parser", "tool_call_parser"),
                ("--safetensors-load-strategy", "safetensors_load_strategy"),
            ):
                self._append(tokens, flag, getattr(values, field))
            if values.speculative is not None:
                payload = values.speculative.model_dump(exclude_none=True)
                self._append(
                    tokens,
                    "--speculative-config",
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
                )
        tokens.extend(settings.unknown_tokens)
        return " ".join(self._quote(token) for token in tokens)

    @staticmethod
    def _detect_backend(tokens: list[str]) -> Literal["llama_cpp", "vllm"]:
        if any("vllm" in token.lower() for token in tokens):
            return "vllm"
        if any(CommandCodec._split_flag(token)[0] in VLLM_FLAGS and CommandCodec._split_flag(token)[0] not in LLAMA_FLAGS for token in tokens):
            return "vllm"
        return "llama_cpp"

    @staticmethod
    def _first_known_flag(tokens: list[str], flags: dict[str, FlagSpec]) -> int | None:
        for index, token in enumerate(tokens):
            if CommandCodec._split_flag(token)[0] in flags:
                return index
        return None

    @staticmethod
    def _vllm_positional_model(tokens: list[str]) -> int | None:
        for index, token in enumerate(tokens[:-1]):
            if token == "serve" and not tokens[index + 1].startswith("-"):
                return index + 1
        return None

    @staticmethod
    def _split_flag(token: str) -> tuple[str, str | None]:
        if token.startswith("--") and "=" in token:
            return tuple(token.split("=", 1))  # type: ignore[return-value]
        return token, None

    @staticmethod
    def _convert_value(flag: str, raw: str, kind: str) -> Any:
        try:
            if kind == "int":
                return int(raw)
            if kind == "float":
                return float(raw)
            if kind == "json":
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError("JSON value must be an object")
                return value
            return raw
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise CommandDecodeError(f"Invalid value for {flag}: {error}") from error

    @staticmethod
    def _speculative(value: Any) -> SpeculativeSettings | None:
        if value is None:
            return None
        try:
            return SpeculativeSettings(**value)
        except ValidationError as error:
            raise CommandDecodeError(f"Invalid speculative configuration: {error}") from error

    @staticmethod
    def _append(tokens: list[str], flag: str, value: Any) -> None:
        if value is None or value is False:
            return
        tokens.append(flag)
        if value is not True:
            tokens.append(str(value))

    @staticmethod
    def _quote(token: str) -> str:
        return token if _TEMPLATE_TOKEN.fullmatch(token) else shlex.quote(token)


def assert_stable(codec: CommandCodec, command: str) -> ModelSettings:
    first = codec.decode(command)
    second = codec.decode(codec.encode(first))
    if first != second:
        raise CommandRoundTripError("Command cannot be represented without loss")
    return first
