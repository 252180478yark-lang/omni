from app.services.fetch_verdict import compute_verdict, extract_biz_code


def test_biz_code_compat_order():
    assert extract_biz_code({"code": 0}) == 0
    assert extract_biz_code({"Code": 404}) == 404          # 404 大写
    assert extract_biz_code({"status": 1001}) == 1001      # 云图
    assert extract_biz_code({"st": 0}) == 0                # 罗盘
    assert extract_biz_code({"errno": 5}) == 5
    assert extract_biz_code({"data": {}}) is None
    assert extract_biz_code({"code": 0, "st": 9}) == 0     # code 优先


def test_pass_with_data():
    r = compute_verdict(200, "application/json",
                        {"code": 0, "data": {"total_count": 127392}},
                        '{"code":0}', ["total_count"])
    assert r["verdict"] == "PASS"
    assert r["code"] == 0
    assert r["has_data"] is True
    assert r["fields"] == {"total_count": 127392}


def test_pass_nodata_empty():
    r = compute_verdict(200, "application/json", {"code": 0, "data": {}}, "{}", [])
    assert r["verdict"] == "PASS_NODATA"
    assert r["has_data"] is False


def test_fail_drift_html():
    r = compute_verdict(200, "text/html", None, "<!DOCTYPE html><html>", [])
    assert r["verdict"] == "FAIL_DRIFT"


def test_fail_404():
    r = compute_verdict(404, "application/json", {"Code": 404}, '{"Code":404}', [])
    assert r["verdict"] == "FAIL_404"


def test_fail_auth_403():
    r = compute_verdict(403, "application/json", None, "", [])
    assert r["verdict"] == "FAIL_AUTH"


def test_fail_auth_bizcode():
    r = compute_verdict(200, "application/json", {"status": 4000}, '{"status":4000}', [])
    assert r["verdict"] == "FAIL_AUTH"


def test_fail_other_bizcode():
    r = compute_verdict(200, "application/json", {"st": 100003}, '{"st":100003}', [])
    assert r["verdict"] == "FAIL_OTHER"


def test_extract_fields_nested():
    r = compute_verdict(200, "application/json",
                        {"code": 0, "data": {"a": {"b": 5}}}, "{}", ["data.a.b", "missing"])
    assert r["fields"] == {"data.a.b": 5}  # 取到的才进，missing 不进
