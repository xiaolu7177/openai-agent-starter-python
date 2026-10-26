"""
Agent Tools — 出行决策 Agent（高德地图 Web 服务）

私有模块（以 _ 开头），不会被映射为公开路由。

所有工具均从环境变量读取密钥，绝不硬编码 Key。

工具清单：
  1. geocode_place       —— 把「位置描述」转成经纬度（高德 /v3/geocode/geo）
  2. search_nearby_malls —— 根据坐标检索附近商场（高德 /v3/place/around）
  3. search_brand_in_mall —— 在某商场内检索品牌门店（高德 /v3/place/text + 商场名）
  4. calc_distance        —— 计算起点到商场的距离（高德 /v3/distance）

地点、门店与距离一律以高德接口返回为准，不由模型自行编造。
"""

import json
import os
from typing import Annotated, Any

import httpx

from agents import function_tool

AMAP_KEY = os.getenv("AMAP_API_KEY", "")
AMAP_REST = "https://restapi.amap.com/v3"


def _amap_get(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """调用高德 REST 接口，统一处理 key 注入与异常。

    高德约定：
      - status == "1" 且 infocode == "10000" 表示成功；
      - 其余 infocode 为具体错误码。
    """
    if not AMAP_KEY:
        return {"error": "缺少高德地图 Key（环境变量 AMAP_API_KEY 未配置）"}

    params = {**params, "key": AMAP_KEY}
    try:
        resp = httpx.get(f"{AMAP_REST}/{endpoint}", params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        return {"error": f"高德接口请求失败: {type(e).__name__}: {e}"}
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"高德接口返回无法解析: {e}"}

    if data.get("status") != "1":
        info = data.get("info", "")
        infocode = data.get("infocode", "")
        return {"error": f"高德接口返回错误 (infocode={infocode}): {info}"}

    return data


def _format_poi(poi: dict[str, Any]) -> dict[str, Any]:
    """把高德 POI 精简为结构化字段，供 Agent 阅读与排序。"""
    location = (poi.get("location") or "").split(",")
    lon = float(location[0]) if len(location) == 2 else None
    lat = float(location[1]) if len(location) == 2 else None
    biz_ext = poi.get("biz_ext") or {}
    return {
        "name": poi.get("name", ""),
        "type": poi.get("type", ""),
        "address": poi.get("address", ""),
        "tel": poi.get("tel", ""),
        "rating": biz_ext.get("rating", ""),
        "opening_hours": biz_ext.get("open_time", ""),
        "location": poi.get("location", ""),
        "lon": lon,
        "lat": lat,
    }


@function_tool
def geocode_place(
    address: Annotated[str, "地点描述，例如：红莲南路地铁站、北京市西城区某某路口"],
    city: Annotated[str, "城市名，用于限定搜索范围，例如：北京"] = "北京",
) -> str:
    """把文字地点转成经纬度坐标。用户只给出地点名（而非坐标）时，先用本工具拿到坐标。"""
    data = _amap_get("geocode/geo", {"address": address, "city": city})
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)

    geocodes = data.get("geocodes") or []
    if not geocodes:
        return json.dumps({"error": f"未在地图中找到地点「{address}」"}, ensure_ascii=False)

    top = geocodes[0]
    location = top.get("location", "")
    return json.dumps({
        "place": top.get("formatted_address", address),
        "location": location,
        "province": top.get("province", ""),
        "city": top.get("city", ""),
        "district": top.get("district", ""),
    }, ensure_ascii=False)


@function_tool
def search_nearby_malls(
    location: Annotated[str, "中心点坐标，格式 '经度,纬度'，例如 '116.32,39.89'，可从 geocode_place 获取"],
    radius: Annotated[int, "搜索半径（米），默认 3000"] = 3000,
    keywords: Annotated[str, "检索关键词，默认 商场"] = "商场",
) -> str:
    """以某坐标为中心，检索周边商场，返回名称、地址、坐标、评分等。"""
    data = _amap_get(
        "place/around",
        {
            "location": location,
            "radius": radius,
            "keywords": keywords,
            "types": "060100",  # 购物服务;商场
            "sortrule": "distance",
            "offset": 20,
            "page": 1,
        },
    )
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)

    pois = [_format_poi(p) for p in data.get("pois", [])]
    return json.dumps({"count": data.get("count"), "malls": pois}, ensure_ascii=False)


@function_tool
def search_brand_in_mall(
    mall_name: Annotated[str, "商场名称，例如：北京荟聚"],
    brand: Annotated[str, "品牌或门店关键词，例如：倍轻松、星巴克"],
    city: Annotated[str, "城市名，用于限定范围"] = "北京",
) -> str:
    """在指定商场内检索某品牌/门店是否存在，返回门店名称、地址、电话等。"""
    data = _amap_get(
        "place/text",
        {
            "keywords": f"{brand} {mall_name}",
            "city": city,
            "offset": 20,
            "page": 1,
        },
    )
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)

    pois = [_format_poi(p) for p in data.get("pois", [])]
    # 只保留与商场名或品牌相关的门店
    matched = [
        p for p in pois
        if mall_name in p["name"] or mall_name in p["address"] or brand in p["name"]
    ]
    return json.dumps({
        "brand": brand,
        "mall": mall_name,
        "count": len(matched),
        "stores": matched,
    }, ensure_ascii=False)


@function_tool
def calc_distance(
    origins: Annotated[str, "起点坐标，格式 '经度,纬度'"],
    destination: Annotated[str, "终点坐标，格式 '经度,纬度'"],
    type_: Annotated[int, "距离类型：0 直线距离，1 驾车，3 步行；默认 0"] = 0,
) -> str:
    """计算起点到终点的距离（直线/驾车/步行），返回距离与预计耗时。"""
    data = _amap_get(
        "distance",
        {"origins": origins, "destination": destination, "type": type_},
    )
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)

    results = data.get("results") or []
    if not results:
        return json.dumps({"error": "距离计算无结果"}, ensure_ascii=False)

    return json.dumps(results[0], ensure_ascii=False)
