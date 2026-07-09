from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsCategory:
    id: str
    label: str
    description: str
    query: str
    color: str  # tailwind color name for badge


NEWS_CATEGORIES: list[NewsCategory] = [
    NewsCategory(
        id="land_price",
        label="地価・公示",
        description="地価公示・地価調査・公示地価に関するニュース",
        query="地価公示 OR 地価調査 OR 公示地価",
        color="emerald",
    ),
    NewsCategory(
        id="market",
        label="取引・相場",
        description="不動産取引価格・市場動向・相場情報",
        query="不動産取引 相場 OR 不動産 価格推移",
        color="brand",
    ),
    NewsCategory(
        id="housing",
        label="住宅・マンション",
        description="分譲マンション・新築・中古住宅の市場",
        query="マンション 価格 OR 新築住宅 不動産 OR 中古マンション",
        color="violet",
    ),
    NewsCategory(
        id="policy",
        label="政策・税制",
        description="不動産関連の法改正・税制・規制",
        query="不動産 税制 OR 不動産 規制 OR 住宅ローン 政策",
        color="amber",
    ),
    NewsCategory(
        id="development",
        label="再開発・都市",
        description="再開発・駅前開発・都市計画",
        query="不動産 再開発 OR 駅前開発 OR 都市計画 不動産",
        color="rose",
    ),
]

CATEGORY_BY_ID = {c.id: c for c in NEWS_CATEGORIES}
