#!/usr/bin/env bash
# Prepara una EC2 con Amazon Linux 2023 (AWS Academy Learner Lab) para el asistente.
# Basado en deploy/bootstrap-ec2.sh del repo del curso. Se puede correr varias veces.
#
# Uso, igual que en el curso (paso 6 de RA3/IL3.5/1-deploy-aws-paso-a-paso.md):
#   curl -fsSL https://raw.githubusercontent.com/<USUARIO>/<REPO>/main/deploy/bootstrap-ec2.sh -o bootstrap.sh
#   bash bootstrap.sh https://github.com/<USUARIO>/<REPO>.git
# o, con el repo ya en ~/app:
#   bash ~/app/deploy/bootstrap-ec2.sh
#
# Hace: instala git, Docker + compose + buildx, clona (o actualiza) el repo en ~/app,
# descomprime las pólizas si subiste ~/documentos_demo.zip, crea deploy/.env desde el
# ejemplo y deja un servicio que arranca la app sola cada vez que la instancia se enciende.
set -euo pipefail

REPO_URL="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "$REPO_URL" ] || [ ! -f "$SCRIPT_DIR/docker-compose.prod.yml" ]; then
  APP_DIR="$HOME/app"                   # descargado con curl: el repo va en ~/app
else
  APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)" # corrido desde dentro del repo
fi
ARCH="$(uname -m)"                      # x86_64 en una t3
case "$ARCH" in x86_64) GOARCH=amd64 ;; aarch64) GOARCH=arm64 ;; *) GOARCH="$ARCH" ;; esac
PLUGINS=/usr/local/lib/docker/cli-plugins

echo ">> 0/5 Repositorio..."
sudo dnf install -y git nano unzip >/dev/null   # la AMI de Amazon Linux 2023 no los trae
if [ -n "$REPO_URL" ]; then
  if [ ! -d "$APP_DIR/.git" ]; then
    git clone "$REPO_URL" "$APP_DIR"
  else
    git -C "$APP_DIR" pull --ff-only
  fi
fi
if [ ! -f "$APP_DIR/deploy/docker-compose.prod.yml" ]; then
  echo "   No encuentro el proyecto en $APP_DIR. Pasa la URL de tu repo:" >&2
  echo "   bash bootstrap.sh https://github.com/<USUARIO>/<REPO>.git" >&2
  exit 1
fi
echo "   Proyecto en $APP_DIR"

echo ">> 1/5 Instalando Docker..."
if ! command -v docker >/dev/null 2>&1; then
  sudo dnf install -y docker
fi
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true
sudo mkdir -p "$PLUGINS"

echo ">> 2/5 Instalando docker compose..."
if ! sudo docker compose version >/dev/null 2>&1; then
  sudo curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
    -o "$PLUGINS/docker-compose"
  sudo chmod +x "$PLUGINS/docker-compose"
fi

echo ">> 3/5 Instalando docker buildx (compose lo necesita para construir la imagen)..."
if ! sudo docker buildx version >/dev/null 2>&1; then
  VERSION="$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest | grep -m1 '"tag_name"' | cut -d '"' -f 4)"
  sudo curl -fsSL "https://github.com/docker/buildx/releases/download/${VERSION}/buildx-${VERSION}.linux-${GOARCH}" \
    -o "$PLUGINS/docker-buildx"
  sudo chmod +x "$PLUGINS/docker-buildx"
fi

echo ">> 4/5 Pólizas (PDF)..."
if [ -f "$HOME/documentos_demo.zip" ]; then
  unzip -o -q "$HOME/documentos_demo.zip" -d "$APP_DIR"
fi
CANTIDAD="$(find "$APP_DIR/corredores" -name '*.pdf' | wc -l)"
if [ "$CANTIDAD" -eq 0 ]; then
  echo "   FALTAN los PDF. Desde tu PC, en la carpeta del proyecto:"
  echo "   scp -i <tu-llave>.pem entrega/documentos_demo.zip ec2-user@<IP_PUBLICA>:~/"
  echo "   y vuelve a correr este script."
  exit 1
fi
echo "   $CANTIDAD pólizas listas."

echo ">> 5/5 Configuración, clave del dueño y arranque automático..."
if [ ! -f "$APP_DIR/deploy/.env" ]; then
  cp "$APP_DIR/deploy/.env.example" "$APP_DIR/deploy/.env"
  chmod 600 "$APP_DIR/deploy/.env"
fi
# Clave del link secreto del dueño (cupo reservado + panel). 128 bits al azar: no se
# puede adivinar. Solo se crea si falta; iniciar.sh imprime el link.
if ! grep -qE '^CLAVE_ACCESO="?[0-9a-f]{32}' "$APP_DIR/deploy/.env"; then
  CLAVE="$(openssl rand -hex 16 2>/dev/null || od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  if grep -q '^CLAVE_ACCESO=' "$APP_DIR/deploy/.env"; then
    sed -i "s|^CLAVE_ACCESO=.*|CLAVE_ACCESO=\"$CLAVE\"|" "$APP_DIR/deploy/.env"
  else
    echo "CLAVE_ACCESO=\"$CLAVE\"" >> "$APP_DIR/deploy/.env"
  fi
  echo "   Clave del dueño creada en deploy/.env"
fi
# Servicio que corre deploy/iniciar.sh al encender la EC2: actualiza la IP (cambia en
# cada sesión del Learner Lab) y levanta los contenedores.
sudo tee /etc/systemd/system/proyecto-seguros.service >/dev/null <<EOF
[Unit]
Description=Asistente de seguros (docker compose)
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash $APP_DIR/deploy/iniciar.sh

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable proyecto-seguros.service >/dev/null

echo
echo ">> Listo. Falta:"
echo "   1. nano $APP_DIR/deploy/.env      (pega tu GROQ_API_KEY y guarda)"
echo "   2. sudo bash $APP_DIR/deploy/iniciar.sh   (la 1.ª vez tarda ~10 min: construye la imagen)"
echo "      Al final imprime tu link secreto de dueño: guárdalo y no lo compartas."
