from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Ont(Base):
    __tablename__ = "onts"

    id = Column(Integer, primary_key=True, index=True)

    # Identificador principal de la ONU
    gpon_sn = Column(String(50), unique=True, index=True, nullable=False)  # GPON Serial Number
    mac_address = Column(String(17), unique=True, index=True, nullable=True)  # e.g. AA:BB:CC:DD:EE:FF
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6

    model = Column(String(100), nullable=True)
    firmware = Column(String(100), nullable=True)

    # Asociación con OLT y cliente
    olt_id = Column(Integer, ForeignKey("olts.id"), nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)

    # Ubicación / metadatos
    location = Column(String(255), nullable=True)  # zona, barrio, coordenadas, etc.
    notes = Column(String(1000), nullable=True)

    # Estado
    is_active = Column(Boolean, default=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    customer = relationship("Customer", back_populates="onts")
    olt = relationship("OLT", back_populates="onts")
    telemetry_events = relationship("TelemetryEvent", back_populates="ont", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Ont(id={self.id}, gpon_sn={self.gpon_sn}, customer_id={self.customer_id})>"
