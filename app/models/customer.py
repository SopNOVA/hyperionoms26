from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    document = Column(String(50), unique=True, index=True, nullable=True)  # cédula, NIT, etc.
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    address = Column(String(500), nullable=True)
    mac_address = Column(String(17), unique=True, index=True, nullable=True)  # Primary ONT MAC for matching
    gpon_sn = Column(String(50), unique=True, index=True, nullable=True)  # Primary GPON for quick match

    # Optional extra fields for ISP
    plan = Column(String(100), nullable=True)
    installation_date = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship
    onts = relationship("Ont", back_populates="customer", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Customer(id={self.id}, name={self.name})>"
