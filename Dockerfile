FROM python:3.11-slim

# Instalar dependências necessárias para rodar o Chrome no Linux
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -u 1000 -m robo
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R robo:robo /app

USER robo

# Usar -u para garantir que os logs (prints) apareçam em tempo real no Coolify
CMD ["python", "-u", "robo_entrega.py"]
