"""ComfyUI 层次化健康检查。

检查理念：不是简单的"通/不通"，而是分层诊断，每一层失败都给出可操作的建议：
  L0 连通性  — ComfyUI 能否连上？连不上时区分原因（端口没监听/超时/主机不可达）
  L1 系统    — 连上后读 GPU/VRAM/版本
  L2 模型    — workflow 需要的模型文件是否都在 ComfyUI 磁盘上
  L3 节点    — workflow 需要的自定义节点 class_type 是否都已注册

依赖清单在 app/presets/health_requirements.json（数据驱动）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from . import config


# --- 依赖清单加载 ---

_REQUIREMENTS_PATH = config.PRESETS_DIR / "health_requirements.json"


def load_requirements() -> dict:
    """加载模型 + 自定义节点依赖清单。文件缺失返回空清单（不崩）。"""
    if not _REQUIREMENTS_PATH.exists():
        return {"models": [], "custom_nodes": []}
    with _REQUIREMENTS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


# --- HealthReport ---

@dataclass
class ModelReq:
    filename: str
    folder: str
    node: str
    workflows: list[str]


@dataclass
class NodeReq:
    class_type: str
    package: str
    workflows: list[str]


@dataclass
class HealthReport:
    url: str
    # L0 连通性
    reachable: bool = False
    connect_error: str | None = None
    # L1 系统信息
    gpu_name: str | None = None
    vram_total_gb: float | None = None
    vram_free_gb: float | None = None
    comfyui_version: str | None = None
    # L2 模型
    required_models: list[ModelReq] = field(default_factory=list)
    missing_models: list[ModelReq] = field(default_factory=list)
    # L3 节点
    required_nodes: list[NodeReq] = field(default_factory=list)
    missing_nodes: list[NodeReq] = field(default_factory=list)

    @property
    def overall_ok(self) -> bool:
        return self.reachable and not self.missing_models and not self.missing_nodes

    def to_markdown(self) -> str:
        lines = [f"## ComfyUI 健康检查 — `{self.url}`", ""]
        # L0
        if not self.reachable:
            lines.append(f"### ❌ 连通性\n{self.connect_error}")
            lines.append("")
            lines.append(
                "**结论**：❌ 你的 ComfyUI 实例当前不可用。workflow 本身已经作者验证过；"
                "先让 ComfyUI 起来再试。"
            )
            return "\n".join(lines)
        lines.append("### ✅ 连通性")
        # L1
        sys_parts = []
        if self.comfyui_version:
            sys_parts.append(f"ComfyUI v{self.comfyui_version}")
        if self.gpu_name:
            sys_parts.append(f"GPU: {self.gpu_name}")
            vram = []
            if self.vram_total_gb is not None:
                vram.append(f"VRAM {self.vram_total_gb:.1f}GB")
            if self.vram_free_gb is not None:
                vram.append(f"可用 {self.vram_free_gb:.1f}GB")
            if vram:
                sys_parts.append(f"({', '.join(vram)})")
        lines.append("　" + "，".join(sys_parts) if sys_parts else "　已连接")
        lines.append("")
        # L2 模型
        total_m = len(self.required_models)
        ok_m = total_m - len(self.missing_models)
        mark_m = "✅" if not self.missing_models else "❌"
        lines.append(f"### {mark_m} 模型文件 ({ok_m}/{total_m})")
        if self.missing_models:
            lines.append("缺失：")
            for m in self.missing_models:
                lines.append(f"　- `{m.filename}` ({m.folder})")
        else:
            lines.append("　全部就绪")
        lines.append("")
        # L3 节点
        total_n = len(self.required_nodes)
        ok_n = total_n - len(self.missing_nodes)
        mark_n = "✅" if not self.missing_nodes else "❌"
        lines.append(f"### {mark_n} 自定义节点 ({ok_n}/{total_n})")
        if self.missing_nodes:
            # 按包聚合
            by_pkg: dict[str, list[str]] = {}
            for n in self.missing_nodes:
                by_pkg.setdefault(n.package, []).append(n.class_type)
            for pkg, classes in by_pkg.items():
                lines.append(f"　**{pkg}** 缺 {len(classes)} 个节点：{', '.join(classes[:5])}{'…' if len(classes) > 5 else ''}")
            lines.append(f"　→ 请在 ComfyUI Manager 安装：{', '.join(by_pkg.keys())}")
        else:
            lines.append("　全部就绪")
        lines.append("")
        # 结论
        lines.append("---")
        if self.overall_ok:
            lines.append("**结论**：✅ 所有工作流可运行。")
        else:
            issues = []
            if self.missing_models:
                issues.append(f"缺 {len(self.missing_models)} 个模型")
            if self.missing_nodes:
                issues.append(f"缺 {len(self.missing_nodes)} 个自定义节点")
            lines.append(
                f"**结论**：❌ 你的 ComfyUI 实例{'，'.join(issues)}。workflow 本身已经验证；请补齐 ComfyUI 实例侧的依赖。"
            )
        return "\n".join(lines)


# --- 主检查函数 ---

def check_health(url: str | None = None, timeout: int = 8) -> HealthReport:
    """执行完整多层健康检查，返回 HealthReport。"""
    target = (url or config.COMFY_BASE_URL).strip().rstrip("/")
    report = HealthReport(url=target)
    reqs = load_requirements()
    report.required_models = [ModelReq(m["filename"], m["folder"], m["node"], m.get("workflows", []))
                              for m in reqs.get("models", [])]
    report.required_nodes = [NodeReq(n["class_type"], n["package"], n.get("workflows", []))
                             for n in reqs.get("custom_nodes", [])]

    # L0 + L1: /system_stats（用模块级 requests，可被测试 patch）
    try:
        resp = requests.get(f"{target}/system_stats", timeout=timeout)
        if resp.status_code != 200:
            report.connect_error = (
                f"ComfyUI 返回 HTTP {resp.status_code}。`{target}` 可能不是 ComfyUI 实例。"
            )
            return report
        data = resp.json()
    except requests.ConnectionError as e:
        report.connect_error = _diagnose_connection_error(target, e)
        return report
    except requests.Timeout:
        report.connect_error = (
            f"⏰ 连接超时（{timeout}s）。地址 `{target}` 可能错误，或被防火墙拦截。"
        )
        return report
    except Exception as e:
        report.connect_error = f"{type(e).__name__}: {e}"
        return report

    report.reachable = True
    # L1 解析系统信息
    system = data.get("system", {})
    report.comfyui_version = system.get("comfyui_version")
    devices = data.get("devices", [])
    if devices:
        d0 = devices[0]
        report.gpu_name = d0.get("name")
        if d0.get("vram_total") is not None:
            report.vram_total_gb = d0["vram_total"] / (1024 ** 3)
        if d0.get("vram_free") is not None:
            report.vram_free_gb = d0["vram_free"] / (1024 ** 3)

    # L2 + L3: /object_info（一次请求拿模型列表 + class_type keys）
    try:
        oi_resp = requests.get(f"{target}/object_info", timeout=timeout)
        if oi_resp.status_code == 200:
            object_info = oi_resp.json()
            available_classes = set(object_info.keys())
            # L3: 检查自定义节点 class_type
            for nreq in report.required_nodes:
                if nreq.class_type not in available_classes:
                    report.missing_nodes.append(nreq)
            # L2: 检查模型文件
            for mreq in report.required_models:
                available_files = _get_available_models(object_info, mreq.node, mreq.folder)
                if mreq.filename not in available_files:
                    report.missing_models.append(mreq)
    except Exception:
        pass  # /object_info 失败不致命（L0/L1 已证明连通），报告里 L2/L3 留空

    return report


def _get_available_models(object_info: dict, node_class: str, folder: str) -> set[str]:
    """从 /object_info 提取某 loader 节点可用的模型文件名列表。

    loader 节点的 input.required.<field>[0] 是当前磁盘上的模型文件名列表。
    """
    node = object_info.get(node_class)
    if not node:
        return set()
    required = node.get("input", {}).get("required", {})
    # loader 节点的字段名固定（unet_name/vae_name/clip_name/ckpt_name/lora_name）
    for field in ("unet_name", "vae_name", "clip_name", "ckpt_name", "lora_name"):
        if field in required:
            val = required[field]
            if isinstance(val, list) and val and isinstance(val[0], list):
                return set(val[0])
    return set()


def _diagnose_connection_error(target: str, exc: Exception) -> str:
    """把连接异常翻译成可操作的诊断建议。"""
    msg = str(exc).lower()
    parsed = urlparse(target)
    host = parsed.hostname or target
    port = parsed.port or 8188
    # 连接被拒 = 端口没有进程监听
    if "refused" in msg or "errno 111" in msg or "winerror 10061" in msg:
        return (
            f"❌ 端口 {port} 没有进程监听。\n"
            f"　ComfyUI 启动器可能只打开了界面，但后端没真正启动。\n"
            f"　→ 去 ComfyUI 启动器点「启动」按钮，等控制台显示 `To see the GUI go to: http://127.0.0.1:{port}` 后再试。"
        )
    # 超时
    if "timeout" in msg or "timed out" in msg:
        return f"⏰ 连接超时。地址 `{target}` 可能错误或被防火墙拦截。"
    # DNS 解析失败
    if "resolve" in msg or "name or service" in msg or "getaddrinfo" in msg:
        return f"❌ 无法解析主机 `{host}`。请检查地址拼写。"
    # 主机不可达
    if "unreachable" in msg or "no route" in msg:
        return f"❌ 主机 `{host}` 不可达。请检查网络/地址。"
    return f"❌ 无法连接 `{target}`：{exc}"
