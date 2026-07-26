"""运行页不能有孤立的 preset-actions 行 (那是和 creator-card 重复的按钮组)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "app" / "templates" / "run.html").read_text(encoding="utf-8")


def test_no_orphan_preset_actions_div():
    """preset-actions 整块在 creator-card 合并之后已经删掉, 防止回潮."""
    assert '<div class="preset-actions">' not in TEMPLATE, (
        "run.html 还有独立的 preset-actions 行, 那会让按钮脱离 creator-card,"
        "用户会觉得宽度对不齐. creator-card 顶部已经放了按钮, 不要再加第二组."
    )


def test_no_orphan_load_example_button():
    """避免单独 📥 加载示例素材 / 📂 加载上次成功参数 按钮回潮 (被合并掉的旧实现)."""
    assert "📥 加载示例素材" not in TEMPLATE
    assert "📂 加载上次成功参数" not in TEMPLATE


def test_creator_card_has_load_actions():
    """加载示例 / 加载上次 必须能在 creator-card 顶部找到 (不能因为删独立按钮就漏掉)."""
    assert "loadExample(w.name)" in TEMPLATE
    assert "loadLastRun(w.name)" in TEMPLATE
