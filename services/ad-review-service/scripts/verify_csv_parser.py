"""离线快速校验 CSV 解析（对应 UAT 4.2 / TC-4.x），在项目根执行：
   cd services/ad-review-service && set PYTHONPATH=. && python scripts/verify_csv_parser.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.csv_parser import detect_encoding, parse_csv  # noqa: E402


def main() -> None:
    # UTF-8 BOM + 花费列名
    utf8_bom = (
        "\ufeff素材名称,花费,点击率,播放数\n"
        "素材A,100.5,0.025,1000\n"
        "素材B,--,,\n"
    ).encode("utf-8-sig")
    assert detect_encoding(utf8_bom) == "utf-8-sig"
    rows, mapping = parse_csv(utf8_bom)
    assert "花费" in mapping and mapping["花费"] == "cost"
    assert rows[0]["name"] == "素材A" and rows[0]["cost"] == 100.5
    assert rows[1]["cost"] is None

    # GBK
    gbk_header = "素材名称,消耗,展示次数\n测试,10,100\n".encode("gbk")
    rows2, _ = parse_csv(gbk_header)
    assert rows2[0]["name"] == "测试" and rows2[0]["cost"] == 10

    print("csv_parser checks: OK")


if __name__ == "__main__":
    main()
