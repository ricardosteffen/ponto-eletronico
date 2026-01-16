from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect
import os

from app.database import engine, Base, get_db, SessionLocal
from app.models.models import User, CompanySettings, Curso, Location
from app.routes import auth_router, ponto_router, admin_router, super_admin_router
from app.utils.auth import get_password_hash
from config import DEFAULT_COMPANY_LATITUDE, DEFAULT_COMPANY_LONGITUDE, DEFAULT_ALLOWED_RADIUS_METERS, PORT


def run_migrations():
    """Executa migrações do banco de dados para adicionar novas colunas."""
    inspector = inspect(engine)

    with engine.connect() as conn:
        # Detecta se é PostgreSQL ou SQLite
        is_postgres = 'postgresql' in str(engine.url)

        # Verifica se tabela cursos existe
        if not inspector.has_table('cursos'):
            print("Criando tabela cursos...")
            if is_postgres:
                conn.execute(text("""
                    CREATE TABLE cursos (
                        id SERIAL PRIMARY KEY,
                        nome VARCHAR(100) NOT NULL,
                        slug VARCHAR(50) UNIQUE NOT NULL,
                        ativo BOOLEAN DEFAULT true,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE cursos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome VARCHAR(100) NOT NULL,
                        slug VARCHAR(50) UNIQUE NOT NULL,
                        ativo BOOLEAN DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            conn.commit()
            print("Tabela cursos criada!")

        # Verifica colunas na tabela users
        user_columns = [col['name'] for col in inspector.get_columns('users')]

        if 'is_super_admin' not in user_columns:
            print("Adicionando coluna is_super_admin em users...")
            if is_postgres:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_super_admin BOOLEAN DEFAULT false"))
            else:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_super_admin BOOLEAN DEFAULT 0"))
            conn.commit()
            print("Coluna is_super_admin adicionada!")

        if 'curso_id' not in user_columns:
            print("Adicionando coluna curso_id em users...")
            conn.execute(text("ALTER TABLE users ADD COLUMN curso_id INTEGER"))
            conn.commit()
            print("Coluna curso_id adicionada em users!")

        # Verifica colunas na tabela locations
        if inspector.has_table('locations'):
            location_columns = [col['name'] for col in inspector.get_columns('locations')]

            if 'curso_id' not in location_columns:
                print("Adicionando coluna curso_id em locations...")
                conn.execute(text("ALTER TABLE locations ADD COLUMN curso_id INTEGER"))
                conn.commit()
                print("Coluna curso_id adicionada em locations!")

    print("Migrações concluídas!")


# Executa migrações antes de criar tabelas
run_migrations()

# Cria as tabelas no banco de dados (para tabelas novas)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Ponto Eletrônico",
    description="Sistema de Controle de Ponto Eletrônico",
    version="1.0.0"
)

# Monta arquivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Configura templates
templates = Jinja2Templates(directory="templates")

# Registra rotas da API
app.include_router(auth_router)
app.include_router(ponto_router)
app.include_router(admin_router)
app.include_router(super_admin_router)


def init_db(db: Session):
    """Inicializa o banco de dados com dados padrão"""
    # Cria curso padrão se não existir
    default_curso = db.query(Curso).filter(Curso.slug == "default").first()
    if not default_curso:
        default_curso = Curso(
            nome="Curso Padrão",
            slug="default"
        )
        db.add(default_curso)
        db.flush()
        print("Curso padrão criado")

    # Cria super admin se não existir
    super_admin = db.query(User).filter(User.is_super_admin == True).first()
    if not super_admin:
        # Verifica se existe admin antigo para converter
        old_admin = db.query(User).filter(User.email == "admin@empresa.com").first()
        if old_admin:
            old_admin.is_super_admin = True
            print("Usuário admin convertido para super admin")
        else:
            super_admin = User(
                nome="Super Administrador",
                email="admin@puc.rio",
                matricula="SUPERADMIN",
                senha_hash=get_password_hash("admin123"),
                is_admin=True,
                is_super_admin=True,
                ativo=True,
                curso_id=None  # Super admin não pertence a nenhum curso específico
            )
            db.add(super_admin)
            print("Super admin criado: admin@puc.rio / admin123")

    # Associa usuários/locais órfãos ao curso padrão
    db.query(User).filter(
        User.curso_id == None,
        User.is_super_admin == False
    ).update({"curso_id": default_curso.id})

    db.query(Location).filter(Location.curso_id == None).update({"curso_id": default_curso.id})

    settings = db.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(
            nome_empresa="Minha Empresa",
            latitude=DEFAULT_COMPANY_LATITUDE,
            longitude=DEFAULT_COMPANY_LONGITUDE,
            raio_permitido_metros=DEFAULT_ALLOWED_RADIUS_METERS
        )
        db.add(settings)
        print("Configurações padrão da empresa criadas")

    db.commit()


@app.on_event("startup")
async def startup_event():
    os.makedirs("uploads/fotos", exist_ok=True)
    db = SessionLocal()
    try:
        init_db(db)
    finally:
        db.close()

    print("\n" + "="*50)
    print("PONTO ELETRÔNICO - Sistema iniciado!")
    print("="*50)
    print("Acesse: http://localhost:8000")
    print("Login admin: admin@empresa.com / admin123")
    print("="*50 + "\n")


@app.get("/")
async def root():
    return RedirectResponse(url="/login")


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "user": None})


@app.get("/cadastro")
async def cadastro_page(request: Request):
    return templates.TemplateResponse("cadastro.html", {"request": request, "user": None})


@app.get("/dashboard")
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": {"nome": ""}})


@app.get("/admin")
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request, "user": {"nome": "", "is_admin": True}})


# ============= SUPER ADMIN =============

@app.get("/super-admin")
async def super_admin_page(request: Request):
    return templates.TemplateResponse("super_admin.html", {"request": request})


# ============= ROTAS POR CURSO =============

def get_curso_or_404(db: Session, curso_slug: str) -> Curso:
    """Helper para buscar curso ou retornar 404."""
    curso = db.query(Curso).filter(Curso.slug == curso_slug, Curso.ativo == True).first()
    if not curso:
        raise HTTPException(status_code=404, detail="Curso não encontrado")
    return curso


@app.get("/{curso_slug}/login")
async def curso_login_page(request: Request, curso_slug: str, db: Session = Depends(get_db)):
    curso = get_curso_or_404(db, curso_slug)
    return templates.TemplateResponse("curso_login.html", {
        "request": request,
        "curso": {"id": curso.id, "nome": curso.nome, "slug": curso.slug}
    })


@app.get("/{curso_slug}/cadastro")
async def curso_cadastro_page(request: Request, curso_slug: str, db: Session = Depends(get_db)):
    curso = get_curso_or_404(db, curso_slug)
    return templates.TemplateResponse("curso_cadastro.html", {
        "request": request,
        "curso": {"id": curso.id, "nome": curso.nome, "slug": curso.slug}
    })


@app.get("/{curso_slug}/dashboard")
async def curso_dashboard_page(request: Request, curso_slug: str, db: Session = Depends(get_db)):
    curso = get_curso_or_404(db, curso_slug)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": {"nome": ""},
        "curso": {"id": curso.id, "nome": curso.nome, "slug": curso.slug}
    })


@app.get("/{curso_slug}/admin")
async def curso_admin_page(request: Request, curso_slug: str, db: Session = Depends(get_db)):
    curso = get_curso_or_404(db, curso_slug)
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": {"nome": "", "is_admin": True},
        "curso": {"id": curso.id, "nome": curso.nome, "slug": curso.slug}
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
