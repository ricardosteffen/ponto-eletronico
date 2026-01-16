from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date, timedelta
import csv
import io
import os
from app.database import get_db
from app.models.models import User, TimeRecord, CompanySettings, Location
from app.utils.auth import get_current_admin
from config import DEFAULT_COMPANY_LATITUDE, DEFAULT_COMPANY_LONGITUDE, DEFAULT_ALLOWED_RADIUS_METERS
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

router = APIRouter(prefix="/admin", tags=["Administração"])


class UserListResponse(BaseModel):
    id: int
    nome: str
    email: str
    matricula: str
    is_admin: bool
    ativo: bool

    class Config:
        from_attributes = True


class CompanySettingsUpdate(BaseModel):
    nome_empresa: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    raio_permitido_metros: Optional[int] = None


class CompanySettingsResponse(BaseModel):
    id: int
    nome_empresa: str
    latitude: float
    longitude: float
    raio_permitido_metros: int

    class Config:
        from_attributes = True


class RegistroRelatorio(BaseModel):
    id: int
    user_id: int
    nome_funcionario: str
    matricula: str
    tipo: str
    timestamp: datetime
    latitude: Optional[float]
    longitude: Optional[float]
    dentro_raio: bool
    face_detected: Optional[bool] = None


class RelatorioResponse(BaseModel):
    registros: List[RegistroRelatorio]
    total_registros: int
    total_funcionarios: int


class ResumoFuncionario(BaseModel):
    user_id: int
    nome: str
    matricula: str
    total_horas: str
    dias_trabalhados: int
    registros_fora_raio: int


class RelatorioResumoResponse(BaseModel):
    periodo_inicio: date
    periodo_fim: date
    funcionarios: List[ResumoFuncionario]


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


