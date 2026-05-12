import time
import uuid

from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Index, Integer, String, UniqueConstraint

####################
# Container Registry DB Schema
# Each user owns one container. This table is the ledger that
# maps user identity to the living space the container holds.
####################


class Container(Base):
    __tablename__ = 'container'

    id = Column(String, primary_key=True, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)

    # Docker internals
    container_id = Column(String, nullable=True)  # full Docker container ID (64 chars)
    container_name = Column(String, nullable=True)  # myah-agent-{user_id}

    # Networking — port on the host that maps to container's 8642
    host_port = Column(Integer, nullable=True)
    # Port on the host that maps to container's Vite dev server (5174)
    vite_port = Column(Integer, nullable=True)
    # Port on the host that maps to container's VNC server (5900)
    vnc_port = Column(Integer, nullable=True)
    # Port on the host that maps to container's `hermes dashboard` (9119).
    # See routers/containers.py + utils/hermes_web.py (Workstream A Phase 0).
    web_port = Column(Integer, nullable=True)
    # Port on the host that maps to container's standalone Myah adapter
    # (8643 — MYAH_GATEWAY_PORT inside the container). Tier 2A standalone-
    # runner refactor moved /myah/v1/* and /myah/health off the API server's
    # 8642 onto a plugin-owned aiohttp app. NULL for containers spawned
    # before this column was added — readers fall back to host_port.
    gateway_port = Column(Integer, nullable=True)
    # Per-container bearer token used by the platform to authenticate
    # against the hermes dashboard server / myah-admin plugin routes.
    # Mirrors the HERMES_WEB_SESSION_TOKEN env var injected on docker run.
    web_session_token = Column(String, nullable=True)

    # Lifecycle: 'creating' | 'running' | 'hibernated' | 'error'
    status = Column(String, nullable=False, default='creating')

    # Timestamps (epoch seconds)
    created_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))
    last_active = Column(BigInteger, nullable=False, default=lambda: int(time.time()))

    __table_args__ = (
        UniqueConstraint('user_id', name='uq_container_user_id'),
        Index('container_status_idx', 'status'),
        Index('container_last_active_idx', 'last_active'),
    )


class ContainerModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    container_id: str | None = None
    container_name: str | None = None
    host_port: int | None = None
    vite_port: int | None = None
    vnc_port: int | None = None
    web_port: int | None = None
    gateway_port: int | None = None
    web_session_token: str | None = None
    status: str
    created_at: int
    last_active: int


class ContainerTable:
    def get_by_user_id(self, user_id: str) -> ContainerModel | None:
        with get_db() as db:
            row = db.query(Container).filter_by(user_id=user_id).first()
            return ContainerModel.model_validate(row) if row else None

    def create(self, user_id: str) -> ContainerModel:
        with get_db() as db:
            row = Container(
                id=str(uuid.uuid4()),
                user_id=user_id,
                status='creating',
                created_at=int(time.time()),
                last_active=int(time.time()),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return ContainerModel.model_validate(row)

    def update_status(
        self,
        user_id: str,
        *,
        status: str,
        container_id: str | None = None,
        container_name: str | None = None,
        host_port: int | None = None,
        vite_port: int | None = None,
        vnc_port: int | None = None,
        web_port: int | None = None,
        gateway_port: int | None = None,
        web_session_token: str | None = None,
    ) -> ContainerModel | None:
        with get_db() as db:
            row = db.query(Container).filter_by(user_id=user_id).first()
            if not row:
                return None
            row.status = status
            if container_id is not None:
                row.container_id = container_id
            if container_name is not None:
                row.container_name = container_name
            if host_port is not None:
                row.host_port = host_port
            if vite_port is not None:
                row.vite_port = vite_port
            if vnc_port is not None:
                row.vnc_port = vnc_port
            if web_port is not None:
                row.web_port = web_port
            if gateway_port is not None:
                row.gateway_port = gateway_port
            if web_session_token is not None:
                row.web_session_token = web_session_token
            row.last_active = int(time.time())
            db.commit()
            db.refresh(row)
            return ContainerModel.model_validate(row)

    def touch(self, user_id: str) -> None:
        """Update last_active to now — call on every successful message route."""
        with get_db() as db:
            row = db.query(Container).filter_by(user_id=user_id).first()
            if row:
                row.last_active = int(time.time())
                db.commit()

    def get_idle(self, idle_seconds: int) -> list[ContainerModel]:
        """Return running containers idle for more than idle_seconds."""
        cutoff = int(time.time()) - idle_seconds
        with get_db() as db:
            rows = db.query(Container).filter(Container.status == 'running', Container.last_active < cutoff).all()
            return [ContainerModel.model_validate(r) for r in rows]

    def delete(self, user_id: str) -> bool:
        with get_db() as db:
            deleted = db.query(Container).filter_by(user_id=user_id).delete()
            db.commit()
            return deleted > 0

    def reconcile_with_running_containers(self, running_names: set[str]) -> int:
        """Mark as 'stopped' any 'running' DB row whose container is not in running_names.

        Defensive truth-up on platform startup. The deploy workflow's
        'stop stale per-user agent containers' step kills Docker containers
        without touching the DB; without this reconciliation, _get_container_port's
        short-circuit would return a dead host_port on every aux_call until
        each user's first idle-probe fired.

        Returns the number of rows marked stopped.
        """
        with get_db() as db:
            rows = db.query(Container).filter_by(status='running').all()
            fixed = 0
            for row in rows:
                if row.container_name and row.container_name not in running_names:
                    row.status = 'stopped'
                    fixed += 1
            if fixed:
                db.commit()
            return fixed


Containers = ContainerTable()
