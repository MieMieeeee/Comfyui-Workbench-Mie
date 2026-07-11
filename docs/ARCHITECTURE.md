# 系统架构

## 总览

```
+-------------------------+        HTTP         +----------------------------+
|  浏览器 (用户)            | <-----------------> |  Gradio Web (localhost:8199) |
|  - 上传参考图             |                     |  - scail2_app.py (UI)      |
|  - 上传驱动视频            |                     |  - scail2_client.py (HTTP) |
|  - 填提示词               |                     +-------------+--------------+
|  - 点运行                 |                                   |
|  - 看视频                 |                                   | HTTP (8188)
+-------------------------+                                   v
                                                    +-------------------------+
                                                    |  ComfyUI (8188)         |
                                                    |  - /upload/image        |
                                                    |  - /upload/file         |
                                                    |  - /prompt              |
                                                    |  - /history/{id}        |
                                                    |  - /view?filename=...   |
                                                    +-------------+-----------+
                                                                  |
                                                                  v
                                                    +-------------------------+
                                                    |  ComfyUI 文件系统        |
                                                    |  - input/  (上传落盘)    |
                                                    |  - output/SCAIL-2/      |
                                                    |    (生成视频落盘)         |
                                                    |  - mie_nodes_cache/     |
                                                    |    (cache 命中文件)      |
                                                    +-------------------------+
```

**两个进程**：
- `ComfyUI启动器.exe` → 起 ComfyUI 进程，端口 8188（**已存在，不要碰**）
- `python scail2_app.py` → 起 Gradio 进程，端口 8199（**新增**，避开 Gradio 默认 7860 和 ComfyUI 的 8188）

两者不共享内存，只通过 HTTP 和磁盘文件交互。

---

## 文件依赖图

```
scail2_app.py (Gradio UI)
    |
    |  引用
    v
scail2_client.py (ComfyUI HTTP 客户端)
    |
    |  HTTP 调用
    v
ComfyUI HTTP API (8188)
    |
    |  读
    v
sca12_uncached.json (workflow 模板)
```

`scail2_client.py` 是**唯一**跟 ComfyUI HTTP API 直接打交道的模块；UI 层只通过 client 暴露的方法（`upload` / `queue_prompt` / `get_history` / `get_output_url`）调用。这样将来要换 FastAPI 时只动 UI 层，client 复用。

---

## ComfyUI HTTP API 契约

我们用到的 5 个端点（来自 `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\script_examples\basic_api_example.py`）：

### 1. `POST /upload/image` — 上传图片

```bash
curl -X POST http://127.0.0.1:8188/upload/image \
  -F "image=@halfbody.png" \
  -F "type=input" \
  -F "overwrite=true"
```

返回：
```json
{ "name": "halfbody.png", "subfolder": "", "type": "input" }
```

### 2. ~~`POST /upload/file`~~ — 上传任意文件（视频用这个）

> ⚠️ 当前 ComfyUI 0.24 **只有 `POST /upload/image` 一个端点**（`/upload/file` 返
> 405），但它接受任意类型文件（mp4/png/jpg 都行），form 字段名固定是 `image`。
> 视频、图片上传都走 `/upload/image`。详见 `scail2_client.py` 顶部注释 +
> `UPLOAD_ENDPOINT` 常量。下面这段是历史记录，将来若 ComfyUI 加回 `/upload/file`
> 端点可重新启用。

```bash
curl -X POST http://127.0.0.1:8188/upload/file \
  -F "file=@九万字.mp4" \
  -F "type=input" \
  -F "overwrite=true"
```

返回：
```json
{ "name": "九万字.mp4", "subfolder": "", "type": "input" }
```

### 3. `POST /prompt` — 入队一个 workflow

```bash
curl -X POST http://127.0.0.1:8188/prompt \
  -H "Content-Type: application/json" \
  -d @workflow.json
```

请求体：
```json
{
  "prompt": { "30": {"inputs": {"image": "halfbody.png"}, "class_type": "LoadImage"}, ... },
  "client_id": "optional-uuid"
}
```

返回：
```json
{ "prompt_id": "abc-123-def-456", "number": 42 }
```

注意：
- `prompt` 字段里是 **API 格式** workflow（不是 UI 格式），node ID 当 key
- `client_id` 可选，但有它能通过 WebSocket 收实时进度（阶段 4 用）

### 4. `GET /history/{prompt_id}` — 查询执行历史

```bash
curl http://127.0.0.1:8188/history/abc-123-def-456
```

返回（节选）：
```json
{
  "abc-123-def-456": {
    "prompt": [...],
    "outputs": {
      "456": {
        "gifs": [{"filename": "scail-2-loop_00001.gif", "subfolder": "SCAIL-2", "type": "output"}],
        "videos": [{"filename": "scail-2-loop_00001.mp4", "subfolder": "SCAIL-2", "type": "output"}]
      }
    },
    "status": { "status_str": "success", "completed": true, "messages": [...] }
  }
}
```

### 5. `GET /view` — 下载输出媒体

```bash
curl "http://127.0.0.1:8188/view?filename=scail-2-loop_00001.mp4&type=output&subfolder=SCAIL-2" \
  -o scail-2-loop_00001.mp4
```

`gr.Video` 直接吃这个 URL，不需要先下到本地。

---

## workflow JSON 参数替换规则

