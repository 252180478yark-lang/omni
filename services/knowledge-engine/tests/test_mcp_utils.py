"""T2：utils（Decimal 序列化）。"""
import json
from decimal import Decimal

from app.mcp.utils import decimal_to_jsonable


def test_decimal_to_jsonable_scalar():
    assert decimal_to_jsonable(Decimal("12.345")) == "12.345"


def test_decimal_to_jsonable_nested_dict():
    src = {"price": Decimal("9.99"), "qty": 3, "child": {"cost": Decimal("0.50")}}
    out = decimal_to_jsonable(src)
    assert out == {"price": "9.99", "qty": 3, "child": {"cost": "0.50"}}
    # 验证可被 json.dumps
    json.dumps(out)


def test_decimal_to_jsonable_list():
    src = [Decimal("1"), {"a": Decimal("2")}, [Decimal("3")]]
    out = decimal_to_jsonable(src)
    assert out == ["1", {"a": "2"}, ["3"]]
    json.dumps(out)


def test_decimal_to_jsonable_passthrough_other_types():
    assert decimal_to_jsonable(None) is None
    assert decimal_to_jsonable("hi") == "hi"
    assert decimal_to_jsonable(42) == 42
    assert decimal_to_jsonable(3.14) == 3.14
    assert decimal_to_jsonable(True) is True
