# Imagem enxuta com Python 3.12.
FROM python:3.12-slim

# Nao gerar arquivos .pyc e mostrar o log na hora (sem buffer).
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala as dependencias primeiro para aproveitar o cache de camadas.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o codigo da aplicacao.
COPY app ./app

# A API sobe na porta 8723 (porta pouco usual, para evitar conflitos comuns).
EXPOSE 8723

# Sobe o servidor uvicorn apontando para o app FastAPI.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8723"]
