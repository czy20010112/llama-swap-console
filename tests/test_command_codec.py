from __future__ import annotations

import pytest

from llama_swap_console.command_codec import (
    CommandCodec,
    CommandDecodeError,
    CommandRoundTripError,
    assert_stable,
)
from llama_swap_console.schemas import LlamaCppSettings, ModelSettings


LLAMA_COMMAND = r'''"/opt/llama cpp/llama-server" --model "/mnt/d/AI/models/a model.gguf" --port ${PORT} --ctx-size 32768 --n-gpu-layers 99 --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 --jinja --temp 0.8 --top-p 0.95 --vendor-extra "two words"'''

VLLM_COMMAND = r'''/home/czy098/vllm/bin/python -m vllm.entrypoints.openai.api_server --model "/mnt/d/AI/models/Fable Fusion" --port ${PORT} --max-model-len 32768 --gpu-memory-utilization 0.85 --max-num-seqs 1 --enable-chunked-prefill --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder --safetensors-load-strategy prefetch --speculative-config '{"method":"mtp","num_speculative_tokens":5}' --unknown-vllm value'''

SGLANG_COMMAND = r'''env CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1,0 /home/czy098/.venvs/sglang/bin/sglang serve --model-path /mnt/d/AI/models/Qwen3.8-27B-NVFP4 --served-model-name ${MODEL_ID} --host 127.0.0.1 --port ${PORT} --tp-size 2 --context-length 65536 --mem-fraction-static 0.92 --quantization compressed-tensors --kv-cache-dtype fp8_e4m3 --chunked-prefill-size 8192 --mamba-ssm-dtype bfloat16 --max-running-requests 1 --speculative-algorithm NEXTN --speculative-draft-model-path /mnt/d/AI/models/Qwen3.8-27B-NVFP4 --speculative-num-steps 3 --speculative-eagle-topk 1 --speculative-num-draft-tokens 4 --enable-metrics'''


def test_llama_cpp_command_round_trips_known_and_unknown_tokens() -> None:
    codec = CommandCodec()

    decoded = codec.decode(LLAMA_COMMAND)

    assert decoded.backend == "llama_cpp"
    assert decoded.launch_tokens == ("/opt/llama cpp/llama-server",)
    assert decoded.model_path == "/mnt/d/AI/models/a model.gguf"
    assert decoded.context_length == 32768
    assert decoded.llama_cpp is not None
    assert decoded.llama_cpp.n_gpu_layers == 99
    assert decoded.llama_cpp.flash_attn == "on"
    assert decoded.llama_cpp.jinja is True
    assert decoded.llama_cpp.temperature == 0.8
    assert decoded.port_token == "${PORT}"
    assert decoded.unknown_tokens == ("--vendor-extra", "two words")
    assert codec.decode(codec.encode(decoded)) == decoded


def test_vllm_command_round_trips_mtp_and_python_module_prefix() -> None:
    codec = CommandCodec()

    decoded = codec.decode(VLLM_COMMAND)

    assert decoded.backend == "vllm"
    assert decoded.launch_tokens == (
        "/home/czy098/vllm/bin/python",
        "-m",
        "vllm.entrypoints.openai.api_server",
    )
    assert decoded.vllm is not None
    assert decoded.vllm.gpu_memory_utilization == 0.85
    assert decoded.vllm.enable_chunked_prefill is True
    assert decoded.vllm.speculative is not None
    assert decoded.vllm.speculative.method == "mtp"
    assert decoded.vllm.speculative.num_speculative_tokens == 5
    assert decoded.unknown_tokens == ("--unknown-vllm", "value")
    assert codec.decode(codec.encode(decoded)) == decoded