@router.get("/users", response_model=List[UserListResponse])
async def list_users(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    # Super admin vê todos os usuários, admin comum só vê do seu curso
    query = db.query(User)
    if not current_admin.is_super_admin and current_admin.curso_id:
        query = query.filter(User.curso_id == current_admin.curso_id)
    users = query.order_by(User.nome).all()
    return [UserListResponse.model_validate(u) for u in users]


@router.get("/settings", response_model=CompanySettingsResponse)
async def get_settings(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    settings = db.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(
            nome_empresa="Minha Empresa",
            latitude=DEFAULT_COMPANY_LATITUDE,
            longitude=DEFAULT_COMPANY_LONGITUDE,
            raio_permitido_metros=DEFAULT_ALLOWED_RADIUS_METERS
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return CompanySettingsResponse.model_validate(settings)


@router.put("/settings", response_model=CompanySettingsResponse)
async def update_settings(
    settings_data: CompanySettingsUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    settings = db.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(
            nome_empresa="Minha Empresa",
            latitude=DEFAULT_COMPANY_LATITUDE,
            longitude=DEFAULT_COMPANY_LONGITUDE,
            raio_permitido_metros=DEFAULT_ALLOWED_RADIUS_METERS
        )
        db.add(settings)

    if settings_data.nome_empresa is not None:
        settings.nome_empresa = settings_data.nome_empresa
    if settings_data.latitude is not None:
        settings.latitude = settings_data.latitude
    if settings_data.longitude is not None:
        settings.longitude = settings_data.longitude
    if settings_data.raio_permitido_metros is not None:
        settings.raio_permitido_metros = settings_data.raio_permitido_metros

    db.commit()
    db.refresh(settings)
    return CompanySettingsResponse.model_validate(settings)


@router.get("/relatorio", response_model=RelatorioResponse)
async def get_relatorio(
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    if not data_inicio:
        data_inicio = date.today().replace(day=1)
    if not data_fim:
        data_fim = date.today()

    inicio = datetime.combine(data_inicio, datetime.min.time())
    fim = datetime.combine(data_fim, datetime.max.time())

    query = db.query(TimeRecord, User).join(User).filter(
        and_(
            TimeRecord.timestamp >= inicio,
            TimeRecord.timestamp <= fim
        )
    )

    # Filtra por curso se não for super admin
    if not current_admin.is_super_admin and current_admin.curso_id:
        query = query.filter(User.curso_id == current_admin.curso_id)

    if user_id:
        query = query.filter(TimeRecord.user_id == user_id)

    results = query.order_by(TimeRecord.timestamp.desc()).all()

    registros = []
    user_ids = set()
    for record, user in results:
        user_ids.add(user.id)
        registros.append(RegistroRelatorio(
            id=record.id,
            user_id=user.id,
            nome_funcionario=user.nome,
            matricula=user.matricula,
            tipo=record.tipo,
            timestamp=record.timestamp,
            latitude=record.latitude,
            longitude=record.longitude,
            dentro_raio=record.dentro_raio,
            face_detected=record.face_detected
        ))

    return RelatorioResponse(
        registros=registros,
        total_registros=len(registros),
        total_funcionarios=len(user_ids)
    )


@router.get("/relatorio/resumo", response_model=RelatorioResumoResponse)
async def get_relatorio_resumo(
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    if not data_inicio:
        data_inicio = date.today().replace(day=1)
    if not data_fim:
        data_fim = date.today()

    inicio = datetime.combine(data_inicio, datetime.min.time())
    fim = datetime.combine(data_fim, datetime.max.time())

    # Filtra por curso se não for super admin
    query = db.query(User).filter(User.ativo == True)
    if not current_admin.is_super_admin and current_admin.curso_id:
        query = query.filter(User.curso_id == current_admin.curso_id)
    users = query.all()

    funcionarios = []
    for user in users:
        registros = db.query(TimeRecord).filter(
            and_(
                TimeRecord.user_id == user.id,
                TimeRecord.timestamp >= inicio,
                TimeRecord.timestamp <= fim
            )
        ).order_by(TimeRecord.timestamp).all()

        if registros:
            total_horas = calcular_horas_trabalhadas(registros)
            dias_unicos = set(r.timestamp.date() for r in registros)
            fora_raio = sum(1 for r in registros if not r.dentro_raio)

            funcionarios.append(ResumoFuncionario(
                user_id=user.id,
                nome=user.nome,
                matricula=user.matricula,
                total_horas=formatar_horas(total_horas),
                dias_trabalhados=len(dias_unicos),
                registros_fora_raio=fora_raio
            ))

    return RelatorioResumoResponse(
        periodo_inicio=data_inicio,
        periodo_fim=data_fim,
        funcionarios=funcionarios
    )


@router.get("/relatorio/export")
async def export_relatorio(
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    if not data_inicio:
        data_inicio = date.today().replace(day=1)
    if not data_fim:
        data_fim = date.today()

    inicio = datetime.combine(data_inicio, datetime.min.time())
    fim = datetime.combine(data_fim, datetime.max.time())

    query = db.query(TimeRecord, User).join(User).filter(
        and_(
            TimeRecord.timestamp >= inicio,
            TimeRecord.timestamp <= fim
        )
    )

    # Filtra por curso se não for super admin
    if not current_admin.is_super_admin and current_admin.curso_id:
        query = query.filter(User.curso_id == current_admin.curso_id)

    if user_id:
        query = query.filter(TimeRecord.user_id == user_id)

    results = query.order_by(TimeRecord.timestamp).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Data', 'Hora', 'Aluno', 'Matrícula', 'Tipo',
        'Latitude', 'Longitude', 'Dentro do Raio'
    ])

    for record, user in results:
        writer.writerow([
            record.timestamp.strftime('%d/%m/%Y'),
            record.timestamp.strftime('%H:%M:%S'),
            user.nome,
            user.matricula,
            record.tipo.upper(),
            record.latitude or '',
            record.longitude or '',
            'Sim' if record.dentro_raio else 'Não'
        ])

    output.seek(0)
    filename = f"relatorio_ponto_{data_inicio.strftime('%Y%m%d')}_{data_fim.strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


class DeleteResponse(BaseModel):
    message: str
    registros_deletados: int
    fotos_deletadas: int


@router.delete("/registros", response_model=DeleteResponse)
async def delete_registros(
    data_inicio: date,
    data_fim: date,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Apaga registros de ponto em lote por período e opcionalmente por usuário."""
    inicio = datetime.combine(data_inicio, datetime.min.time())
    fim = datetime.combine(data_fim, datetime.max.time())

    # Se não for super admin, filtra por usuários do curso
    if not current_admin.is_super_admin and current_admin.curso_id:
        user_ids_curso = db.query(User.id).filter(User.curso_id == current_admin.curso_id).subquery()
        query = db.query(TimeRecord).filter(
            and_(
                TimeRecord.timestamp >= inicio,
                TimeRecord.timestamp <= fim,
                TimeRecord.user_id.in_(user_ids_curso)
            )
        )
    else:
        query = db.query(TimeRecord).filter(
            and_(
                TimeRecord.timestamp >= inicio,
                TimeRecord.timestamp <= fim
            )
        )

    if user_id:
        query = query.filter(TimeRecord.user_id == user_id)

    registros = query.all()

    if not registros:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum registro encontrado no período especificado"
        )

    fotos_deletadas = 0
    for registro in registros:
        # Remove arquivo de foto se existir
        if registro.foto_path and os.path.exists(registro.foto_path):
            try:
                os.remove(registro.foto_path)
                fotos_deletadas += 1
            except Exception:
                pass  # Ignora erros ao deletar arquivos

    registros_count = len(registros)

    # Deleta registros do banco
    query.delete(synchronize_session=False)
    db.commit()

    return DeleteResponse(
        message=f"Registros deletados com sucesso",
        registros_deletados=registros_count,
        fotos_deletadas=fotos_deletadas
    )


@router.get("/relatorio/export/pdf")
async def export_relatorio_pdf(
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Exporta relatório em formato PDF."""
    if not data_inicio:
        data_inicio = date.today().replace(day=1)
    if not data_fim:
        data_fim = date.today()

    inicio = datetime.combine(data_inicio, datetime.min.time())
    fim = datetime.combine(data_fim, datetime.max.time())

    query = db.query(TimeRecord, User).join(User).filter(
        and_(
            TimeRecord.timestamp >= inicio,
            TimeRecord.timestamp <= fim
        )
    )

    # Filtra por curso se não for super admin
    if not current_admin.is_super_admin and current_admin.curso_id:
        query = query.filter(User.curso_id == current_admin.curso_id)

    if user_id:
        query = query.filter(TimeRecord.user_id == user_id)

    results = query.order_by(TimeRecord.timestamp).all()

    # Cria PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1*cm,
        leftMargin=1*cm,
        topMargin=1*cm,
        bottomMargin=1*cm
    )

    elements = []
    styles = getSampleStyleSheet()

    # Título
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=20,
        alignment=1  # Center
    )
    title = Paragraph(
        f"Relatório de Presença<br/>{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}",
        title_style
    )
    elements.append(title)
    elements.append(Spacer(1, 0.5*cm))

    # Tabela de dados
    data = [['Data', 'Hora', 'Aluno', 'Matrícula', 'Tipo', 'Localização', 'Raio', 'Rosto']]

    for record, user in results:
        face_status = ''
        if record.face_detected is not None:
            face_status = 'Sim' if record.face_detected else 'Não'

        data.append([
            record.timestamp.strftime('%d/%m/%Y'),
            record.timestamp.strftime('%H:%M'),
            user.nome[:25],  # Limita tamanho do nome
            user.matricula,
            record.tipo.upper(),
            f"{record.latitude:.4f}, {record.longitude:.4f}" if record.latitude else '-',
            'OK' if record.dentro_raio else 'Fora',
            face_status
        ])

    # Estilo da tabela
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.24, 0.48, 0.48)),  # Cor PUC
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.Color(0.95, 0.95, 0.95)]),
    ]))

    elements.append(table)

    # Resumo
    elements.append(Spacer(1, 1*cm))
    summary = Paragraph(
        f"<b>Total de registros:</b> {len(results)}",
        styles['Normal']
    )
    elements.append(summary)

    doc.build(elements)
    buffer.seek(0)

    filename = f"relatorio_presenca_{data_inicio.strftime('%Y%m%d')}_{data_fim.strftime('%Y%m%d')}.pdf"

    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============= LOCAIS =============

