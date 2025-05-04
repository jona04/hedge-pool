# Dockerfile

FROM python:3.11-slim

# Define diretório de trabalho
WORKDIR /app

# Copia os arquivos
COPY . .

# Instala dependências
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Expõe a porta usada pelo FastAPI
EXPOSE 8000

# Comando para iniciar o app
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
