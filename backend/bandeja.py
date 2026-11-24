"""Bandeja del corredor en la consola: solicitudes y derivaciones registradas por los agentes.

Uso:
  uv run python -m backend.bandeja
  uv run python -m backend.bandeja --corredor demo
"""
import argparse
import sys

from backend import almacen


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Bandeja del corredor")
    parser.add_argument("--corredor")
    args = parser.parse_args()

    solicitudes = almacen.listar("solicitudes", args.corredor)
    print(f"\n== Solicitudes ({len(solicitudes)}) ==")
    for s in solicitudes:
        print(f"  {s['numero']}  {s['creada']}  {s['seguro']:22} {s['estado']}")
        for campo, valor in s["datos"].items():
            print(f"      {campo}: {valor}")

    derivaciones = almacen.listar("derivaciones", args.corredor)
    print(f"\n== Derivaciones ({len(derivaciones)}) ==")
    for d in derivaciones:
        print(f"  {d['numero']}  {d['creada']}  {d['seguro']:22} urgencia {d['urgencia']:6} {d['estado']}")
        print(f"      motivo: {d['motivo']}")
        if d["contacto"]:
            print(f"      contacto: {d['contacto']}")


if __name__ == "__main__":
    main()
