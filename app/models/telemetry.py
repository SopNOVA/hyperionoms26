from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id = Column(Integer, primary_key=True, index=True)

    ont_id = Column(Integer, ForeignKey("onts.id"), nullable=False, index=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Campos normalizados para consultas rápidas
    classification = Column(String(50), index=True)  # GOOD, REGULAR, BAD, CRITICAL
    reason = Column(String(255), nullable=True)

    wan_ip = Column(String(45), nullable=True)
    ping_8_avg = Column(Float, nullable=True)
    ping_1_avg = Column(Float, nullable=True)
    tcp_retrans_segs = Column(Integer, nullable=True)

    # Datos completos del agente (flexible)
    data = Column(JSON, nullable=False)

    # Tipo de entrega
    delivery = Column(String(20), default="live")  # live, diagnostic, etc.

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    ont = relationship("Ont", back_populates="telemetry_events")

    def __repr__(self):
        return f"<TelemetryEvent(id={self.id}, ont_id={self.ont_id}, classification={self.classification})>"
