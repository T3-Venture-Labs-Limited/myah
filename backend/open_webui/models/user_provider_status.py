"""UserProviderStatus — platform metadata about each user's connected provider.

Composite primary key (user_id, provider_id). No secrets stored here; the
encrypted credentials live in the user's Hermes container under
/data/.hermes/{env,auth.json,credential_pool.json}. This table only records
that a credential exists + what its last-four are + when it was last
validated, so the UI can render "Connected" tiles and default-model
selectors without hitting the agent container on every page load.
"""
import time

from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, PrimaryKeyConstraint, String, Index


class UserProviderStatus(Base):
    __tablename__ = 'user_provider_status'
    __table_args__ = (
        PrimaryKeyConstraint('user_id', 'provider_id', name='pk_user_provider_status'),
        Index('ix_user_provider_status_user_id', 'user_id'),
    )

    user_id = Column(String, nullable=False)
    provider_id = Column(String, nullable=False)
    entry_id = Column(String, nullable=True)
    connected_at = Column(BigInteger, nullable=False, server_default='0')
    last_validated_at = Column(BigInteger, nullable=True)
    is_valid = Column(Boolean, nullable=False, server_default='true')
    key_last_four = Column(String, nullable=False, server_default='')
    reconnect_needed = Column(Boolean, nullable=False, server_default='false')
    reconnect_reason = Column(String, nullable=True)
    sync_watermark = Column(BigInteger, nullable=True)


class UserProviderStatusRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: str
    provider_id: str
    entry_id: str | None = None
    connected_at: int
    last_validated_at: int | None = None
    is_valid: bool
    key_last_four: str
    reconnect_needed: bool
    reconnect_reason: str | None = None
    sync_watermark: int | None = None


class UserProviderStatuses:
    @staticmethod
    def upsert(
        user_id: str,
        provider_id: str,
        *,
        entry_id: str | None = None,
        key_last_four: str = '',
        is_valid: bool = True,
        reconnect_needed: bool = False,
        reconnect_reason: str | None = None,
    ) -> UserProviderStatus:
        now = int(time.time())
        with get_db() as db:
            row = db.query(UserProviderStatus).filter_by(
                user_id=user_id, provider_id=provider_id,
            ).first()
            if row:
                row.entry_id = entry_id or row.entry_id
                row.last_validated_at = now
                row.is_valid = is_valid
                row.key_last_four = key_last_four or row.key_last_four
                row.reconnect_needed = reconnect_needed
                row.reconnect_reason = reconnect_reason
                row.sync_watermark = now
            else:
                row = UserProviderStatus(
                    user_id=user_id,
                    provider_id=provider_id,
                    entry_id=entry_id,
                    connected_at=now,
                    last_validated_at=now,
                    is_valid=is_valid,
                    key_last_four=key_last_four,
                    reconnect_needed=reconnect_needed,
                    reconnect_reason=reconnect_reason,
                    sync_watermark=now,
                )
                db.add(row)
            db.commit()
            db.refresh(row)
            return row

    @staticmethod
    def list_for_user(user_id: str) -> list[UserProviderStatusRecord]:
        with get_db() as db:
            rows = db.query(UserProviderStatus).filter_by(user_id=user_id).all()
            return [UserProviderStatusRecord.model_validate(r) for r in rows]

    @staticmethod
    def delete(user_id: str, provider_id: str) -> bool:
        with get_db() as db:
            row = db.query(UserProviderStatus).filter_by(
                user_id=user_id, provider_id=provider_id,
            ).first()
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True

    @staticmethod
    def mark_reconnect_needed(user_id: str, provider_id: str, reason: str) -> None:
        UserProviderStatuses.upsert(
            user_id=user_id,
            provider_id=provider_id,
            is_valid=False,
            reconnect_needed=True,
            reconnect_reason=reason,
        )

    @staticmethod
    def get_any_for_user(user_id: str) -> UserProviderStatusRecord | None:
        rows = UserProviderStatuses.list_for_user(user_id)
        return rows[0] if rows else None
