FROM python:3.11-slim

# Instalar dependências necessárias para rodar o Chrome no Linux
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usar -u para garantir que os logs (prints) apareçam em tempo real no Coolify
CMD ["python", "-u", "robo_entrega.py"]
