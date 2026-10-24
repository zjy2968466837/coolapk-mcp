# Changelog

## [0.3.0-fork] - 2026-10-24

### Added
- `throttle.py`：全局限速 / GET TTL 缓存 / 瞬态退避重试 / 验证码负缓存（环境变量可调）
- `postfilter.py`：搜索去重+严格关键词过滤+疑似广告标记；评论/楼中楼关键词检索（`--grep` / `comment_keyword`）
- 数盟 ShuzlmID 设备码 `encode_device_code/decode_device_code`，实测解除 detail/replyList 验证码拦截
- 详情风控回落：feed_id→uid 持久化索引 + 作者动态列表取正文（`fetch_source` 标注）
- 全量评论：`--all-replies` / `all_replies=true` 自动翻页，ReplyModel 带楼中楼 `sub_replies`
- 错误分类 `error_type`（captcha/network/api/...），MCP 工具统一结构化错误输出

### Changed
- 默认设备码不再使用公共共享码（已被多账号风控 -415 拉黑），改为每安装独享 UUID（有数盟 ID 时用 encode_device_code）
- `coolapk_search` 默认 strict=True，返回 `{counts, results}` 结构


## [0.2.0] - 2026-10-22

### Docs
- README 首屏改为专业图文 Hero + badges + 场景表
- 新增 Cursor / Claude `mcp.json` 配置说明
- 新增「生态适配」：Qx / qxcoolapk 友链与 Workbench 使用案例配图（#4）
- 新增「已知限制」：说明 `feed/detail` captcha（#5）
- 弱化实现细节中的敏感措辞

### Meta
- Topics 已更新：ai, claude, coolapk, cursor, mcp, mcp-server, python
