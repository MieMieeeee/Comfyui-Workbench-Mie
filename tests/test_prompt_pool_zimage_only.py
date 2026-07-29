"""prompt_pool type 只能出现在 zimage 里.

现在仅 zimage (建在) 保留随机提示词功能。其他全部工作流 (包括用户自定义的 Anima_turbo / t2i_krea2 等)
都不能用 prompt_pool, 对应的 type 必须是 text。不要让随便加个随机提示词按钮进来。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFINITIONS = ROOT / "app" / "presets" / "definitions"
def _load_definitions():
    """读取所有 definitions/*.json 文件 (新格式定义)."""
    out = {}
    for p in DEFINITIONS.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            name = data.get("workflow_file", "").replace(".json", "")
            out[name] = data
        except Exception:
            pass
    return out


def test_only_zimage_has_prompt_pool_in_definitions():
    """definitions/ 里只能是 zimage 使用 prompt_pool type (随机提示词专用)."""
    defs = _load_definitions()
    bad = []
    for name, data in defs.items():
        if name == "zimage":
            continue  # zimage 是唯一允许使用 prompt_pool 的建在工作流
        for spec in data.get("user_facing_inputs", []):
            if spec.get("type") == "prompt_pool":
                bad.append((name, spec.get("label", spec.get("node_id"))))
    assert not bad, (
        f"以下定义还在用 prompt_pool (会在表单里出现“随机提示词”按钮), 应改成 text: {bad}"
    )


def test_zimage_still_has_prompt_pool():
    """zimage 作为唯一允许随机提示词的定义, 必须保持 prompt_pool.

    如果这个这个定义被改了, 上面两个检查会错误地“你同时担除了仅余的 prompt_pool”, 这个检查是护栏:
    要么是 zimage 仍然是唯一允许的, 要么是全部去掉随机提示词。"""
    defs = _load_definitions()
    assert "zimage" in defs, "zimage.json 不宔该移除 (是唯一允许 prompt_pool 的定义)"
    zimage_pool = [
        s for s in defs["zimage"].get("user_facing_inputs", [])
        if s.get("type") == "prompt_pool"
    ]
    assert zimage_pool, "zimage.json 里没有 prompt_pool 了, 请确认是否从这个唯一允许里移除了随机提示词"
