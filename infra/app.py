#!/usr/bin/env python3
"""Punto de entrada de CDK. Instancia los stacks del entorno elegido, en orden de dependencia.

    cdk synth  -c entorno=dev
    cdk deploy --all -c entorno=demo

Detalle y operación en infra/README.md; diseño en docs/feature/F0004-despliegue-frontend-backend.md.
"""
from pathlib import Path

import aws_cdk as cdk

from config.entornos import cargar
from stacks.backend import BackendStack
from stacks.datos import DatosStack
from stacks.frontend import FrontendStack
from stacks.ia import IaStack
from stacks.identidad import IdentidadStack
from stacks.red import RedStack

RAIZ = Path(__file__).resolve().parent.parent


def construir(app: cdk.App, nombre_entorno: str, dist: Path = RAIZ / "web" / "dist") -> dict[str, cdk.Stack]:
    entorno = cargar(nombre_entorno)
    env = cdk.Environment(account=entorno.cuenta, region=entorno.region)
    red = RedStack(app, f"{entorno.id}-Red", entorno=entorno, env=env)
    datos = DatosStack(app, f"{entorno.id}-Datos", entorno=entorno, red=red, env=env)
    identidad = IdentidadStack(app, f"{entorno.id}-Identidad", entorno=entorno, env=env)
    ia = IaStack(app, f"{entorno.id}-Ia", entorno=entorno, env=env)
    backend = BackendStack(app, f"{entorno.id}-Backend", entorno=entorno, red=red, datos=datos, ia=ia, env=env)
    frontend = FrontendStack(app, f"{entorno.id}-Frontend", entorno=entorno, red=red, backend=backend,
                             identidad=identidad, dist=dist, env=env)
    for stack in (red, datos, identidad, ia, backend, frontend):
        cdk.Tags.of(stack).add("proyecto", "hlf-priorizacion")
        cdk.Tags.of(stack).add("entorno", entorno.nombre)
    return {"red": red, "datos": datos, "identidad": identidad, "ia": ia, "backend": backend, "frontend": frontend}


if __name__ == "__main__":
    app = cdk.App()
    construir(app, app.node.try_get_context("entorno") or "dev")
    app.synth()
