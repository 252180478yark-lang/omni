import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FetchJob(Base):
    __tablename__ = "fetch_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    triggered_by: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    sources_used: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    keywords_used: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    total_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    after_dedup: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    after_enrich: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
