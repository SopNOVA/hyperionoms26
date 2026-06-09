from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class OLT(Base):
    __tablename__ = "olts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    ip_address = Column(String(45), nullable=False, index=True)  # OLT management / ping IP
    location = Column(String(255), nullable=True)
    model = Column(String(100), nullable=True)
    firmware = Column(String(100), nullable=True)

    is_active = Column(Boolean, default=True)
    # Status derived or set by sensor: UP, DOWN, DEGRADED
    status = Column(String(20), default="UP", index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_ping_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    onts = relationship("Ont", back_populates="olt", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<OLT(id={self.id}, name={self.name}, status={self.status})>"
