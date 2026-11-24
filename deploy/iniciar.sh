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
# Secretos que se crean solos si faltan (al azar, nunca escritos en el código ni en git):
#   CLAVE_ACCESO          link secreto del dueño (cupo reservado + panel)
#   JWT_SECRETO           firma los tokens de sesión (la comparten app y usuarios)
#   CORREDOR_CONTRASENA   cuenta del corredor en el microservicio de usuarios
escribir() {  # escribir NOMBRE VALOR
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=\"$2\"|" .env; else echo "$1=\"$2\"" >> .env; fi
}
al_azar() { openssl rand -hex "$1" 2>/dev/null || od -An -N"$1" -tx1 /dev/urandom | tr -d ' 
'; }
asegurar() {  # asegurar NOMBRE BYTES
  grep -qE "^$1=\"?[0-9a-f]{$(( $2 * 2 ))}" .env || escribir "$1" "$(al_azar "$2")"
}
asegurar CLAVE_ACCESO 16
asegurar JWT_SECRETO 32
asegurar CORREDOR_CONTRASENA 8
grep -qE '^CORREDOR_CORREO="?[^"@ ]+@' .env || escribir CORREDOR_CORREO "corredor@demo.cl"
leer() { grep -m1 "^$1=" .env | cut -d= -f2- | tr -d '"'; }
CLAVE="$(leer CLAVE_ACCESO)"

# IP pública desde el servicio de metadatos de la EC2 (IMDSv2, solo accesible desde dentro).
TOKEN="$(curl -fsS -X PUT http://169.254.169.254/latest/api/token \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' || true)"
IP="$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/public-ipv4 || true)"

if [ -n "$IP" ]; then
  for VAR in "SITE_ADDRESS=https://$IP" "SITE_IP=$IP"; do
    NOMBRE="${VAR%%=*}"
    if grep -q "^$NOMBRE=" .env; then
      sed -i "s|^$NOMBRE=.*|$NOMBRE=\"${VAR#*=}\"|" .env
    else
      echo "$NOMBRE=\"${VAR#*=}\"" >> .env
    fi
  done
else
  echo "No se pudo leer la IP pública: se usa SITE_ADDRESS tal como está en .env" >&2
fi

# Sin --build, compose construye la imagen solo si todavía no existe.
docker compose -f docker-compose.prod.yml up -d ${1:-}
# El Caddyfile va montado como archivo: si se reemplazó (git pull), el contenedor sigue
# viendo el archivo viejo y compose no lo recrea. Reiniciar Caddy (~1 s) lo vuelve a leer.
docker compose -f docker-compose.prod.yml restart caddy >/dev/null

echo
echo "Listo. Abre:  https://${IP:-<IP_PUBLICA>}                 (chat, público)"
echo "              https://${IP:-<IP_PUBLICA>}/api/health      (como en la guía del curso)"
# El link secreto solo se muestra en una terminal, no en el registro del servicio.
if [ -t 1 ]; then
  echo
  echo "Tu link de DUEÑO (ábrelo una vez en tu navegador; NO lo compartas ni lo proyectes):"
  echo "              https://${IP:-<IP_PUBLICA>}/entrar?clave=$CLAVE"
  echo "Deja tu navegador con cupo reservado y abre el panel de métricas."
  echo
  echo "Cuenta de CORREDOR (inicia sesión en el chat; ve el panel y usa el cupo reservado):"
  echo "              correo:     $(leer CORREDOR_CORREO)"
  echo "              contraseña: $(leer CORREDOR_CONTRASENA)"
fi
echo
echo "El navegador avisa por el certificado propio: 'Avanzado' -> 'Continuar'."
echo "La app tarda ~1 min en cargar los índices después de arrancar."
