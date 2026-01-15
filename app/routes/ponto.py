from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date, timedelta
import os
import uuid
from app.database import get_db
from app.models.models import User, TimeRecord, CompanySettings, Location
from app.utils.auth import get_current_user
from app.utils.geo import is_within_radius
from app.utils.face import detect_face
from config import UPLOAD_FOLDER, DEFAULT_COMPANY_LATITUDE, DEFAULT_COMPANY_LONGITUDE, DEFAULT_ALLOWED_RADIUS_METERS

router = APIRouter(prefix="/ponto", tags=["Ponto"])


class RegistroPontoRequest(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    observacao: Optional[str] = None


class RegistroPontoResponse(BaseModel):
    id: int
    tipo: str
    timestamp: datetime
    latitude: Optional[float]
    longitude: Optional[float]
    dentro_raio: bool
    observacao: Optional[str]
    distancia_metros: Optional[float] = None
    face_detected: Optional[bool] = None
    face_count: Optional[int] = None
    location_id: Optional[int] = None
    location_name: Optional[str] = None

    class Config:
        from_attributes = True


class HistoricoResponse(BaseModel):
    registros: List[RegistroPontoResponse]
    total_horas_periodo: str
    dias_trabalhados: int


class StatusPontoResponse(BaseModel):
    pode_bater: str  # 'entrada' ou 'saida'
    ultimo_registro: Optional[RegistroPontoResponse]
    registros_hoje: List[RegistroPontoResponse]
    horas_hoje: str


def get_company_settings(db: Session) -> CompanySettings:
    settings = db.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(
            latitude=DEFAULT_COMPANY_LATITUDE,
            longitude=DEFAULT_COMPANY_LONGITUDE,
            raio_permitido_metros=DEFAULT_ALLOWED_RADIUS_METERS
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def check_all_locations(db: Session, user_lat: float, user_lon: float):
    """
    Verifica se o usuário está dentro do raio de algum local cadastrado.
    Retorna: (dentro_raio, distancia, location_id, location_name)
    """
    locations = db.query(Location).filter(Location.ativo == True).all()

    if not locations:
        # Se não há locais cadastrados, usa as configurações da empresa
        settings = get_company_settings(db)
        dentro_raio, distancia = is_within_radius(
            user_lat, user_lon,
            settings.latitude, settings.longitude,
            settings.raio_permitido_metros
        )
        return dentro_raio, distancia, None, None

    # Verifica cada local e retorna o mais próximo que está dentro do raio
    melhor_match = None
    menor_distancia = float('inf')

    for loc in locations:
        dentro, dist = is_within_radius(
            user_lat, user_lon,
            loc.latitude, loc.longitude,
            loc.raio_metros
        )
        if dentro and dist < menor_distancia:
            melhor_match = loc
            menor_distancia = dist

    if melhor_match:
        return True, menor_distancia, melhor_match.id, melhor_match.nome

    # Se não está em nenhum local, retorna o mais próximo
    for loc in locations:
        _, dist = is_within_radius(
            user_lat, user_lon,
            loc.latitude, loc.longitude,
            loc.raio_metros
        )
        if dist < menor_distancia:
            menor_distancia = dist

    return False, menor_distancia, None, None


def calcular_horas_trabalhadas(registros: List[TimeRecord]) -> timedelta:
    total = timedelta()
    entrada = None

    for reg in sorted(registros, key=lambda x: x.timestamp):
        if reg.tipo == 'entrada':
            entrada = reg.timestamp
        elif reg.tipo == 'saida' and entrada:
            total += reg.timestamp - entrada
            entrada = None

    return total


def formatar_horas(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


@router.get("/status", response_model=StatusPontoResponse)
async def get_status_ponto(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    hoje = date.today()
    inicio_dia = datetime.combine(hoje, datetime.min.time())
    fim_dia = datetime.combine(hoje, datetime.max.time())

    registros_hoje = db.query(TimeRecord).filter(
        and_(
            TimeRecord.user_id == current_user.id,
            TimeRecord.timestamp >= inicio_dia,
            TimeRecord.timestamp <= fim_dia
        )
    ).order_by(TimeRecord.timestamp.desc()).all()

    ultimo_registro = registros_hoje[0] if registros_hoje else None

    # Determina próximo tipo de registro
    if not ultimo_registro or ultimo_registro.tipo == 'saida':
        pode_bater = 'entrada'
    else:
        pode_bater = 'saida'

    # Calcula horas trabalhadas hoje
    horas_hoje = calcular_horas_trabalhadas(registros_hoje)

    return StatusPontoResponse(
        pode_bater=pode_bater,
        ultimo_registro=RegistroPontoResponse.model_validate(ultimo_registro) if ultimo_registro else None,
        registros_hoje=[RegistroPontoResponse.model_validate(r) for r in reversed(registros_hoje)],
        horas_hoje=formatar_horas(horas_hoje)
    )


@router.post("/registrar", response_model=RegistroPontoResponse)
async def registrar_ponto(
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    observacao: Optional[str] = Form(None),
    foto: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # VALIDAÇÃO: Geolocalização é obrigatória
    if latitude is None or longitude is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Geolocalização é obrigatória. Permita o acesso ao GPS."
        )

    # Verifica último registro para determinar tipo
    ultimo_registro = db.query(TimeRecord).filter(
        TimeRecord.user_id == current_user.id
    ).order_by(TimeRecord.timestamp.desc()).first()

    if not ultimo_registro or ultimo_registro.tipo == 'saida':
        tipo = 'entrada'
    else:
        tipo = 'saida'

    # Valida geolocalização contra todos os locais cadastrados
    dentro_raio, distancia, location_id, location_name = check_all_locations(
        db, latitude, longitude
    )

    # Processa foto se enviada
    foto_path = None
    face_detected = None
    face_count = None

    if foto:
        ext = os.path.splitext(foto.filename)[1] if foto.filename else '.jpg'
        filename = f"{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        content = await foto.read()

        with open(filepath, "wb") as f:
            f.write(content)

        foto_path = filepath

        # Detecta rosto na foto
        face_result = detect_face(content)
        face_detected = face_result["face_detected"]
        face_count = face_result["face_count"]

    # Cria registro
    novo_registro = TimeRecord(
        user_id=current_user.id,
        tipo=tipo,
        latitude=latitude,
        longitude=longitude,
        foto_path=foto_path,
        dentro_raio=dentro_raio,
        observacao=observacao,
        face_detected=face_detected,
        face_count=face_count,
        location_id=location_id
    )

    db.add(novo_registro)
    db.commit()
    db.refresh(novo_registro)

    response = RegistroPontoResponse.model_validate(novo_registro)
    response.distancia_metros = distancia
    response.location_name = location_name

    return response


@router.get("/historico", response_model=HistoricoResponse)
async def get_historico(
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not data_inicio:
        data_inicio = date.today().replace(day=1)
    if not data_fim:
        data_fim = date.today()

    inicio = datetime.combine(data_inicio, datetime.min.time())
    fim = datetime.combine(data_fim, datetime.max.time())

    registros = db.query(TimeRecord).filter(
        and_(
            TimeRecord.user_id == current_user.id,
            TimeRecord.timestamp >= inicio,
            TimeRecord.timestamp <= fim
        )
    ).order_by(TimeRecord.timestamp.asc()).all()

    # Calcula total de horas
    total_horas = calcular_horas_trabalhadas(registros)

    # Conta dias únicos trabalhados
    dias_unicos = set(r.timestamp.date() for r in registros)

    return HistoricoResponse(
        registros=[RegistroPontoResponse.model_validate(r) for r in registros],
        total_horas_periodo=formatar_horas(total_horas),
        dias_trabalhados=len(dias_unicos)
    )