我们的 SCAIL-2 workflow（API 格式），每次运行需要改的 4 个地方：

| Node ID | class_type | inputs 字段 | 替换值来源 |
|---|---|---|---|
| 30 | LoadImage | `image` | 用户上传的参考图文件名 |
| 360 | CLIPTextEncode | `text` | 用户填的提示词 |
| 369 | VHS_LoadVideo | `video` | 用户上传的驱动视频文件名 |
| 479 | MieLoopStart | `int_range_end` | 用户设的循环段数 slider 值 |

**不要动**的（看似可改但改坏会出事）：
- node 322 (`LoraLoaderModelOnly.strength_model=0.8`)：Lora 强度，0.8 是测过的
- node 330 (`ModelSamplingSD3.shift=5`)：flow matching shift
- node 503 (`ColorTransfer.method="reinhard_lab"`, `source_stats="per_frame"`, `strength=1`)：段间校色
- node 504 (`MieLoopIfIsFirst`)：循环条件分支
- node 505 (`GetImageRangeFromBatch.start_index=5`)：pre-drop 5 帧（pre_drop 版本关键参数）

把"哪些可以改"封装在 `app/presets/sca12_uncached.json` 的**同目录 metadata** 里（`params.json`）：

```json
{
  "user_facing_inputs": [
    {"node_id": "30",  "field": "image",     "label": "参考图",   "type": "file:image"},
    {"node_id": "369", "field": "video",     "label": "驱动视频", "type": "file:video"},
    {"node_id": "360", "field": "text",      "label": "提示词",   "type": "text"},
    {"node_id": "479", "field": "int_range_end", "label": "循环段数", "type": "int", "min": 1, "max": 12, "default": 8}
  ],
  "do_not_modify_warnings": [
    {"node_id": "503", "reason": "段间色阶校色，调错会段间闪"},
    {"node_id": "504", "reason": "循环首段特殊处理"},
    {"node_id": "505", "reason": "pre-drop 5 帧，调错会段头黑屏"}
  ]
}
```

将来扩展更多 workflow 时照这个格式来。

---

## 进度轮询设计

```python
# scail2_client.py
def wait_for_completion(prompt_id, timeout_sec=1800, poll_interval=2):
    """轮询 /history/{id} 直到 completed 或 timeout。
    yield 状态字符串给 Gradio 流式更新。
    """
    start = time.time()
    while time.time() - start < timeout_sec:
        hist = get_history(prompt_id)
        if not hist: 
            yield f"⏳ waiting for {prompt_id[:8]}..."
            time.sleep(poll_interval)
            continue
        status = hist.get("status", {})
        if status.get("completed"):
            if status.get("status_str") == "success":
                yield "✅ done"
            else:
                # 错误信息从 status.messages 数组里抽
                err = _extract_error(status)
                yield f"❌ {err}"
            return
        # 未完成：报告最近执行的节点
        last_node = _last_executed_node(hist)
        elapsed = int(time.time() - start)
        yield f"⏳ {elapsed//60:02d}:{elapsed%60:02d}  running… {last_node}"
        time.sleep(poll_interval)
    yield f"⏰ timeout after {timeout_sec}s"
```

Gradio 端用 `yield` 流式：

```python
def run(...):
    for status_msg in scail2_client.run_workflow(wf, timeout=1800):
        yield status_msg, None  # (status, video_url)
        if status_msg.startswith("✅"):
            # 抓 outputs 拼 video url
            yield "done", video_url
```

---

## 错误处理清单

| 场景 | 用户看到 | 排查路径 |
|---|---|---|
| ComfyUI 没起 | "❌ Cannot connect to ComfyUI at :8188" | 检查 `ComfyUI启动器.exe` |
| 上传文件失败 | "❌ Upload failed: <reason>" | 检查 ComfyUI input 目录权限 |
| workflow JSON 缺字段 | "❌ Workflow missing node 30" | 用 `node -e "JSON.parse"` 验证 |
| 视频太长 (> 200MB) | "❌ Drive video too large (max 200MB)" | 客户端先校验 |
| 参考图超 5MB | "❌ Reference image too large (max 5MB)" | 客户端先校验 |
| ComfyUI 跑超时 (30 min) | "⏰ Timeout, partial output in output/SCAIL-2/" | 看 ComfyUI 控制台 |
| Out of memory | "❌ ComfyUI: CUDA OOM" | 降低段数 / 启用 fp8 |
| Wrong model file | "❌ Missing model: wan2.1_14B_SCAIL_2_fp16.safetensors" | 检查 `E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI\models\` |

---

## 部署

**本地开发**（本项目当前阶段）：
```bash
# 终端 1：ComfyUI（已存在，不动）
"E:\FF\ComfyUI_Mie_2026_V8.0\ComfyUI启动器.exe"

# 终端 2：Gradio Web（待开发）
cd F:\ComfyUIWebToRunWorkflow\app
python scail2_app.py
# 浏览器自动开 http://localhost:8199
```

**局域网共享**（如果要让其他设备访问）：
- Gradio `launch(server_name="0.0.0.0", server_port=8199)`
- Windows 防火墙放行 8199
- 同一 wifi 设备访问 `http://<开发机 IP>:8199`

**公网部署**（如果要给非本地用户用）：
- 先不要考虑；先在本地跑通
- 真要部署，迁 HTMX + FastAPI 然后用 Cloudflare Tunnel / ngrok