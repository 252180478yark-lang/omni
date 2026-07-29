from __future__ import annotations

from app.services.video_production_match import build_execution_content_match_report


def _report(*, stage: str, audio_plan: dict) -> dict:
    return build_execution_content_match_report(
        stage=stage,
        truth_snapshot={
            "audience_record": {
                "name": "下班后认真做饭的人",
                "raw_md_segment": "下班后想快速做好一顿热饭，关注家庭厨房和真实做饭过程。",
                "match_reasons": ["家庭厨房", "热饭"],
            },
            "audience_portrait": {"portrait_md": "工作日晚上，想把一顿热饭做好。"},
        },
        candidate={
            "opening_hook_3s": "下班回家，锅已经热了。",
            "body": "在家庭厨房里做一顿热饭。",
            "spoken_copy": "今天也认真把这顿热饭做好。",
            "product_action": "起锅前加入产品。",
        },
        prompt_source={
            "prompt_source": {
                "product_solution_action": "在真实家庭厨房完成做饭动作。",
                "scene_detail": "单人家庭厨房，完成一顿热饭。",
                "sound_detail": "保留自然厨房声音和清晰口播。",
            }
        },
        reference_manifest={"items": [{"id": "ref-1", "type": "product", "sha256": "a" * 64}]},
        audio_plan=audio_plan,
    )


def test_planned_content_match_is_transparent_and_never_a_winner() -> None:
    report = _report(
        stage="planned",
        audio_plan={
            "mode": "planned_native_audio",
            "native_audio_requested": True,
            "bgm": {"mode": "not_supplied"},
        },
    )
    assert report["stage"] == "planned"
    assert report["transparent_proxy"]["algorithm"] == "transparent_lexical_overlap.v1"
    assert "never selects" in report["transparent_proxy"]["only_for"]
    assert "bgm_not_configured" in report["warnings"]
    assert report["execution_content"]["visual"]["reference_asset_ids"] == ["ref-1"]


def test_final_content_match_requires_visible_audio_scope_or_authorization() -> None:
    confirmed = _report(
        stage="final",
        audio_plan={
            "mode": "owner_supplied",
            "source_sha256": "b" * 64,
            "bgm": {"mode": "none_scope_confirmed", "scope_note": "本版交付 VO 加字幕，不添加 BGM。"},
        },
    )
    assert "no_bgm_scope_confirmation_missing" not in confirmed["warnings"]
    assert confirmed["execution_content"]["audio"]["bgm_mode"] == "none_scope_confirmed"

    authorized = _report(
        stage="final",
        audio_plan={
            "mode": "native",
            "source_sha256": "b" * 64,
            "bgm": {
                "mode": "authorized",
                "source_sha256": "c" * 64,
                "authorization_note": "内部已授权曲库素材。",
            },
        },
    )
    assert authorized["execution_content"]["audio"]["bgm_mode"] == "authorized"
    assert "authorized_bgm_manifest_incomplete" not in authorized["warnings"]
