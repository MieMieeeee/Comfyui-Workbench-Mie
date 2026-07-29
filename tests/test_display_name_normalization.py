"""工作流显示规范化契约 (review 2026-07-14).

锁住 9 个 preset 在左侧 Radio + 表单顶部的显示规范:
  - display_name 格式: 「中文任务类型 (模型名)」, 括号内只放模型名
  - display_name 全局唯一 (ltx t2v / i2v 不再重名)
  - order 按类目分段: image=10+, video=100+, audio=200+
  - 所有 video preset 显式声明 output_kind (不再依赖 category 兜底)
  - description 不含 node ID / 节点数 / LoRA / GGUF 等内部技术词
  - text 类 spec 必须显式声明 example_key (不再靠 node_id 兜底)

这些是纯数据约束, 违反时改对应 preset 的 definitions/<name>.json 即可, 不需要动代码.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import config


# description 里禁止出现的内部技术词 (用户视角看不到 node 353 / 9 节点 / LoRA 文件名).
_FORBIDDEN_DESC_TOKENS = (
    re.compile(r"node\s*\d+", re.IGNORECASE),  # node 353
    re.compile(r"\d+\s*节点"),                  # 9 节点
    "LoRA",
    "GGUF",
    "VAE",
    "CLIP",
    "CheckpointLoader",
)


def _all_preset_cfgs():
    """返回 [(name, cfg), ...], cfg 是完整 preset 配置 (含 display_name/order 等).

    单源: 读 definitions/*.json (跟代码运行时一致).
    """
    import json
    rows = []
    for def_path in sorted(config.DEFINITIONS_DIR.glob("*.json")):
        rows.append((def_path.stem, json.loads(def_path.read_text(encoding="utf-8"))))
    return rows


# ===== display_name 格式 =====

def test_display_name_matches_task_model_pattern():
    """display_name 必须形如「中文任务类型 (模型名)」: 以中文开头, 含一对括号.

    允许全角括号 () / 半角括号 (), 是中文排版习惯.
    """
    for name, cfg in _all_preset_cfgs():
        dn = cfg.get("display_name", "")
        # 必须以非 ASCII (中文) 开头
        assert dn and ord(dn[0]) > 127, f"{name}: display_name 必须以中文开头, 实际 {dn!r}"
        # 必须含恰好一对 (全角或半角) 括号
        lp = dn.count("(") + dn.count("（")
        rp = dn.count(")") + dn.count("）")
        assert lp == 1 and rp == 1, (
            f"{name}: display_name 必须含一对括号 '(模型名)', 实际 {dn!r}"
        )


def test_display_name_bracket_has_no_junk():
    """括号内的模型名不应混入用途描述 / distill / 海报 / 带字 等杂质词.

    全角 () / 半角 () 括号都接受, 取第一个 ( 或 ( 到第一个 ) 或 ) 之间的内容.
    """
    junk = ("海报", "带字", "distill", "distilled", "Distill", "Distilled",
            "4step", "4step", "节点", "node")
    for name, cfg in _all_preset_cfgs():
        dn = cfg.get("display_name", "")
        # 找第一个开括号 / 闭括号 (支持全角 / 半角)
        open_idx = min([i for i in [dn.find("("), dn.find("（")] if i != -1], default=-1)
        close_idx = min([i for i in [dn.find(")"), dn.find("）")] if i != -1], default=-1)
        bracket = dn[open_idx + 1: close_idx]
        for tok in junk:
            assert tok not in bracket, f"{name}: 括号内含杂质词 {tok!r}, display_name={dn!r}"


def test_display_names_are_globally_unique():
    """display_name 全局唯一 — 同模型的多个 preset 靠任务类型前缀区分, 不重名."""
    names = [cfg.get("display_name") for _, cfg in _all_preset_cfgs()]
    assert len(names) == len(set(names)), f"display_name 有重复: {names}"


# ===== order 分段 =====

def test_order_segmented_by_category():
    """review 2026-07-29: 单源重排后 order 是连续排序键, 不按 category 硬分段.

    旧的 'image=10-99, video=100-199, audio=200-299' 约束下线了, 因为现在同 category 的
    preset 可能穿插 (例如 Anima_turbo=140, sam3_mat_image=150 都是 image).
    视觉分组走 group 字段, 不靠 order 数值.

    现在只校验: order > 0 且同 category 内 order 唯一 (留空号给未来插入).
    """
    for name, cfg in _all_preset_cfgs():
        order = cfg.get("order", 0)
        assert order > 0, f"{name}: order 必须是正整数, 实际 {order}"
        # 同 category 内 order 唯一 (test_order_unique_within_category 测)


def test_order_unique_within_category():
    """同一类目内 order 不重复 (留空号给未来新 preset)."""
    from collections import defaultdict
    by_cat = defaultdict(list)
    for name, cfg in _all_preset_cfgs():
        cat = cfg.get("category", "other")
        by_cat[cat].append((cfg.get("order"), name))
    for cat, items in by_cat.items():
        orders = [o for o, _ in items]
        assert len(orders) == len(set(orders)), f"category={cat} 内 order 有重复: {items}"


# ===== output_kind 显式声明 =====

def test_video_presets_have_explicit_output_kind():
    """所有 video preset 必须显式写 output_kind (不再依赖 category 兜底)."""
    for name, cfg in _all_preset_cfgs():
        if cfg.get("category") == "video":
            assert cfg.get("output_kind") == "video", (
                f"{name}: video preset 必须显式 output_kind='video', "
                f"实际 {cfg.get('output_kind')!r}"
            )


# ===== description 干净 =====

def test_description_has_no_internal_tokens():
    """description 是用户视角文案, 禁止 node ID / 节点数 / LoRA / GGUF 等内部词."""
    failures = []
    for name, cfg in _all_preset_cfgs():
        desc = cfg.get("description", "")
        for tok in _FORBIDDEN_DESC_TOKENS:
            if isinstance(tok, re.Pattern):
                if tok.search(desc):
                    failures.append((name, tok.pattern, desc))
            elif tok in desc:
                failures.append((name, tok, desc))
    assert not failures, (
        "description 含内部技术词 (违反 user-perspective 约定):\n"
        + "\n".join(f"  {name}: 含 {tok!r} -> {desc!r}" for name, tok, desc in failures)
    )


def test_description_within_reasonable_length():
    """description 长度有上限但比 review 2026-07-14 当时宽 (review 2026-07-28 草稿后).

    review 2026-07-14 那笔写 description <=30 字符是为了标题区单行 (避免切换 preset 高度跳变).
    review 2026-07-28 那波草稿后, 标题区改成 min-height: 4.2em (3 行余量, .creator-bio CSS),
    长度放宽到 200 字以内都 OK (足够说明工作流, 不至于挤满整个面板).

    约束:
      - <= 200 字符: 防止 description 无限长把标题区撑爆
      - 不为空: 有 description 才能在标题区显示
      - min-height CSS 存在: 锁住高度, 切换 preset 不抖
    """
    failures = []
    for name, cfg in _all_preset_cfgs():
        desc = cfg.get("description", "")
        if not desc:
            failures.append((name, 0, "为空"))
        elif len(desc) > 200:
            failures.append((name, len(desc), desc))
    # CSS 上锁住 .creator-bio 的 min-height, 切换 preset 不抖
    css = (Path(__file__).resolve().parent.parent / "app" / "static" / "app-flask.css").read_text(encoding="utf-8")
    if "min-height" not in css.split(".creator-bio {", 1)[1].split("}", 1)[0]:
        failures.append(("__css__", 0, ".creator-bio 缺 min-height, 切换 preset 会抖"))
    assert not failures, (
        "description 不合规:\n"
        + "\n".join(f"  {name}: {n}字 {info!r}" for name, n, info in failures)
    )

# ===== example_key 显式声明 =====
# 注: basic text spec 必须有 example_key 的契约由
# tests/test_preset_must_have_example.py::test_every_basic_text_input_is_explicitly_backed_by_example
# 统一锁定 (它同时校验 key 字段存在 + example 字典里有对应值).
# advanced text spec (如负向提示词) 允许省略 example_key, 走 spec.default.
