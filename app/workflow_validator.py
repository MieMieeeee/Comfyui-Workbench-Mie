"""workflow 模板加载后做契约校验 — 阶段 0.3。

校验点：
1. params.json user_facing_inputs 里的 4 个 node 都存在
2. 4 个 field 都在对应 node.inputs 里
3. 至少一个 node 的 class_type 是 VIDEO_OUTPUT_CLASS_TYPES 之一（会产出视频）

不在 app.config 里读 preset_config — 让调用方传进来，避免循环依赖。
"""
from __future__ import annotations

from typing import Any


# 会产出 video/gif 输出的 node class_type
VIDEO_OUTPUT_CLASS_TYPES: frozenset[str] = frozenset({
    "VHS_VideoCombine",
    "SaveGIF",
    "SaveWEBM",
    "SaveVideo",
    "VHS_SaveVideo",
    "CreateVideo",
})

# 会产出 image 输出的 node class_type
IMAGE_OUTPUT_CLASS_TYPES: frozenset[str] = frozenset({
    "SaveImage",
    "PreviewImage",
})

# 复合 type：它们的 field 不直接对应单一 node.inputs 字段，
# 运行时由专门的逻辑映射（如 image_sizes → width+height 多次 patch）。
# validator 对这些 type 只检查节点存在，跳过字段存在性检查。
COMPOUND_INPUT_TYPES: frozenset[str] = frozenset({
    "image_sizes",
})


class WorkflowValidationError(ValueError):
    """workflow 不符合 preset_config 描述的契约。"""


def validate(workflow: dict[str, Any], preset_config: dict[str, Any]) -> None:
    """校验 workflow 是否符合 preset_config 描述的 schema。

    Args:
        workflow: ComfyUI API 格式 workflow（顶层 node_id → node dict）
        preset_config: params.json 里单个 preset 的配置（含 user_facing_inputs）

    Raises:
        WorkflowValidationError: 校验失败时抛出，**不**返回 False
    """
    inputs_spec = preset_config.get("user_facing_inputs")
    if not inputs_spec:
        raise WorkflowValidationError(
            f"preset has no user_facing_inputs (preset_config keys: {list(preset_config)})"
        )

    # 校验 1: 4 个 user_facing 节点都存在
    # 校验 2: 4 个 field 都在对应 node.inputs 里
    for spec in inputs_spec:
        node_id = str(spec["node_id"])
        field = spec["field"]
        label = spec.get("label", field)

        if node_id not in workflow:
            raise WorkflowValidationError(
                f"missing node {node_id} (for {label!r}). "
                f"workflow has {len(workflow)} top-level keys."
            )

        node = workflow[node_id]
        node_inputs = node.get("inputs", {})
        if not isinstance(node_inputs, dict):
            raise WorkflowValidationError(
                f"node {node_id} ({node.get('class_type', '?')}) inputs is not a dict: {type(node_inputs).__name__}"
            )
        # 复合 type 的 field 是逻辑名（如 image_sizes 的 "sizes"），
        # 不直接对应单一 inputs 字段，跳过字段存在性检查。
        if spec.get("type") in COMPOUND_INPUT_TYPES:
            continue
        if field not in node_inputs:
            raise WorkflowValidationError(
                f"node {node_id} ({node.get('class_type', '?')}) missing inputs.{field} "
                f"(for {label!r}). existing inputs: {sorted(node_inputs.keys())}"
            )

    # 校验 3: 至少一个 node 会产出 video/gif 或 image
    video_outputs: list[tuple[str, str]] = []
    image_outputs: list[tuple[str, str]] = []
    for node_id, node in workflow.items():
        ct = node.get("class_type", "")
        if ct in VIDEO_OUTPUT_CLASS_TYPES:
            video_outputs.append((node_id, ct))
        elif ct in IMAGE_OUTPUT_CLASS_TYPES:
            image_outputs.append((node_id, ct))

    if not video_outputs and not image_outputs:
        raise WorkflowValidationError(
            f"no output node found. expected one of video {sorted(VIDEO_OUTPUT_CLASS_TYPES)} "
            f"or image {sorted(IMAGE_OUTPUT_CLASS_TYPES)}. "
            f"workflow class_types: {sorted({n.get('class_type','?') for n in workflow.values()})}"
        )