from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import timedelta
from app.database import get_db
from app.models.models import User, Curso
from app.utils.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
    get_current_admin
)
from config import ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/auth", tags=["Autenticação"])


class LoginRequest(BaseModel):
    email: str
    senha: str
    curso_id: Optional[int] = None  # Opcional para login de super admin


class UserCreate(BaseModel):
    nome: str
    email: EmailStr
    matricula: str
    senha: str
    is_admin: bool = False
    curso_id: Optional[int] = None


class UserResponse(BaseModel):
    id: int
    nome: str
    email: str
    matricula: str
    is_admin: bool
    is_super_admin: bool = False
    ativo: bool
    curso_id: Optional[int] = None
    curso_slug: Optional[str] = None
    curso_nome: Optional[str] = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    # Se curso_id especificado, busca usuário no curso específico
    if login_data.curso_id:
        user = db.query(User).filter(
            User.email == login_data.email,
            User.curso_id == login_data.curso_id
        ).first()
    else:
        # Login sem curso_id - busca primeiro por super admin, depois por qualquer usuário
        user = db.query(User).filter(
            User.email == login_data.email,
            User.is_super_admin == True
        ).first()
        if not user:
            # Fallback para usuário comum (compatibilidade com login antigo)
            user = db.query(User).filter(User.email == login_data.email).first()

    if not user or not verify_password(login_data.senha, user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos"
        )

    if not user.ativo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo. Contate o administrador."
        )

    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )

    # Busca informações do curso para a resposta
    curso_slug = None
    curso_nome = None
    if user.curso_id:
        curso = db.query(Curso).filter(Curso.id == user.curso_id).first()
        if curso:
            curso_slug = curso.slug
            curso_nome = curso.nome

    user_response = UserResponse(
        id=user.id,
        nome=user.nome,
        email=user.email,
        matricula=user.matricula,
        is_admin=user.is_admin,
        is_super_admin=user.is_super_admin,
        ativo=user.ativo,
        curso_id=user.curso_id,
        curso_slug=curso_slug,
        curso_nome=curso_nome
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=user_response
    )


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logout realizado com sucesso"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.post("/register", response_model=UserResponse)
async def register_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    # Determina o curso_id: usa o especificado ou herda do admin
    curso_id = user_data.curso_id
    if curso_id is None and not current_admin.is_super_admin:
        curso_id = current_admin.curso_id

    # Verifica se email já existe no curso
    email_query = db.query(User).filter(User.email == user_data.email)
    if curso_id:
        email_query = email_query.filter(User.curso_id == curso_id)
    if email_query.first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email já cadastrado" + (" neste curso" if curso_id else "")
        )

    # Verifica se matrícula já existe no curso
    matricula_query = db.query(User).filter(User.matricula == user_data.matricula)
    if curso_id:
        matricula_query = matricula_query.filter(User.curso_id == curso_id)
    if matricula_query.first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Matrícula já cadastrada" + (" neste curso" if curso_id else "")
        )

    new_user = User(
        nome=user_data.nome,
        email=user_data.email,
        matricula=user_data.matricula,
        senha_hash=get_password_hash(user_data.senha),
        is_admin=user_data.is_admin,
        curso_id=curso_id
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return UserResponse.model_validate(new_user)


@router.put("/users/{user_id}/toggle-active", response_model=UserResponse)
async def toggle_user_active(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )

    # Verifica se o admin tem permissão no curso do usuário
    if not current_admin.is_super_admin and user.curso_id != current_admin.curso_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para modificar este usuário"
        )

    if user.id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você não pode desativar sua própria conta"
        )

    user.ativo = not user.ativo
    db.commit()
    db.refresh(user)

    return UserResponse.model_validate(user)


class SignupRequest(BaseModel):
    nome: str
    email: EmailStr
    matricula: str
    senha: str
    curso_id: Optional[int] = None


@router.post("/signup", response_model=UserResponse)
async def signup(
    user_data: SignupRequest,
    db: Session = Depends(get_db)
):
    """Auto-cadastro de usuários (sem necessidade de admin)"""
    # Se curso_id especificado, valida que o curso existe
    if user_data.curso_id:
        curso = db.query(Curso).filter(
            Curso.id == user_data.curso_id,
            Curso.ativo == True
        ).first()
        if not curso:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Curso não encontrado ou inativo"
            )

        # Verifica se email já existe no curso
        if db.query(User).filter(
            User.email == user_data.email,
            User.curso_id == user_data.curso_id
        ).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email já cadastrado neste curso"
            )

        # Verifica se matrícula já existe no curso
        if db.query(User).filter(
            User.matricula == user_data.matricula,
            User.curso_id == user_data.curso_id
        ).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Matrícula já cadastrada neste curso"
            )
    else:
        # Cadastro sem curso (fallback para compatibilidade)
        # Verifica se email já existe globalmente
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email já cadastrado"
            )

        # Verifica se matrícula já existe globalmente
        if db.query(User).filter(User.matricula == user_data.matricula).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Matrícula já cadastrada"
            )

    new_user = User(
        nome=user_data.nome,
        email=user_data.email,
        matricula=user_data.matricula,
        senha_hash=get_password_hash(user_data.senha),
        is_admin=False,  # Auto-cadastro nunca é admin
        ativo=True,
        curso_id=user_data.curso_id
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return UserResponse.model_validate(new_user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Apagar usuário (apenas admin)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )

    # Verifica se o admin tem permissão no curso do usuário
    if not current_admin.is_super_admin and user.curso_id != current_admin.curso_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para apagar este usuário"
        )

    if user.id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você não pode apagar sua própria conta"
        )

    # Importa TimeRecord aqui para evitar import circular
    from app.models.models import TimeRecord

    # Apaga registros de ponto do usuário
    db.query(TimeRecord).filter(TimeRecord.user_id == user_id).delete()

    # Apaga usuário
    db.delete(user)
    db.commit()

    return {"message": f"Usuário {user.nome} apagado com sucesso"}
