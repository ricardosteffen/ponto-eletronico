from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models.models import User, Curso, Location, TimeRecord
from app.utils.auth import get_current_super_admin, get_password_hash

router = APIRouter(prefix="/api/super-admin", tags=["Super Admin"])


# ============= SCHEMAS =============

class CursoCreate(BaseModel):
    nome: str
    slug: str


class CursoUpdate(BaseModel):
    nome: Optional[str] = None
    slug: Optional[str] = None
    ativo: Optional[bool] = None


class CursoResponse(BaseModel):
    id: int
    nome: str
    slug: str
    ativo: bool
    created_at: datetime
    total_alunos: int = 0
    total_locais: int = 0

    class Config:
        from_attributes = True


class AdminCreate(BaseModel):
    nome: str
    email: EmailStr
    matricula: str
    senha: str
    curso_id: int


class AdminResponse(BaseModel):
    id: int
    nome: str
    email: str
    matricula: str
    is_admin: bool
    curso_id: Optional[int]
    curso_nome: Optional[str] = None

    class Config:
        from_attributes = True


class CursoStats(BaseModel):
    curso_id: int
    curso_nome: str
    total_alunos: int
    total_admins: int
    total_locais: int
    total_registros: int


# ============= ROTAS DE CURSOS =============

@router.get("/cursos", response_model=List[CursoResponse])
async def list_cursos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_super_admin)
):
    """Lista todos os cursos."""
    cursos = db.query(Curso).order_by(Curso.nome).all()

    result = []
    for curso in cursos:
        total_alunos = db.query(User).filter(User.curso_id == curso.id).count()
        total_locais = db.query(Location).filter(Location.curso_id == curso.id).count()

        curso_data = CursoResponse(
            id=curso.id,
            nome=curso.nome,
            slug=curso.slug,
            ativo=curso.ativo,
            created_at=curso.created_at,
            total_alunos=total_alunos,
            total_locais=total_locais
        )
        result.append(curso_data)

    return result


@router.post("/cursos", response_model=CursoResponse)
async def create_curso(
    curso_data: CursoCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_super_admin)
):
    """Cria um novo curso."""
    # Verifica se slug já existe
    existing = db.query(Curso).filter(Curso.slug == curso_data.slug.lower()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um curso com este slug"
        )

    curso = Curso(
        nome=curso_data.nome,
        slug=curso_data.slug.lower()
    )
    db.add(curso)
    db.commit()
    db.refresh(curso)

    return CursoResponse(
        id=curso.id,
        nome=curso.nome,
        slug=curso.slug,
        ativo=curso.ativo,
        created_at=curso.created_at,
        total_alunos=0,
        total_locais=0
    )


@router.put("/cursos/{curso_id}", response_model=CursoResponse)
async def update_curso(
    curso_id: int,
    curso_data: CursoUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_super_admin)
):
    """Atualiza um curso existente."""
    curso = db.query(Curso).filter(Curso.id == curso_id).first()
    if not curso:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curso não encontrado"
        )

    if curso_data.nome is not None:
        curso.nome = curso_data.nome
    if curso_data.slug is not None:
        # Verifica se novo slug já existe
        existing = db.query(Curso).filter(
            Curso.slug == curso_data.slug.lower(),
            Curso.id != curso_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Já existe um curso com este slug"
            )
        curso.slug = curso_data.slug.lower()
    if curso_data.ativo is not None:
        curso.ativo = curso_data.ativo

    db.commit()
    db.refresh(curso)

    total_alunos = db.query(User).filter(User.curso_id == curso.id).count()
    total_locais = db.query(Location).filter(Location.curso_id == curso.id).count()

    return CursoResponse(
        id=curso.id,
        nome=curso.nome,
        slug=curso.slug,
        ativo=curso.ativo,
        created_at=curso.created_at,
        total_alunos=total_alunos,
        total_locais=total_locais
    )


@router.delete("/cursos/{curso_id}")
async def delete_curso(
    curso_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_super_admin)
):
    """Remove um curso (apenas se não tiver usuários)."""
    curso = db.query(Curso).filter(Curso.id == curso_id).first()
    if not curso:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curso não encontrado"
        )

    # Verifica se tem usuários
    total_users = db.query(User).filter(User.curso_id == curso_id).count()
    if total_users > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não é possível remover o curso. Existem {total_users} usuários cadastrados."
        )

    # Remove locais do curso
    db.query(Location).filter(Location.curso_id == curso_id).delete()

    db.delete(curso)
    db.commit()

    return {"message": "Curso removido com sucesso"}


# ============= ROTAS DE ADMINS =============

@router.get("/admins", response_model=List[AdminResponse])
async def list_admins(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_super_admin)
):
    """Lista todos os administradores de todos os cursos."""
    admins = db.query(User).filter(
        (User.is_admin == True) | (User.is_super_admin == True)
    ).order_by(User.nome).all()

    result = []
    for admin in admins:
        curso_nome = None
        if admin.curso_id:
            curso = db.query(Curso).filter(Curso.id == admin.curso_id).first()
            curso_nome = curso.nome if curso else None

        result.append(AdminResponse(
            id=admin.id,
            nome=admin.nome,
            email=admin.email,
            matricula=admin.matricula,
            is_admin=admin.is_admin,
            curso_id=admin.curso_id,
            curso_nome=curso_nome if not admin.is_super_admin else "Super Admin"
        ))

    return result


@router.post("/admins", response_model=AdminResponse)
async def create_admin(
    admin_data: AdminCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_super_admin)
):
    """Cria um administrador para um curso."""
    # Verifica se curso existe
    curso = db.query(Curso).filter(Curso.id == admin_data.curso_id).first()
    if not curso:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curso não encontrado"
        )

    # Verifica se email já existe no curso
    existing = db.query(User).filter(
        User.email == admin_data.email,
        User.curso_id == admin_data.curso_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um usuário com este email neste curso"
        )

    admin = User(
        nome=admin_data.nome,
        email=admin_data.email,
        matricula=admin_data.matricula,
        senha_hash=get_password_hash(admin_data.senha),
        is_admin=True,
        curso_id=admin_data.curso_id
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    return AdminResponse(
        id=admin.id,
        nome=admin.nome,
        email=admin.email,
        matricula=admin.matricula,
        is_admin=admin.is_admin,
        curso_id=admin.curso_id,
        curso_nome=curso.nome
    )


# ============= ESTATÍSTICAS =============

@router.get("/stats", response_model=List[CursoStats])
async def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_super_admin)
):
    """Retorna estatísticas de todos os cursos."""
    cursos = db.query(Curso).all()

    stats = []
    for curso in cursos:
        total_alunos = db.query(User).filter(
            User.curso_id == curso.id,
            User.is_admin == False
        ).count()

        total_admins = db.query(User).filter(
            User.curso_id == curso.id,
            User.is_admin == True
        ).count()

        total_locais = db.query(Location).filter(
            Location.curso_id == curso.id
        ).count()

        # Registros dos usuários do curso
        user_ids = db.query(User.id).filter(User.curso_id == curso.id).subquery()
        total_registros = db.query(TimeRecord).filter(
            TimeRecord.user_id.in_(user_ids)
        ).count()

        stats.append(CursoStats(
            curso_id=curso.id,
            curso_nome=curso.nome,
            total_alunos=total_alunos,
            total_admins=total_admins,
            total_locais=total_locais,
            total_registros=total_registros
        ))

    return stats
