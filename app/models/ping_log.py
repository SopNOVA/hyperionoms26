from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base

class PingLog(Base):
    __tablename__ = "ping_logs"

    id = Column(Integer, primary_key=True, index=True)
    target_type = Column(String(10), nullable=False)  # 'ont' or 'olt'
    target_id = Column(Integer, nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    status = Column(String(10), nullable=False)  # UP or DOWN
    ping_ms = Column(Float, nullable=True)
    error = Column(String(255), nullable=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self):
        return f"<PingLog({self.target_type}:{self.target_id} {self.status} {self.ping_ms}ms)>"
