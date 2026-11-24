# Corredores y seguros

Cada corredor tiene su carpeta, y cada seguro tiene su ficha y sus documentos.

```
corredores/
└── demo/                   ← corredor de prueba
    └── seguros/
        └── vehiculo/
            ├── ficha.yaml  ← nombre, descripción, datos que se piden y lista de documentos
            └── documentos/ ← PDF que lee el agente (no se suben a git)
```

**Para agregar un seguro:** copia la carpeta de otro seguro, cambia su nombre, edita `ficha.yaml` y deja sus PDF en `documentos/`. No hace falta programar nada.

En `ficha.yaml`, `paginas_particulares` indica hasta qué página van las condiciones particulares de la póliza (el plan de un cliente puntual). Desde la página siguiente vienen las condiciones generales.

Las carpetas que empiezan con `_` o `.` se ignoran.
