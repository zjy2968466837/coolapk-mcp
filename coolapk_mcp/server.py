"""MCP Server — 酷安社区搜索工具"""

import functools
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from coolapk_mcp import postfilter
from coolapk_mcp.client import CoolapkClient, CoolapkError
from coolapk_mcp.models import FeedDetail, FeedModel, TopicModel, UserModel

mcp = FastMCP(
    "coolapk",
    instructions=(
        "酷安社区搜索工具。可搜索帖子、用户、应用、话题信息。"
        "主要用于获取社区内容和用户讨论信息。"
        "搜索默认启用严格关键词过滤与去重（strict=False 可关闭）；"
        "帖子详情在详情接口被风控时会自动回落到作者动态列表（fetch_source 字段标注来源）。"
    ),
)

_client: CoolapkClient | None = None


def _get_client() -> CoolapkClient:
    global _client
    if _client is None:
        _client = CoolapkClient()
    return _client


def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_defaults=True)
    return obj


def _json(data: Any) -> str:
    if data is None:
        return json.dumps({"error": "无数据"}, ensure_ascii=False)
    if isinstance(data, list):
        data = [_dump(item) for item in data]
    else:
        data = _dump(data)
    return json.dumps(data, ensure_ascii=False)


def _parse_feed_list(raw: Any) -> list[FeedModel]:
    if not isinstance(raw, list):
        return []
    return [FeedModel.from_api(f) for f in raw if isinstance(f, dict)]


def _catch_api_error(fn):
    """把 CoolapkError 转成结构化 JSON（带 error_type），AI 客户端可据此避免盲目重试"""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except CoolapkError as e:
            return json.dumps(
                {"error": e.message, "error_type": e.kind},
                ensure_ascii=False,
            )

    return wrapper


@mcp.tool()
@_catch_api_error
async def coolapk_search(
    keyword: str, type: str = "feed", page: int = 1, strict: bool = True
) -> str:
    """搜索酷安社区内容（自动去重 + 严格关键词过滤 + 疑似广告标记）。

    Args:
        keyword: 搜索关键词；多个词用空格分隔，strict 模式下要求全部命中
        type: 搜索类型，可选 feed(帖子) user(用户) feedTopic(话题) app(应用)
        page: 页码
        strict: 严格过滤（默认开）：归一化后每个关键词都必须出现在标题/正文/作者名里，
            可滤掉酷安搜索混入的不相关结果与机型名单广告；关闭则返回原始结果
    """
    client = _get_client()
    data = await client.search(keyword, type, page)
    if not isinstance(data, list):
        return _json(data)
    if type == "feed":
        kept, meta = postfilter.filter_search_results(data, keyword, strict=strict)
        results = postfilter.convert_search_items(kept)
        return json.dumps({"counts": meta, "results": results}, ensure_ascii=False)
    # user/feedTopic/app 结果不走严格过滤，仅剔除非实体卡片
    kept, meta = postfilter.filter_search_results(data, keyword, strict=False)
    results = postfilter.convert_search_items(kept)
    return json.dumps({"counts": meta, "results": results}, ensure_ascii=False)


@mcp.tool()
@_catch_api_error
async def coolapk_feed_detail(
    feed_id: int,
    with_replies: bool = True,
    reply_page: int = 1,
    author_uid: int | None = None,
    all_replies: bool = False,
    comment_keyword: str | None = None,
) -> str:
    """获取酷安帖子的完整详情和回复（详情接口被风控时自动回落）。

    Args:
        feed_id: 帖子ID
        with_replies: 是否包含回复列表，默认是
        reply_page: 回复页码（all_replies / comment_keyword 时忽略）
        author_uid: 作者UID（可选；提供可加速风控回落，不提供则自动查本地索引）
        all_replies: 拉全部一级评论（自动翻页，含内联楼中楼），适合完整舆情/评论分析
        comment_keyword: 按关键词检索评论和楼中楼（自动拉全量；空格分隔多词=任一命中；
            命中条目带 comment_match 字段，楼中楼按上下文保留，统计见 comment_search）
    """
    client = _get_client()
    smart = await client.get_feed_detail_smart(
        feed_id, author_uid=author_uid,
        with_replies=with_replies or bool(comment_keyword),
        reply_page=reply_page,
        all_replies=all_replies or bool(comment_keyword),
    )
    detail = FeedDetail.from_api(
        smart["data"],
        smart["replies"] if isinstance(smart["replies"], list) else None,
        fetch_source=smart["source"],
    )
    if comment_keyword:
        dumped = detail.model_dump(mode="json", exclude_defaults=True)
        dumped = postfilter.filter_comments(dumped, comment_keyword)
        return json.dumps(dumped, ensure_ascii=False)
    return _json(detail)


@mcp.tool()
@_catch_api_error
async def coolapk_user_profile(uid: int) -> str:
    """查看酷安用户资料。

    Args:
        uid: 用户UID
    """
    client = _get_client()
    data = await client.get_user_space(uid)
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        return _json(UserModel.from_api(data))
    return _json(data)


@mcp.tool()
@_catch_api_error
async def coolapk_user_feeds(uid: int, page: int = 1) -> str:
    """查看酷安用户发布的帖子。

    Args:
        uid: 用户UID
        page: 页码
    """
    client = _get_client()
    data = await client.get_user_feeds(uid, page)
    if isinstance(data, list):
        return _json(_parse_feed_list(data))
    return _json(data)


@mcp.tool()
@_catch_api_error
async def coolapk_home(tab: str = "recommend", page: int = 1) -> str:
    """获取酷安首页动态。

    Args:
        tab: 类型，可选 recommend(推荐) hot(热门) latest(最新)
        page: 页码
    """
    client = _get_client()
    if tab == "hot":
        data = await client.get_hot_feeds(page)
    elif tab == "latest":
        data = await client.get_latest_feeds(page)
    else:
        data = await client.get_home_feeds(page)
    if isinstance(data, list):
        return _json(_parse_feed_list(data))
    return _json(data)


@mcp.tool()
@_catch_api_error
async def coolapk_topic(tag: str, with_feeds: bool = False, page: int = 1) -> str:
    """查看酷安话题详情或话题下的帖子。

    Args:
        tag: 话题标签名
        with_feeds: 是否获取话题下的帖子列表
        page: 帖子页码
    """
    client = _get_client()
    result: dict[str, Any] = {}
    detail = await client.get_topic_detail(tag)
    if isinstance(detail, list) and detail:
        detail = detail[0]
    if isinstance(detail, dict):
        result["topic"] = TopicModel.from_api(detail)

    if with_feeds:
        feeds = await client.get_topic_feeds(tag, page)
        if isinstance(feeds, list):
            result["feeds"] = _parse_feed_list(feeds)
    return _json(result)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
