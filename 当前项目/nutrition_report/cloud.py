"""云端食物营养库访问、缓存与本地回退。"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests


DEFAULT_BASE_URL = "https://survey.femalesportshealth.cn/api/trophic"
DEFAULT_CACHE_TTL_SECONDS = 30 * 60


@dataclass(frozen=True)
class FoodDataResult:
    foods: dict[str, dict[str, Any]]
    metadata: dict[str, Any]


_cache_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _api_get(url: str, *, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    # 该接口目前返回 application/json 但未声明 charset，显式按 UTF-8 解码中文。
    response.encoding = "utf-8"
    payload = response.json()
    if payload.get("code") != 200:
        raise RuntimeError(str(payload.get("message") or "云端接口返回失败状态"))
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise RuntimeError("云端接口返回的数据格式不正确")
    return data


def fetch_cloud_foods(
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 8.0,
    getter: Callable[..., dict[str, Any]] = _api_get,
) -> dict[str, dict[str, Any]]:
    """读取全部分类及食物；任一分类失败时视为本轮云端查询失败。"""
    root = base_url.rstrip("/")
    category_data = getter(
        f"{root}/category",
        params={"pageNum": 1, "pageSize": 50},
        timeout=timeout,
    )
    categories = category_data.get("records") or []
    categories = [item for item in categories if isinstance(item, dict) and item.get("id")]
    if not categories:
        raise RuntimeError("云端食物分类为空")

    def load_category(category: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        data = getter(
            f"{root}/goodsInfo",
            params={"categoryId": category["id"], "pageNum": 1, "pageSize": 200},
            timeout=timeout,
        )
        return str(category.get("name") or "").strip(), data.get("records") or []

    foods: dict[str, dict[str, Any]] = {}
    worker_count = min(8, len(categories))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="nutrition-cloud") as executor:
        futures = [executor.submit(load_category, category) for category in categories]
        for future in as_completed(futures):
            category_name, records = future.result()
            for record in records:
                if not isinstance(record, dict):
                    continue
                name = str(record.get("name") or "").strip()
                if not name:
                    continue
                foods[name] = {
                    "category": category_name,
                    "energy": record.get("energy", 0),
                    "protein": record.get("protein", 0),
                    "fat": record.get("fat", 0),
                    "carbohydrate": record.get("carbohydrate", 0),
                    "calcium": record.get("calcium", 0),
                }
    if not foods:
        raise RuntimeError("云端食物营养数据为空")
    return foods


def _load_local_foods() -> dict[str, dict[str, Any]]:
    path = Path(__file__).resolve().parent / "data" / "food_db.json"
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_food_data(
    *,
    prefer_cloud: bool = True,
    base_url: str | None = None,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    fetcher: Callable[..., dict[str, dict[str, Any]]] = fetch_cloud_foods,
) -> FoodDataResult:
    """返回云端优先的数据；云端失败时使用旧缓存或包内本地库。"""
    resolved_base = (base_url or os.environ.get("NUTRITION_CLOUD_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    if not prefer_cloud:
        queried_at = _now_iso()
        return FoodDataResult(
            _load_local_foods(),
            {
                "kind": "local",
                "label": "本地食物营养库",
                "cloud_available": None,
                "message": "营养数据来源：本地食物营养库",
                "queried_at": queried_at,
                "base_url": resolved_base,
                "error": "",
                "cache_hit": False,
                "using_stale_cache": False,
            },
        )

    now = time.monotonic()
    with _cache_lock:
        cached = dict(_cache) if _cache.get("base_url") == resolved_base else {}
    if cached and now - cached["stored_monotonic"] < cache_ttl_seconds:
        metadata = dict(cached["metadata"])
        metadata["cache_hit"] = True
        return FoodDataResult(cached["foods"], metadata)

    queried_at = _now_iso()
    try:
        foods = fetcher(base_url=resolved_base)
        metadata = {
            "kind": "cloud",
            "label": "云端食物营养库",
            "cloud_available": True,
            "message": "营养数据来源：云端食物营养库",
            "queried_at": queried_at,
            "base_url": resolved_base,
            "error": "",
            "cache_hit": False,
            "using_stale_cache": False,
        }
        with _cache_lock:
            _cache.clear()
            _cache.update({
                "base_url": resolved_base,
                "stored_monotonic": now,
                "foods": foods,
                "metadata": metadata,
            })
        return FoodDataResult(foods, metadata)
    except Exception as error:
        reason = str(error).strip() or error.__class__.__name__
        if cached:
            metadata = dict(cached["metadata"])
            metadata.update({
                "kind": "stale_cloud",
                "label": "上次云端缓存",
                "cloud_available": False,
                "message": "云端无法访问，当前使用上次云端缓存",
                "error": reason,
                "cache_hit": True,
                "using_stale_cache": True,
                "last_attempt_at": queried_at,
            })
            return FoodDataResult(cached["foods"], metadata)
        return FoodDataResult(
            _load_local_foods(),
            {
                "kind": "local",
                "label": "本地食物营养库（云端回退）",
                "cloud_available": False,
                "message": "云端无法访问，当前使用本地营养库",
                "queried_at": queried_at,
                "base_url": resolved_base,
                "error": reason,
                "cache_hit": False,
                "using_stale_cache": False,
            },
        )


def clear_food_data_cache() -> None:
    """仅供测试和显式刷新使用。"""
    with _cache_lock:
        _cache.clear()
