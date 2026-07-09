"""e-Stat パーサのオフライン検証（egress不要・pytest不要で直接実行可）。

実行: cd backend && python tests/test_estat.py
合成の getStatsData ペイロード（e-Stat の実スキーマに準拠）でパース結果を検証する。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.estat.parse import (  # noqa: E402
    build_class_lookup,
    iter_values,
    next_key,
    parse_value,
    parse_year,
    result_status,
)

# 国勢調査（市区町村×男女×年）を模した最小ペイロード。
SAMPLE = {
    "GET_STATS_DATA": {
        "RESULT": {"STATUS": 0, "ERROR_MSG": "正常に終了しました。"},
        "STATISTICAL_DATA": {
            "RESULT_INF": {"TOTAL_NUMBER": 6, "FROM_NUMBER": 1, "TO_NUMBER": 6},
            "CLASS_INF": {
                "CLASS_OBJ": [
                    {"@id": "tab", "@name": "表章項目", "CLASS": {"@code": "020", "@name": "人口", "@unit": "人"}},
                    {
                        "@id": "cat01",
                        "@name": "男女別",
                        "CLASS": [
                            {"@code": "000", "@name": "総数"},
                            {"@code": "001", "@name": "男"},
                            {"@code": "002", "@name": "女"},
                        ],
                    },
                    {
                        "@id": "area",
                        "@name": "地域",
                        "CLASS": [
                            {"@code": "13101", "@name": "千代田区"},
                            {"@code": "13000", "@name": "東京都"},
                        ],
                    },
                    {
                        "@id": "time",
                        "@name": "時間軸",
                        "CLASS": [
                            {"@code": "2020000000", "@name": "2020年"},
                            {"@code": "2015000000", "@name": "2015年"},
                        ],
                    },
                ]
            },
            "DATA_INF": {
                "VALUE": [
                    {"@tab": "020", "@cat01": "000", "@area": "13101", "@time": "2020000000", "@unit": "人", "$": "66,680"},
                    {"@tab": "020", "@cat01": "001", "@area": "13101", "@time": "2020000000", "@unit": "人", "$": "32,000"},
                    {"@tab": "020", "@cat01": "000", "@area": "13101", "@time": "2015000000", "@unit": "人", "$": "58,406"},
                    {"@tab": "020", "@cat01": "000", "@area": "13000", "@time": "2020000000", "@unit": "人", "$": "13,921,000"},
                    {"@tab": "020", "@cat01": "000", "@area": "13102", "@time": "2020000000", "@unit": "人", "$": "-"},
                ]
            },
        },
    }
}

# 1件だと dict になる e-Stat の癖を模したペイロード
SINGLE = {
    "GET_STATS_DATA": {
        "RESULT": {"STATUS": 0},
        "STATISTICAL_DATA": {
            "RESULT_INF": {"NEXT_KEY": 101},
            "CLASS_INF": {
                "CLASS_OBJ": {
                    "@id": "area",
                    "@name": "地域",
                    "CLASS": {"@code": "01100", "@name": "札幌市"},
                }
            },
            "DATA_INF": {
                "VALUE": {"@area": "01100", "@time": "2020000000", "@unit": "人", "$": "1973395"}
            },
        },
    }
}


def check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {name}")
    print(f"  ok: {name}")


def main() -> None:
    print("test_estat: parser self-test")

    # result_status
    status, msg = result_status(SAMPLE)
    check("status is 0", status == 0)

    # class lookup
    lookup = build_class_lookup(SAMPLE)
    check("area name resolved", lookup["area"]["13101"] == "千代田区")
    check("cat01 name resolved", lookup["cat01"]["001"] == "男")

    rows = list(iter_values(SAMPLE))
    check("row count = 5", len(rows) == 5)

    # 千代田区2020総数
    r0 = rows[0]
    check("area_code", r0["area_code"] == "13101")
    check("area_name", r0["area_name"] == "千代田区")
    check("year parsed", r0["period_year"] == 2020)
    check("value comma-stripped", r0["value"] == 66680.0)
    check("unit", r0["unit"] == "人")
    check("stat_label has 人口/総数", "人口" in (r0["stat_label"] or "") and "総数" in (r0["stat_label"] or ""))
    check("cat_key stable", r0["cat_key"] == "cat01=000;tab=020")

    # 系列の区別: 男 は cat_key が異なる
    r1 = rows[1]
    check("male cat_key differs", r1["cat_key"] != r0["cat_key"])
    check("male label", "男" in (r1["stat_label"] or ""))

    # 欠損値 '-' は None
    r_missing = rows[4]
    check("missing '-' -> None", r_missing["value"] is None)

    # 都道府県・全国も取得できる（フィルタは sync 側の責務）
    codes = {r["area_code"] for r in rows}
    check("prefecture row present", "13000" in codes)

    # 単数正規化 & next_key
    single_rows = list(iter_values(SINGLE))
    check("single VALUE normalized to 1 row", len(single_rows) == 1)
    check("single CLASS_OBJ normalized", single_rows[0]["area_name"] == "札幌市")
    check("single value no-comma", single_rows[0]["value"] == 1973395.0)
    check("next_key parsed", next_key(SINGLE) == 101)
    check("next_key none on SAMPLE", next_key(SAMPLE) is None)

    # スカラ関数
    check("parse_year short", parse_year("2023100000") == 2023)
    check("parse_year junk -> None", parse_year("xx") is None)
    check("parse_value suppressed", parse_value("***") is None)
    check("parse_value empty", parse_value("") is None)
    check("parse_value float", parse_value("1,234.5") == 1234.5)

    print("\nALL PASSED")


if __name__ == "__main__":
    main()