def test_sglang_command_round_trips_context_concurrency_kv_and_mtp() -> None:
    codec = CommandCodec()

    decoded = codec.decode(SGLANG_COMMAND)

    assert decoded.backend == "sglang"
    assert decoded.launch_tokens == (
        "env",
        "CUDA_DEVICE_ORDER=PCI_BUS_ID",
        "CUDA_VISIBLE_DEVICES=1,0",
        "/home/czy098/.venvs/sglang/bin/sglang",
        "serve",
    )
    assert decoded.model_path == "/mnt/d/AI/models/Qwen3.8-27B-NVFP4"
    assert decoded.context_length == 65536
    assert decoded.sglang is not None
    assert decoded.sglang.tp_size == 2
    assert decoded.sglang.mem_fraction_static == 0.92
    assert decoded.sglang.kv_cache_dtype == "fp8_e4m3"
    assert decoded.sglang.max_running_requests == 1
    assert decoded.sglang.speculative_algorithm == "NEXTN"
    assert decoded.sglang.speculative_num_steps == 3
    assert decoded.sglang.speculative_num_draft_tokens == 4
    assert decoded.sglang.enable_metrics is True
    assert decoded.unknown_tokens == (
        "--served-model-name",
        "${MODEL_ID}",
        "--host",
        "127.0.0.1",
    )
    assert codec.decode(codec.encode(decoded)) == decoded


@pytest.mark.parametrize(
    "command",
    [
        "/opt/llama-server --ctx-size 4096 --port ${PORT}",
        "/opt/vllm --model /models/a --speculative-config not-json",
        "/opt/vllm --model /models/a --speculative-config '[]'",
    ],
)
def test_decode_rejects_missing_model_and_invalid_speculative_json(command: str) -> None:
    with pytest.raises(CommandDecodeError):
        CommandCodec().decode(command)


def test_schema_rejects_out_of_range_context() -> None:
    command = "/opt/llama-server --model /models/a.gguf --ctx-size 100 --port ${PORT}"

    with pytest.raises(CommandDecodeError, match="validation"):
        CommandCodec().decode(command)


def test_assert_stable_rejects_a_codec_that_loses_information() -> None:
    class LossyCodec(CommandCodec):
        def encode(self, settings):  # type: ignore[no-untyped-def]
            return super().encode(settings).replace("--vendor-extra 'two words'", "")

    with pytest.raises(CommandRoundTripError):
        assert_stable(LossyCodec(), LLAMA_COMMAND)


def test_template_tokens_are_not_shell_single_quoted() -> None:
    encoded = CommandCodec().encode(CommandCodec().decode(VLLM_COMMAND))

    assert "--port ${PORT}" in encoded
    assert "'${PORT}'" not in encoded


def test_long_flags_accept_equals_form() -> None:
    command = (
        "/opt/llama-server --model=/models/a.gguf --ctx-size=8192 "
        "--flash-attn=auto --port=${PORT}"
    )

    decoded = CommandCodec().decode(command)

    assert decoded.model_path == "/models/a.gguf"
    assert decoded.context_length == 8192
    assert decoded.llama_cpp is not None
    assert decoded.llama_cpp.flash_attn == "auto"
    assert CommandCodec().decode(CommandCodec().encode(decoded)) == decoded


def test_vllm_serve_positional_model_path_round_trips() -> None:
    command = (
        "/home/czy098/.venvs/vllm/bin/vllm serve "
        "/mnt/d/AI/models/Qwen3.6-27B-NVFP4 "
        "--served-model-name ${MODEL_ID} --host 127.0.0.1 --port ${PORT} "
        "--quantization modelopt --max-model-len 65536 "
        "--speculative-config '{\"method\":\"mtp\",\"num_speculative_tokens\":3}'"
    )

    decoded = CommandCodec().decode(command)

    assert decoded.backend == "vllm"
    assert decoded.launch_tokens == (
        "/home/czy098/.venvs/vllm/bin/vllm",
        "serve",
    )
    assert decoded.model_argument == "positional"
    assert decoded.model_path == "/mnt/d/AI/models/Qwen3.6-27B-NVFP4"
    assert decoded.unknown_tokens == (
        "--served-model-name",
        "${MODEL_ID}",
        "--host",
        "127.0.0.1",
    )
    assert CommandCodec().decode(CommandCodec().encode(decoded)) == decoded


def test_encode_omits_blank_optional_llama_cpp_values() -> None:
    settings = ModelSettings(
        backend="llama_cpp",
        launch_tokens=("/opt/llama-server",),
        model_path="/models/chat.gguf",
        llama_cpp=LlamaCppSettings(
            mmproj="",
            model_draft="   ",
            spec_type="",
        ),
    )

    encoded = CommandCodec().encode(settings)

    assert "--mmproj" not in encoded
    assert "--model-draft" not in encoded
    assert "--spec-type" not in encoded
