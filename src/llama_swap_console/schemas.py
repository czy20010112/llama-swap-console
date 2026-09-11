from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Backend = Literal["llama_cpp", "vllm", "sglang"]


class SpeculativeSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: str
    model: str | None = None
    num_speculative_tokens: int = Field(default=0, ge=0, le=16)


class LlamaCppSettings(BaseModel):
    n_gpu_layers: int | None = None
    flash_attn: Literal["auto", "on", "off"] | None = None
    cache_type_k: str | None = None
    cache_type_v: str | None = None
    jinja: bool = False
    mmproj: str | None = None
    model_draft: str | None = None
    spec_type: str | None = None
    spec_draft_n_max: int | None = Field(default=None, ge=0, le=64)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, ge=0, le=1)
    top_k: int | None = Field(default=None, ge=0)
    min_p: float | None = Field(default=None, ge=0, le=1)
    repeat_penalty: float | None = Field(default=None, ge=0)


class VllmSettings(BaseModel):
    gpu_memory_utilization: float | None = Field(default=None, ge=0.1, le=0.99)
    kv_cache_dtype: str | None = None
    dtype: str | None = None
    quantization: str | None = None
    max_num_seqs: int | None = Field(default=None, ge=1, le=256)
    max_num_batched_tokens: int | None = Field(default=None, ge=1)
    enable_chunked_prefill: bool = False
    trust_remote_code: bool = False
    reasoning_parser: str | None = None
    enable_auto_tool_choice: bool = False
    tool_call_parser: str | None = None
    speculative: SpeculativeSettings | None = None
    safetensors_load_strategy: str | None = None


class SglangSettings(BaseModel):
    mem_fraction_static: float | None = Field(default=None, ge=0.1, le=0.99)
    kv_cache_dtype: str | None = None
    quantization: str | None = None
    tp_size: int | None = Field(default=None, ge=1, le=64)
    max_running_requests: int | None = Field(default=None, ge=1, le=256)
    chunked_prefill_size: int | None = Field(default=None, ge=1)
    mamba_ssm_dtype: str | None = None
    speculative_algorithm: str | None = None
    speculative_draft_model_path: str | None = None
    speculative_num_steps: int | None = Field(default=None, ge=1, le=16)
    speculative_eagle_topk: int | None = Field(default=None, ge=1, le=64)
    speculative_num_draft_tokens: int | None = Field(default=None, ge=0, le=64)
    enable_metrics: bool = False


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Backend
    launch_tokens: tuple[str, ...]
    model_path: str
    model_argument: Literal["flag", "positional"] = "flag"
    context_length: int = Field(default=4096, ge=512, le=1048576)
    port_token: str = "${PORT}"
    llama_cpp: LlamaCppSettings | None = None
    vllm: VllmSettings | None = None
    sglang: SglangSettings | None = None
    unknown_tokens: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_backend_settings(self) -> "ModelSettings":
        if self.backend == "llama_cpp" and (
            self.llama_cpp is None or self.vllm is not None or self.sglang is not None
        ):
            raise ValueError("llama_cpp backend requires only llama_cpp settings")
        if self.backend == "vllm" and (
            self.vllm is None or self.llama_cpp is not None or self.sglang is not None
        ):
            raise ValueError("vllm backend requires only vllm settings")
        if self.backend == "sglang" and (
            self.sglang is None or self.llama_cpp is not None or self.vllm is not None
        ):
            raise ValueError("sglang backend requires only sglang settings")
        if not self.launch_tokens:
            raise ValueError("launch_tokens cannot be empty")
        return self


class ModelUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    settings: ModelSettings
    reload: bool = False


class ModelRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    settings: ModelSettings
