import os
from datetime import timezone, timedelta

# Timezone Brasil (UTC-3)
BRAZIL_TZ = timezone(timedelta(hours=-3))

# Configurações gerais
SECRET_KEY = os.getenv("SECRET_KEY", "sua-chave-secreta-muito-segura-aqui-mude-em-producao")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 horas

# Configurações do banco de dados
# Em produção (Railway), usar DATABASE_URL do ambiente
# Em desenvolvimento local, usar SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ponto_eletronico.db")

# Railway usa "postgres://" mas SQLAlchemy precisa de "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Configurações de geolocalização padrão (São Paulo)
DEFAULT_COMPANY_LATITUDE = -23.550520
DEFAULT_COMPANY_LONGITUDE = -46.633308
DEFAULT_ALLOWED_RADIUS_METERS = 100

# Configurações de upload
UPLOAD_FOLDER = "uploads/fotos"
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB

# Porta do servidor (Railway define via variável de ambiente)
PORT = int(os.getenv("PORT", 8000))
