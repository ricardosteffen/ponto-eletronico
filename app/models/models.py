from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta
from app.database import Base

# Timezone Brasil (UTC-3)
BRAZIL_TZ = timezone(timedelta(hours=-3))

def now_brazil():
    return datetime.now(BRAZIL_TZ)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    matricula = Column(String(20), unique=True, index=True, nullable=False)
    senha_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    ativo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_brazil)
    updated_at = Column(DateTime, default=now_brazil, onupdate=now_brazil)

    registros = relationship("TimeRecord", back_populates="usuario")


class TimeRecord(Base):
    __tablename__ = "time_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tipo = Column(String(10), nullable=False)  # 'entrada' ou 'saida'
    timestamp = Column(DateTime, default=now_brazil, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    foto_path = Column(String(255), nullable=True)
    dentro_raio = Column(Boolean, default=True)
    observacao = Column(Text, nullable=True)
    face_detected = Column(Boolean, nullable=True)  # Rosto detectado na foto?
    face_count = Column(Integer, nullable=True)     # Quantidade de rostos detectados
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)  # Local onde registrou

    usuario = relationship("User", back_populates="registros")
    local = relationship("Location")


class CompanySettings(Base):
    __tablename__ = "company_settings"

    id = Column(Integer, primary_key=True, index=True)
    nome_empresa = Column(String(200), default="Minha Empresa")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    raio_permitido_metros = Column(Integer, default=100)
    created_at = Column(DateTime, default=now_brazil)
    updated_at = Column(DateTime, default=now_brazil, onupdate=now_brazil)


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)  # Ex: "Campus PUC", "Hospital", etc.
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    raio_metros = Column(Integer, default=100)
    ativo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_brazil)
    updated_at = Column(DateTime, default=now_brazil, onupdate=now_brazil)
