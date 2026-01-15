from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import os

from app.database import engine, Base, get_db, SessionLocal
from app.models.models import User, CompanySettings
from app.routes import auth_router, ponto_router, admin_router
from app.utils.auth import get_password_hash
from config import DEFAULT_COMPANY_LATITUDE, DEFAULT_COMPANY_LONGITUDE, DEFAULT_ALLOWED_RADIUS_METERS, PORT

# Cria as tabelas no banco de dados
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


def init_db(db: Session):
    """Inicializa o banco de dados com dados padrão"""
    admin = db.query(User).filter(User.email == "admin@empresa.com").first()
    if not admin:
        admin = User(
            nome="Administrador",
            email="admin@empresa.com",
            matricula="ADMIN001",
            senha_hash=get_password_hash("admin123"),
            is_admin=True,
            ativo=True
        )
        db.add(admin)
        print("Usuário admin criado: admin@empresa.com / admin123")

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
