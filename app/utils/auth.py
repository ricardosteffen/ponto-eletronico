from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import sys
sys.path.append('../..')
from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import get_db
from app.models.models import User, Curso

security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_token_from_request(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    token = request.cookies.get("access_token")
    return token


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = None
    if credentials:
        token = credentials.credentials
    else:
        token = get_token_from_request(request)

    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    if not user.ativo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo"
        )
    return user


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin and not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso permitido apenas para administradores"
        )
    return current_user


async def get_current_super_admin(current_user: User = Depends(get_current_user)) -> User:
    """Verifica se o usuário é super admin (gerencia todos os cursos)."""
    if not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso permitido apenas para super administradores"
        )
    return current_user


def get_curso_from_path(request: Request, db: Session = Depends(get_db)) -> Optional[Curso]:
    """Extrai o curso do path da URL (ex: /medicina/dashboard -> curso 'medicina')."""
    path_parts = request.url.path.strip('/').split('/')
    if path_parts:
        curso_slug = path_parts[0]
        # Ignora paths que não são de curso (static, api, super-admin, etc.)
        if curso_slug not in ['static', 'uploads', 'api', 'super-admin', 'docs', 'openapi.json']:
            curso = db.query(Curso).filter(Curso.slug == curso_slug, Curso.ativo == True).first()
            return curso
    return None


async def get_required_curso(request: Request, db: Session = Depends(get_db)) -> Curso:
    """Exige que um curso válido esteja no path."""
    curso = get_curso_from_path(request, db)
    if not curso:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curso não encontrado"
        )
    return curso


async def validate_user_curso_access(
    current_user: User = Depends(get_current_user),
    curso: Curso = Depends(get_required_curso)
) -> User:
    """Valida que o usuário tem acesso ao curso na URL."""
    # Super admin tem acesso a todos os cursos
    if current_user.is_super_admin:
        return current_user
    # Usuário comum deve pertencer ao curso
    if current_user.curso_id != curso.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem acesso a este curso"
        )
    return current_user


def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    token = None
    if credentials:
        token = credentials.credentials
    else:
        token = get_token_from_request(request)

    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str is None:
            return None
        user_id = int(user_id_str)
        user = db.query(User).filter(User.id == user_id).first()
        return user if user and user.ativo else None
    except (JWTError, ValueError):
        return None
