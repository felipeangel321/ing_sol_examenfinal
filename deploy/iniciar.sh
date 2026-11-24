#!/usr/bin/env bash
# Levanta (o actualiza) el asistente en la EC2 con la IP pública de ESTA sesión.
#
# En el Learner Lab la IP cambia cada vez que se inicia el laboratorio, y Caddy
# necesita la IP correcta para el certificado HTTPS. Este script la lee de la propia
# instancia, la escribe en deploy/.env y levanta los contenedores.
#
#   sudo bash ~/app/deploy/iniciar.sh            levantar (la 1.ª vez construye la imagen)
#   sudo bash ~/app/deploy/iniciar.sh --build    reconstruir después de cambiar el código
#
# También lo corre solo el servicio proyecto-seguros al encender la instancia.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEPLOY_DIR"

if [ ! -f .env ]; then
  echo "Falta deploy/.env: corre primero deploy/bootstrap-ec2.sh" >&2
  exit 1
fi
if ! grep -q '^GROQ_API_KEY="\?gsk_' .env; then
  echo "AVISO: GROQ_API_KEY no parece completa en deploy/.env (debe empezar con gsk_)." >&2
fi
# Clave del link secreto del dueño: sin ella no hay cupo reservado y el panel queda abierto.
CLAVE="$(grep -oE '^CLAVE_ACCESO="?[0-9a-f]{32,}' .env | grep -oE '[0-9a-f]{32,}' || true)"
if [ -z "$CLAVE" ]; then
  echo "Falta CLAVE_ACCESO (32 caracteres hex) en deploy/.env: corre de nuevo deploy/bootstrap-ec2.sh" >&2
  exit 1
fi

# IP pública desde el servicio de metadatos de la EC2 (IMDSv2, solo accesible desde dentro).
TOKEN="$(curl -fsS -X PUT http://169.254.169.254/latest/api/token \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' || true)"
IP="$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/public-ipv4 || true)"

if [ -n "$IP" ]; then
  if grep -q '^SITE_ADDRESS=' .env; then
    sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=\"https://$IP\"|" .env
  else
    echo "SITE_ADDRESS=\"https://$IP\"" >> .env
  fi
else
  echo "No se pudo leer la IP pública: se usa SITE_ADDRESS tal como está en .env" >&2
fi

# Sin --build, compose construye la imagen solo si todavía no existe.
docker compose -f docker-compose.prod.yml up -d ${1:-}

echo
echo "Listo. Abre:  https://${IP:-<IP_PUBLICA>}                 (chat, público)"
echo "              https://${IP:-<IP_PUBLICA>}/api/health      (como en la guía del curso)"
# El link secreto solo se muestra en una terminal, no en el registro del servicio.
if [ -t 1 ]; then
  echo
  echo "Tu link de DUEÑO (ábrelo una vez en tu navegador; NO lo compartas ni lo proyectes):"
  echo "              https://${IP:-<IP_PUBLICA>}/entrar?clave=$CLAVE"
  echo "Deja tu navegador con cupo reservado y abre el panel de métricas."
fi
echo
echo "El navegador avisa por el certificado propio: 'Avanzado' -> 'Continuar'."
echo "La app tarda ~1 min en cargar los índices después de arrancar."
