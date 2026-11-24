"""Microservicio de usuarios: registro, inicio de sesión y perfil.

Corre en su propio contenedor (deploy/Dockerfile.usuarios) con su propia base de datos
(SQLite, `usuarios.db`). La app del asistente no lee esa base: solo verifica el token
que este servicio firma (tokens.py), con la clave compartida JWT_SECRETO.

  POST /usuarios/registro   crea la cuenta (el correo no se puede repetir: UNIQUE)
  POST /usuarios/login      devuelve un token y deja la cookie de sesión
  POST /usuarios/logout     borra la cookie
  GET  /usuarios/yo         perfil del usuario con sesión
  GET  /usuarios/health
"""
