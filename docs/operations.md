# 真实部署与运维

## 服务与入口

- 管理台：`http://localhost:9293`
- llama-swap：`http://localhost:9292`
- WSL systemd 用户服务：`llama-swap-console.service`

```bash
systemctl --user status llama-swap-console.service
journalctl --user -u llama-swap-console.service -f
```

## Fable 基线配置

模型 ID：`Qwen3.6-27B-Fable-NVFP4-MTP`

| 设置 | 当前推荐值 |
| --- | --- |
| Context | `8192` |
| `gpu_memory_utilization` | `0.94` |
| `kv_cache_dtype` | `fp8` |
| `max_num_seqs` | `1` |
| `max_num_batched_tokens` | `4096` |
| Chunked prefill | `true` |
| Reasoning parser | `qwen3` |
| Tool parser | `qwen3_coder` |
| Auto tool choice | `true` |
| Safetensors strategy | `prefetch` |
| MTP | disabled |

32GB 显存不足以启用 MTP，因此保持关闭。当前 8K 配置的 KV 容量约为
10922 tokens；不要宣称它可以稳定运行 16K 或 32K 上下文。

## 性能与存储说明

- 位于 `/mnt/d` 的模型文件在 NTFS 上冷启动很慢。需长期保持活跃的模型建议迁移至 WSL ext4。
- 日志显示 RTX 5090 使用 `MarlinNvFp4LinearKernel`，且没有原生 FP4 支持；NVFP4 不保证更快。
- 关闭 thinking 后实测约 `17.5 tok/s`。Cherry Studio 请求必须传入
  `chat_template_kwargs.enable_thinking=false`。
