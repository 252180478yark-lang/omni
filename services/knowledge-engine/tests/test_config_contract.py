from __future__ import annotations

from urllib.parse import urlsplit

from app.config import Settings


def test_internal_service_defaults_match_canonical_container_ports(monkeypatch) -> None:
    environment_names = (
        "AI_PROVIDER_HUB_URL",
        "AD_REVIEW_SERVICE_URL",
        "SCOUT_AGENT_URL",
        "VIDEO_ANALYSIS_SERVICE_URL",
    )
    for name in environment_names:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)
    endpoints = {
        "ai-provider-hub": settings.ai_provider_hub_url,
        "ad-review-service": settings.ad_review_service_url,
        "scout-agent": settings.scout_agent_url,
        "video-analysis": settings.video_analysis_service_url,
    }
    assert {
        service: (urlsplit(endpoint).hostname, urlsplit(endpoint).port)
        for service, endpoint in endpoints.items()
    } == {
        "ai-provider-hub": ("ai-provider-hub", 8001),
        "ad-review-service": ("ad-review-service", 8008),
        "scout-agent": ("scout-agent", 8009),
        "video-analysis": ("video-analysis", 8006),
    }


def test_internal_service_url_can_still_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("AD_REVIEW_SERVICE_URL", "http://review-fixture:18008")
    assert Settings(_env_file=None).ad_review_service_url == "http://review-fixture:18008"
