from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.runtime_trace import AttachmentContract, ProviderSessionContract


def test_provider_neutral_contract_keeps_real_runner_session_and_trace_identity():
    contract = ProviderSessionContract(
        session_id="session:one", runner_provider="codex", runner_session_id="runner:one", project_dir="E:/agent/omni",
        trace_id="trace:one", model="gpt", effort="high",
    )
    attachment = AttachmentContract(attachment_id="attachment:" + "b" * 32, sha256="a" * 64, size_bytes=1, content_type="text/plain", storage_key="sha256/" + "a" * 64 + ".txt")
    assert contract.runner_session_id == "runner:one" and attachment.sha256 == "a" * 64


def test_provider_contract_allows_fresh_session_but_rejects_placeholder_resume_identifier():
    fresh = ProviderSessionContract(session_id="session:one", runner_provider="codex", project_dir="E:/agent/omni")
    assert fresh.runner_session_id is None
    with pytest.raises(ValidationError):
        ProviderSessionContract(session_id="session:one", runner_provider="codex", runner_session_id="x", project_dir="E:/agent/omni")