class LocationCreate(BaseModel):
    nome: str
    latitude: float
    longitude: float
    raio_metros: int = 100


class LocationUpdate(BaseModel):
    nome: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    raio_metros: Optional[int] = None
    ativo: Optional[bool] = None


class LocationResponse(BaseModel):
    id: int
    nome: str
    latitude: float
    longitude: float
    raio_metros: int
    ativo: bool

    class Config:
        from_attributes = True


@router.get("/locations", response_model=List[LocationResponse])
async def list_locations(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Lista todos os locais cadastrados do curso."""
    query = db.query(Location)
    # Filtra por curso se não for super admin
    if not current_admin.is_super_admin and current_admin.curso_id:
        query = query.filter(Location.curso_id == current_admin.curso_id)
    locations = query.order_by(Location.nome).all()
    return [LocationResponse.model_validate(loc) for loc in locations]


@router.post("/locations", response_model=LocationResponse)
async def create_location(
    location_data: LocationCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Cria um novo local para o curso do admin."""
    # Define o curso_id baseado no admin (super admin pode não ter curso)
    curso_id = current_admin.curso_id

    location = Location(
        nome=location_data.nome,
        latitude=location_data.latitude,
        longitude=location_data.longitude,
        raio_metros=location_data.raio_metros,
        curso_id=curso_id
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return LocationResponse.model_validate(location)


@router.put("/locations/{location_id}", response_model=LocationResponse)
async def update_location(
    location_id: int,
    location_data: LocationUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Atualiza um local existente."""
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local não encontrado"
        )

    # Verifica permissão do admin no curso do local
    if not current_admin.is_super_admin and location.curso_id != current_admin.curso_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para modificar este local"
        )

    if location_data.nome is not None:
        location.nome = location_data.nome
    if location_data.latitude is not None:
        location.latitude = location_data.latitude
    if location_data.longitude is not None:
        location.longitude = location_data.longitude
    if location_data.raio_metros is not None:
        location.raio_metros = location_data.raio_metros
    if location_data.ativo is not None:
        location.ativo = location_data.ativo

    db.commit()
    db.refresh(location)
    return LocationResponse.model_validate(location)


@router.delete("/locations/{location_id}")
async def delete_location(
    location_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Remove um local."""
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local não encontrado"
        )

    # Verifica permissão do admin no curso do local
    if not current_admin.is_super_admin and location.curso_id != current_admin.curso_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para remover este local"
        )

    db.delete(location)
    db.commit()
    return {"message": "Local removido com sucesso"}
