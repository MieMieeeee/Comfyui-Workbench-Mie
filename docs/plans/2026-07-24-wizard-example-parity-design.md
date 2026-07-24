# 工作流向导示例与配置完整度设计

## 目标

向导保存的新工作流应具备与内置工作流一致的最低完整度：本次试跑参数成为默认参数，选中的最终产物成为示例预览，并为常见输入生成可用的显示元数据。

## 数据流

1. 向导以字段默认值试跑，并在前端保留本次 values。
2. 作者选择最终输出并填写名称、显示名称、分类和用途说明。
3. 保存接口校验产物位于 ComfyUI output/temp 根目录，将其复制到 app/static/examples/<preset>.<ext>。
4. 后端把本次 values 与 preview_image/preview_video/preview_audio 一起写入 definition.example。
5. 只有示例资产复制成功后才写 workflow 与 definition，避免半成品配置。

## Schema 提升

- 常见 EmptyLatentImage 节点的 width/height 合并为 image_sizes。
- image_sizes 自动带常用尺寸预设和帮助说明。
- text、file 和 int_random 自动带基础 help；种子补 min/max/step。
- 保存表单提供 30 字以内的用途说明，写入 description。

## 失败处理

产物缺失、路径越界或复制失败时返回 422，并且不写 definition。已有显式 example 的旧 API 调用保持兼容。

## 验证

单测覆盖尺寸合并、默认参数映射、资产复制、路径越界、保存顺序和前端提交契约；Krea-2 作为现有向导工作流完成数据升级与页面检查。
