#!/usr/bin/env python3
"""Punto de entrada de CDK. Instancia los stacks del entorno elegido, en orden de dependencia.

    cdk synth  -c entorno=dev
    cdk deploy --all -c entorno=demo

Detalle y operación en infra/README.md; diseño en docs/feature/F0004-despliegue-frontend-backend.md.
"""
from pathlib import Path

import aws_cdk as cdk

from config.entornos import cargar
from stacks.asistente import AsistenteStack
from stacks.backend import BackendStack
from stacks.consulta import ConsultaStack
from stacks.datos import DatosStack
from stacks.frontend import FrontendStack
from stacks.ia import IaStack
from stacks.identidad import IdentidadStack
from stacks.observabilidad import ObservabilidadStack
from stacks.red import RedStack
from stacks.seguridad import RespaldoCopiaStack, SeguridadStack
from stacks.voz import VozStack

RAIZ = Path(__file__).resolve().parent.parent


def construir(app: cdk.App, nombre_entorno: str, dist: Path = RAIZ / "web" / "dist") -> dict[str, cdk.Stack]:
    entorno = cargar(nombre_entorno)
    env = cdk.Environment(account=entorno.cuenta, region=entorno.region)
    red = RedStack(app, f"{entorno.id}-Red", entorno=entorno, env=env)
    datos = DatosStack(app, f"{entorno.id}-Datos", entorno=entorno, red=red, env=env)
    identidad = IdentidadStack(app, f"{entorno.id}-Identidad", entorno=entorno, env=env)
    ia = IaStack(app, f"{entorno.id}-Ia", entorno=entorno, env=env)
    consulta = ConsultaStack(app, f"{entorno.id}-Consulta", entorno=entorno, datos=datos, env=env)
    asistente = AsistenteStack(app, f"{entorno.id}-Asistente", entorno=entorno, datos=datos, env=env)
    backend = BackendStack(app, f"{entorno.id}-Backend", entorno=entorno, red=red, datos=datos, ia=ia,
                           consulta=consulta, asistente=asistente, env=env)
    # F0013: WAF, CloudTrail y respaldo (cada uno por flag); el WAF se asocia a CloudFront
    seguridad = SeguridadStack(app, f"{entorno.id}-Seguridad", entorno=entorno, datos=datos, env=env)
    frontend = FrontendStack(app, f"{entorno.id}-Frontend", entorno=entorno, red=red, backend=backend,
                             identidad=identidad, dist=dist, parametro_api=asistente.parametro_api,
                             web_acl_arn=seguridad.web_acl.attr_arn if seguridad.web_acl else None, env=env)
    pilas = {"red": red, "datos": datos, "identidad": identidad, "ia": ia, "consulta": consulta, "asistente": asistente,
             "backend": backend, "seguridad": seguridad, "frontend": frontend}
    if entorno.respaldo and entorno.respaldo_region_copia:
        copia = RespaldoCopiaStack(app, f"{entorno.id}-RespaldoCopia", entorno=entorno,
                                   env=cdk.Environment(account=entorno.cuenta, region=entorno.respaldo_region_copia))
        seguridad.add_dependency(copia)
        pilas["respaldo_copia"] = copia
    lambdas = {"whatsapp": asistente.funcion}
    if asistente.funcion_escaneo is not None:
        lambdas["escaneo-examenes"] = asistente.funcion_escaneo
    if entorno.voz:                    # F0011: Connect y Lex en su propio stack (se despliega aparte si hace falta)
        pilas["voz"] = VozStack(app, f"{entorno.id}-Voz", entorno=entorno, asistente=asistente, datos=datos, env=env)
        lambdas["voz"] = pilas["voz"].funcion
    # F0013: tablero, alarmas y presupuesto (al final: lee métricas de todos)
    pilas["observabilidad"] = ObservabilidadStack(app, f"{entorno.id}-Observabilidad", entorno=entorno, datos=datos,
                                                  backend=backend, lambdas=lambdas, env=env)
    for stack in pilas.values():
        cdk.Tags.of(stack).add("proyecto", "hlf-priorizacion")
        cdk.Tags.of(stack).add("entorno", entorno.nombre)
    return pilas


if __name__ == "__main__":
    app = cdk.App()
    construir(app, app.node.try_get_context("entorno") or "dev")
    app.synth()
