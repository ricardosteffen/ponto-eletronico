from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from datetime import timedelta
from app.database import get_db
from app.models.models import User
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


class UserCreate(BaseModel):
    nome: str
    email: EmailStr
    matricula: str
    senha: str
    is_admin: bool = False


class UserResponse(BaseModel):
    id: int
    nome: str
    email: str
    matricula: str
    is_admin: bool
    ativo: bool

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

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
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
    # Verifica se email já existe
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email já cadastrado"
        )

    # Verifica se matrícula já existe
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
        is_admin=user_data.is_admin
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


@router.post("/signup", response_model=UserResponse)
async def signup(
    user_data: SignupRequest,
    db: Session = Depends(get_db)
):
    """Auto-cadastro de usuários (sem necessidade de admin)"""
    # Verifica se email já existe
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email já cadastrado"
        )

    # Verifica se matrícula já existe
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
        ativo=True
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
