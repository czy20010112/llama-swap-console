from __future__ import annotations

import json
from pathlib import Path

import gguf

from llama_swap_console.model_scanner import ModelScanner


def write_gguf(path: Path, architecture: str = "qwen35") -> None:
    writer = gguf.GGUFWriter(path, architecture)
    writer.add_file_type(15)
    writer.add_quantization_version(2)
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()


def write_hf_config(
    path: Path,
    *,
    quant_method: str = "compressed-tensors",
    model_type: str = "qwen3_5",
) -> None:
    path.mkdir(parents=True)
    (path / "config.json").write_text(
        json.dumps({"model_type": model_type, "quantization_config": {"quant_method": quant_method}}),
        encoding="utf-8",
    )
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")


def test_scans_real_gguf_metadata_and_corrupt_gguf(tmp_path: Path) -> None:
    valid = tmp_path / "Qwen-Q4_K_M.gguf"
    corrupt = tmp_path / "broken.gguf"
    write_gguf(valid)
    corrupt.write_bytes(b"not a gguf")

    candidates = ModelScanner((tmp_path,)).scan()
    by_name = {Path(candidate.path).name: candidate for candidate in candidates}

    assert by_name[valid.name].kind == "gguf"
    assert by_name[valid.name].backend == "llama_cpp"
    assert by_name[valid.name].architecture == "qwen35"
    assert by_name[valid.name].gguf_file_type == 15
    assert by_name[valid.name].quantization_version == 2
    assert by_name[valid.name].metadata_readable is True
    assert by_name[corrupt.name].complete is True
    assert by_name[corrupt.name].metadata_readable is False
    assert by_name[corrupt.name].reason == "GGUF metadata is unreadable"


def test_scans_complete_hf_model_and_mtp_capability(tmp_path: Path) -> None:
    model = tmp_path / "Fable-NVFP4A16"
    write_hf_config(model)
    (model / "model.safetensors").write_bytes(b"weights")
    (model / "model-mtp-bf16.safetensors").write_bytes(b"mtp")

    candidate = ModelScanner((tmp_path,)).scan()[0]

    assert candidate.kind == "huggingface"
    assert candidate.backend == "vllm"
    assert candidate.complete is True
    assert candidate.quantization == "compressed-tensors"
    assert candidate.has_mtp is True
    assert candidate.size_bytes == len(b"weights") + len(b"mtp")


def test_indexed_hf_model_reports_missing_shard(tmp_path: Path) -> None:
    model = tmp_path / "indexed"
    write_hf_config(model)
    (model / "model-00001-of-00002.safetensors").write_bytes(b"one")
    (model / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                "weight_map": {
                    "a": "model-00001-of-00002.safetensors",
                    "b": "model-00002-of-00002.safetensors",
                }
            }
        ),
        encoding="utf-8",
    )

    candidate = ModelScanner((tmp_path,)).scan()[0]

    assert candidate.complete is False
    assert "model-00002-of-00002.safetensors" in candidate.reason


def test_download_markers_make_hf_candidate_incomplete(tmp_path: Path) -> None:
    model = tmp_path / "downloading"
    write_hf_config(model)
    (model / "model.safetensors").write_bytes(b"weights")
    (model / "model.safetensors.part").write_bytes(b"partial")

    candidate = ModelScanner((tmp_path,)).scan()[0]

    assert candidate.complete is False
    assert candidate.reason == "Download is incomplete"


def test_missing_tokenizer_or_weights_is_not_a_hf_candidate(tmp_path: Path) -> None:
    config_only = tmp_path / "config-only"
    config_only.mkdir()
    (config_only / "config.json").write_text("{}", encoding="utf-8")
    unrelated = tmp_path / "notes"
    unrelated.mkdir()
    (unrelated / "tokenizer.json").write_text("{}", encoding="utf-8")

    assert ModelScanner((tmp_path,)).scan() == []


def test_registered_paths_are_deduplicated_and_candidate_ids_are_stable(tmp_path: Path) -> None:
    first = tmp_path / "first.gguf"
    second = tmp_path / "second.gguf"
    write_gguf(first)
    write_gguf(second)
    scanner = ModelScanner((tmp_path,))

    all_candidates = scanner.scan()
    filtered = scanner.scan(registered_paths={first.resolve()})
    repeated = scanner.scan()

    assert [Path(item.path).name for item in filtered] == ["second.gguf"]
    assert [item.candidate_id for item in all_candidates] == [
        item.candidate_id for item in repeated
    ]
    assert all(len(item.candidate_id) == 16 for item in all_candidates)


def test_scanner_does_not_follow_directory_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    write_gguf(outside / "outside.gguf")
    root = tmp_path / "root"
    root.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return

    assert ModelScanner((root,)).scan() == []


def test_scanner_excludes_auxiliary_gguf_models(tmp_path: Path) -> None:
    write_gguf(tmp_path / "mmproj-kquant.gguf", "clip")
    write_gguf(tmp_path / "nomic-embed-text.gguf", "nomic-bert")
    write_gguf(tmp_path / "dflash-kquant.gguf", "dflash")
    write_gguf(tmp_path / "chat-Q4_K_M.gguf", "qwen35")

    candidates = ModelScanner((tmp_path,)).scan()

    assert [Path(candidate.path).name for candidate in candidates] == [
        "chat-Q4_K_M.gguf"
    ]


def test_scanner_excludes_embedding_huggingface_models(tmp_path: Path) -> None:
    embedding = tmp_path / "Qwen3-Embedding"
    write_hf_config(embedding, model_type="qwen3_embedding")
    (embedding / "model.safetensors").write_bytes(b"weights")

    assert ModelScanner((tmp_path,)).scan() == []
