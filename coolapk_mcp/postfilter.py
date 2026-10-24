"""搜索结果后处理 — 去重、严格关键词过滤、疑似广告标记

酷安搜索接口按时间偏向排序且不剔除推广内容，直接返回的结果里混有：
- 同一作者相同内容的重复帖（转发/重发）
- 堆砌机型名单的"远程解BL/刷root"服务广告
- 赞助商卡片（entityType=card）

本模块在客户端侧做轻量清洗。只做标记与过滤，不改变原始数据语义。
"""

from __future__ import annotations

import re
from typing import Any

# 命中即标记为疑似广告的特征（窄口径，避免误伤正常讨论帖）
_AD_PATTERNS: tuple[str, ...] = (
    "秒解bl",
    "远程解锁",
    "远程root",
    "远程秒解",
    "刷root+",
    "降级+5",
    "刷官改",
    "过环境",
    "解锁bl锁",
)

_ADS_KEY = "_suspected_ad"


def _norm(s: str | None) -> str:
    """归一化：去空白/#/__、转小写。'小米15 Ultra' 与 '#小米15Ultra#' 视为相同"""
    return re.sub(r"[\s#＃_]+", "", s or "").lower()


def _feed_full_text(item: dict) -> str:
    """帖子全文 = 标题 + 正文(HTML先剥掉) + 作者名，用于关键词判定"""
    parts = [
        item.get("messageTitle") or "",
        item.get("title") or "",
        item.get("message") or "",
        (item.get("userInfo") or {}).get("username", ""),
        item.get("username") or "",
    ]
    text = " ".join(str(p) for p in parts if p)
    return re.sub(r"<[^>]+>", " ", text)


def _strip_cards(items: list[Any]) -> list[dict]:
    """过滤 card 包装（赞助卡/话题卡等非结果条目），保留实体条目"""
    return [
        it for it in items
        if isinstance(it, dict) and it.get("entityType") not in ("card",)
    ]


def filter_search_results(
    items: list[Any], keyword: str, strict: bool = True
) -> tuple[list[dict], dict]:
    """清洗搜索结果

    Returns:
        (清洗后的原始条目列表, 统计信息)
    """
    meta: dict[str, Any] = {
        "keyword": keyword,
        "strict": strict,
        "raw_count": len(items) if isinstance(items, list) else 0,
        "cards_removed": 0,
        "duplicates_removed": 0,
        "keyword_filtered": 0,
        "suspected_ads": 0,
    }
    if not isinstance(items, list):
        return [], meta

    entities = _strip_cards(items)
    meta["cards_removed"] = len(items) - len(entities)

    # 严格关键词：归一化后的每个查询词都必须出现在全文里
    terms = [_norm(t) for t in keyword.split() if _norm(t)]

    kept: list[dict] = []
    seen_ids: set[int] = set()
    seen_content: set[str] = set()

    for item in entities:
        et = item.get("entityType", "")
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id.isdigit():
            item_id = int(item_id)
        if not isinstance(item_id, int):
            item_id = None

        # 去重：同 id，或 同作者+相同正文开头
        if item_id is not None and item_id in seen_ids:
            meta["duplicates_removed"] += 1
            continue
        user_info = item.get("userInfo") or {}
        uid = item.get("uid") or user_info.get("uid") or 0
        content_key = f"{uid}:{_norm(item.get('message') or item.get('messageTitle') or '')[:80]}"
        if et == "feed" and content_key in seen_content:
            meta["duplicates_removed"] += 1
            continue

        # 疑似广告标记（只标记不删除）
        if et == "feed":
            full = _norm(_feed_full_text(item))
            if any(p in full for p in _AD_PATTERNS):
                item[_ADS_KEY] = True
                meta["suspected_ads"] += 1

        # 严格过滤
        if strict and terms and et == "feed":
            full = _norm(_feed_full_text(item))
            if not all(t in full for t in terms):
                meta["keyword_filtered"] += 1
                continue

        if item_id is not None:
            seen_ids.add(item_id)
        if et == "feed":
            seen_content.add(content_key)
        kept.append(item)

    meta["result_count"] = len(kept)
    return kept, meta


def convert_search_items(items: list[dict]) -> list[dict]:
    """原始条目 → 精简模型 dict，广告标记带过去"""
    from coolapk_mcp.models import (
        AppModel,
        FeedModel,
        TopicModel,
        UserModel,
    )

    results: list[dict] = []
    for item in items:
        et = item.get("entityType", "")
        model = None
        if et == "feed":
            model = FeedModel.from_api(item)
        elif et == "user":
            model = UserModel.from_api(item)
        elif et in ("topic", "tag"):
            model = TopicModel.from_api(item)
        elif et == "app":
            model = AppModel.from_api(item)
        if model is None:
            continue
        dumped = model.model_dump(mode="json", exclude_defaults=True)
        if item.get(_ADS_KEY):
            dumped["suspected_ad"] = True
        results.append(dumped)
    return results


def filter_comments(detail: dict, keyword: str) -> dict:
    """在已 dump 的帖子详情里按关键词检索评论和楼中楼（原地修改并返回）。

    匹配规则：空格分隔多个词，任意命中即算（OR）；归一化后对
    content + username + reply_to 匹配（'华为 屏幕' 能搜到'华为的屏幕'）。

    返回结构：
    - comment_match="comment"：一级评论本身命中（楼中楼全保留作上下文）
    - comment_match="sub_reply"：仅楼中楼命中（只保留命中的楼中楼）
    - detail["comment_search"]：检索统计（命中数/扫描数）
    """
    terms = [_norm(t) for t in keyword.split() if _norm(t)]
    replies = detail.get("replies", [])
    if not terms or not replies:
        return detail

    scanned_sub = sum(len(r.get("sub_replies", [])) for r in replies)

    def _hit(obj: dict) -> bool:
        hay = _norm(
            f"{obj.get('content', '')} {obj.get('username', '')} "
            f"{obj.get('reply_to', '')}"
        )
        return any(t in hay for t in terms)

    matched: list[dict] = []
    matched_sub = 0
    for r in replies:
        self_hit = _hit(r)
        sub_hits = [s for s in r.get("sub_replies", []) if _hit(s)]
        if not self_hit and not sub_hits:
            continue
        row = dict(r)
        if self_hit:
            row["comment_match"] = "comment"  # 楼中楼全保留
        else:
            row["sub_replies"] = sub_hits      # 只保留命中的楼中楼
            row["comment_match"] = "sub_reply"
            matched_sub += len(sub_hits)
        matched.append(row)

    detail["replies"] = matched
    detail["comment_search"] = {
        "keyword": keyword,
        "matched_comments": len(matched),
        "matched_sub_replies": matched_sub,
        "scanned_comments": len(replies),
        "scanned_sub_replies": scanned_sub,
    }
    return detail
