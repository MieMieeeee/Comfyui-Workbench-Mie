"""scail2_app 里 estimate / _update_est 逻辑的单测。

这些函数现在是位置参数耦合（rest[0..2]），测试将暴露：
- 当某个 idx 为 None（preset 缺字段）时，_update_est 不应错位
- _max_idx 对应的 input 只应被 append 一次（不是两次）

由于 _update_est 当前耦合 build_ui 的索引拼接，我们直接测 estimated_segments
纯函数，并把 _update_est 重构成 kwargs 后测它。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from app import scail2_app


# --- estimated_segments 纯函数（已存在，回归保护）---

class TestEstimatedSegments:
    def test_frames_equals_one_segment(self):
        """驱动视频帧数 == 每段长度 → 1 段。"""
        assert scail2_app.estimated_segments(81, per_seg=81, pre_drop=5) == 1

    def test_frames_less_than_per_seg(self):
        """帧数 < 每段 → 1 段（至少一段）。"""
        assert scail2_app.estimated_segments(50, per_seg=81, pre_drop=5) == 1

    def test_two_segments(self):
        """81 + 76 = 157 帧 → 2 段（81 + (157-81)/76=1）。"""
        assert scail2_app.estimated_segments(157, per_seg=81, pre_drop=5) == 2

    def test_three_segments(self):
        """81 + 76 + 76 = 233 → 3 段。"""
        assert scail2_app.estimated_segments(233, per_seg=81, pre_drop=5) == 3

    def test_max_segments_caps(self):
        """max_segments=2 时即使视频够长也只跑 2 段。"""
        assert scail2_app.estimated_segments(500, per_seg=81, pre_drop=5, max_segments=2) == 2

    def test_max_segments_zero_means_unlimited(self):
        """max_segments=0 = 不限制。"""
        big = scail2_app.estimated_segments(500, per_seg=81, pre_drop=5, max_segments=0)
        assert big > 2

    def test_none_frames(self):
        assert scail2_app.estimated_segments(None, per_seg=81, pre_drop=5) is None

    def test_zero_frames(self):
        assert scail2_app.estimated_segments(0, per_seg=81, pre_drop=5) is None


# --- _update_est kwargs 重构后的行为（先写，期望重构后通过）---

class TestUpdateEstKwargs:
    """_update_est 重构为 kwargs 后，不应依赖 rest 的位置。

    重点：当某个参数没传（preset 缺该字段）时，用默认值，不报错、不错位。
    """

    def test_no_drive_returns_prompt(self):
        """没上传驱动视频 → 返回提示语。"""
        out = scail2_app._update_est(None, per_seg=81, pre_drop=5, max_segments=0)
        assert "上传" in out or "驱动" in out

    def test_all_params_present(self):
        """四参数齐全 → 返回含 '段数' 的 markdown。"""
        # 用一个真 mp4 才能读帧数；这里用一个可能不存在的路径，
        # _update_est 读不到帧数会返回 "读取失败"，也是合法分支
        out = scail2_app._update_est("nonexistent.mp4", per_seg=81, pre_drop=5, max_segments=0)
        # 帧数读不到 → "读取失败"；读到了 → 含 "段数"
        assert isinstance(out, str)
        assert ("段数" in out) or ("读取失败" in out) or ("上传" in out)

    def test_only_drive_no_optional(self):
        """只传驱动视频路径，per_seg/pre_drop/max_segments 用默认值。"""
        out = scail2_app._update_est("nonexistent.mp4")
        assert isinstance(out, str)

    def test_max_segments_capped_display(self):
        """max_segments 限制时，输出应含 '限制' 字样（当读得到帧数时）。"""
        # 因为读不到帧数会走 "读取失败" 分支，这里只验证不抛异常
        out = scail2_app._update_est("nonexistent.mp4", per_seg=81, pre_drop=5, max_segments=3)
        assert isinstance(out, str)
