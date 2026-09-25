FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema necessárias para PostgreSQL e outras libs
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependências do Python
COPY backend/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código do backend e os arquivos estáticos (HTML/CSS)
COPY backend/ /app/backend/
COPY public_html/ /app/public_html/

# Expor a porta que a API utiliza
EXPOSE 8000

# Comando para iniciar o servidor web
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
