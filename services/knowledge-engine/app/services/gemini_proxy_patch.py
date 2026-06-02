"""httplib2.Http proxy 注入补丁。

google-generativeai v0.8.x 用 google-api-python-client，其 FileServiceClient
内部直接 httplib2.Http() 上传文件 (Files API)。httplib2 默认无视 proxy 环境变量,
没补丁的话每次 upload_file 都直连 Google（在国内被墙）。

复用自 services/video-analysis/app/services/analysis.py:_patch_httplib2_for_proxy()
抽出来共享。reverse_storyboard_video tool 也用 Files API,同样需要这补丁。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def patch_httplib2_for_proxy() -> None:
    """模块加载期一次性 patch httplib2.Http.__init__ 注入 proxy_info。

    必须在 worker 线程触碰 FileServiceClient 前跑（结果会缓存到 threading.local
    里）。无 proxy 时静默跳过。重复调用安全（用 _omni_proxy_patched 标记防 double
    wrap）。
    """
    proxy_url = ""
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = os.getenv(var, "").strip()
        if val and "127.0.0.1" not in val and "localhost" not in val:
            proxy_url = val
            break

    if not proxy_url:
        return

    try:
        import httplib2
        import socks as _socks
        from urllib.parse import urlparse as _urlparse

        if getattr(httplib2.Http, "_omni_proxy_patched", False):
            return

        parsed = _urlparse(proxy_url)
        proxy_info = httplib2.ProxyInfo(
            proxy_type=_socks.PROXY_TYPE_HTTP,
            proxy_host=parsed.hostname,
            proxy_port=parsed.port or 80,
        )
        _orig_init = httplib2.Http.__init__

        def _patched_init(self, *args, **kwargs):
            kwargs.setdefault("proxy_info", proxy_info)
            _orig_init(self, *args, **kwargs)

        httplib2.Http.__init__ = _patched_init
        httplib2.Http._omni_proxy_patched = True  # type: ignore[attr-defined]
        logger.info(f"httplib2 proxy patched: {parsed.hostname}:{parsed.port}")
    except Exception as exc:
        logger.warning(f"httplib2 proxy patch failed (PySocks 缺?): {exc}")
