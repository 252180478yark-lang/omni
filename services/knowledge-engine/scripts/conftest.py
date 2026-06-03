# scripts/ 下是一次性调试/抓取探针脚本（淘宝 test_img_* 破反爬尝试、_test_competitor_* 等），
# 不是单元测试，且多数有模块级浏览器/网络代码，被 pytest 收集会卡死/报错污染测试套。
#
# 本应由 pyproject `testpaths=["tests"]` 拦住，但实测 `python -m pytest`（无路径参数）在本环境下
# 不尊重 testpaths，仍递归收集到 scripts/。这里用 collect_ignore_glob 在目录级强制跳过收集，
# 恒生效、非破坏性（脚本保留作调试参考），且 scripts/ 是 bind-mount → 容器内即时生效。
collect_ignore_glob = ["test_*.py", "_test_*.py", "*_test.py"]
