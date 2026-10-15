"""Pruebas de los templates de CloudFormation que genera CDK (no despliega nada ni necesita credenciales).

    cd infra && python -m pytest tests -q

Comprueban las garantías de docs/feature/F0004-despliegue-frontend-backend.md: backend privado, buckets sin
acceso público, /api/* sin caché, RDS cifrada y privada, una sola tarea con estado, sin secretos en claro.
"""
import json
import sys
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import construir  # noqa: E402

CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"   # política administrada de CloudFront


@pytest.fixture(scope="module", params=["dev", "demo"])
def plantillas(request, tmp_path_factory):
    dist = tmp_path_factory.mktemp("dist")
    (dist / "index.html").write_text("<!doctype html><title>HLF</title>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    app = cdk.App(context={"entorno": request.param})
    stacks = construir(app, request.param, dist=dist)
    return request.param, {nombre: Template.from_stack(s) for nombre, s in stacks.items()}


def _recursos(t: Template, tipo: str) -> dict:
    return t.find_resources(tipo)


def test_alb_es_interno_y_solo_acepta_cloudfront(plantillas):
    _, t = plantillas
    t["backend"].has_resource_properties("AWS::ElasticLoadBalancingV2::LoadBalancer", {"Scheme": "internal"})
    t["frontend"].has_resource_properties("AWS::EC2::SecurityGroupIngress", {
        "FromPort": 80, "ToPort": 80, "SourcePrefixListId": Match.any_value()})


def test_ningun_security_group_abierto_a_internet(plantillas):
    _, t = plantillas
    # 0.0.0.0/0 sí aparece en la ruta de las subredes públicas al internet gateway y en la salida del
    # backend; lo que no puede haber es una ENTRADA abierta a internet
    for nombre, plantilla in t.items():
        for sg in _recursos(plantilla, "AWS::EC2::SecurityGroup").values():
            for regla in sg["Properties"].get("SecurityGroupIngress", []):
                assert regla.get("CidrIp") not in ("0.0.0.0/0",) and regla.get("CidrIpv6") != "::/0", \
                    f"{nombre}: ingreso abierto a internet"
        for regla in _recursos(plantilla, "AWS::EC2::SecurityGroupIngress").values():
            assert regla["Properties"].get("CidrIp") != "0.0.0.0/0", f"{nombre}: ingreso abierto a internet"


def test_buckets_privados_y_con_tls(plantillas):
    _, t = plantillas
    for nombre in ("datos", "frontend"):
        buckets = _recursos(t[nombre], "AWS::S3::Bucket")
        assert buckets, nombre
        for b in buckets.values():
            assert b["Properties"]["PublicAccessBlockConfiguration"] == {
                "BlockPublicAcls": True, "BlockPublicPolicy": True,
                "IgnorePublicAcls": True, "RestrictPublicBuckets": True}
        politicas = json.dumps(_recursos(t[nombre], "AWS::S3::BucketPolicy"))
        assert '"aws:SecureTransport": "false"' in politicas, f"{nombre}: falta exigir TLS"


def test_api_sin_cache_y_web_con_oac(plantillas):
    _, t = plantillas
    dist = list(_recursos(t["frontend"], "AWS::CloudFront::Distribution").values())[0]["Properties"]
    config = dist["DistributionConfig"]
    api = [c for c in config["CacheBehaviors"] if c["PathPattern"] == "/api/*"]
    assert len(api) == 1 and api[0]["CachePolicyId"] == CACHING_DISABLED
    assert set(api[0]["AllowedMethods"]) >= {"POST", "PUT", "DELETE"}
    assert config["DefaultCacheBehavior"]["FunctionAssociations"][0]["EventType"] == "viewer-request"
    assert _recursos(t["frontend"], "AWS::CloudFront::OriginAccessControl")
    assert _recursos(t["frontend"], "AWS::CloudFront::VpcOrigin")


def test_tareas_segun_donde_vive_el_estado(plantillas):
    entorno, t = plantillas
    # dev: estado en SQLite dentro del contenedor → 1 tarea, reemplazo con corte.
    # demo: estado en RDS (F0005) → 2 tareas, despliegue sin corte.
    tareas, minimo, maximo = (1, 0, 100) if entorno == "dev" else (2, 100, 200)
    t["backend"].has_resource_properties("AWS::ECS::Service", {
        "DesiredCount": tareas,
        "DeploymentConfiguration": Match.object_like({
            "MinimumHealthyPercent": minimo, "MaximumPercent": maximo,
            "DeploymentCircuitBreaker": {"Enable": True, "Rollback": True}}),
        "HealthCheckGracePeriodSeconds": 360,
    })


def test_la_app_solo_escribe_en_sus_prefijos_de_s3(plantillas):
    _, t = plantillas
    politicas = json.dumps(t["backend"].find_resources("AWS::IAM::Policy"))
    assert "/hlf/canal/evidencias/*" in politicas and "/hlf/cargas/*" in politicas
    assert "s3:DeleteObject" not in politicas
    t["backend"].has_resource_properties("AWS::ElasticLoadBalancingV2::TargetGroup", {
        "HealthCheckPath": "/api/meta", "Port": 8000})


def test_variables_del_contenedor_sin_secretos_en_claro(plantillas):
    entorno, t = plantillas
    tarea = list(_recursos(t["backend"], "AWS::ECS::TaskDefinition").values())[0]["Properties"]
    variables = {v["Name"] for v in tarea["ContainerDefinitions"][0]["Environment"]}
    assert {"HLF_S3_BUCKET", "HLF_S3_PREFIJO", "HLF_ATHENA_WORKGROUP", "AWS_REGION"} <= variables
    assert not any("PASSWORD" in v or "CLAVE" in v for v in variables)
    if entorno == "demo":
        assert {"HLF_DB_HOST", "HLF_DB_SECRET_ID"} <= variables
    else:
        assert "HLF_DB_HOST" not in variables


def test_rds_solo_en_demo_cifrada_y_privada(plantillas):
    entorno, t = plantillas
    instancias = _recursos(t["datos"], "AWS::RDS::DBInstance")
    if entorno == "dev":
        assert not instancias
        return
    props = list(instancias.values())[0]
    assert props["Properties"]["StorageEncrypted"] is True
    assert props["Properties"]["PubliclyAccessible"] is False
    assert props["Properties"]["DeletionProtection"] is True
    assert props["DeletionPolicy"] == "Snapshot"


def test_workgroup_de_athena_con_limite_y_cifrado(plantillas):
    entorno, t = plantillas
    t["datos"].has_resource_properties("AWS::Athena::WorkGroup", {
        "Name": f"hlf-priorizacion-{entorno}",
        "WorkGroupConfiguration": Match.object_like({
            "EnforceWorkGroupConfiguration": True,
            "BytesScannedCutoffPerQuery": 1024 ** 3,
            "ResultConfiguration": Match.object_like({
                "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"}}),
        }),
    })


def test_retencion_segun_entorno(plantillas):
    entorno, t = plantillas
    bucket_datos = list(_recursos(t["datos"], "AWS::S3::Bucket").values())[0]
    assert bucket_datos["DeletionPolicy"] == ("Retain" if entorno == "demo" else "Delete")


def test_sin_nat_las_tareas_tienen_ip_publica_pero_sg_cerrado(plantillas):
    _, t = plantillas
    assert not _recursos(t["red"], "AWS::EC2::NatGateway")
    t["backend"].has_resource_properties("AWS::ECS::Service", {
        "NetworkConfiguration": {"AwsvpcConfiguration": Match.object_like({"AssignPublicIp": "ENABLED"})}})
    sg = [s for s in _recursos(t["red"], "AWS::EC2::SecurityGroup").values()
          if "Tareas del backend" in s["Properties"]["GroupDescription"]][0]
    assert "SecurityGroupIngress" not in sg["Properties"]          # su único ingreso es la regla desde el ALB
    t["red"].has_resource_properties("AWS::EC2::SecurityGroupIngress", {"FromPort": 8000, "ToPort": 8000})


def test_etiquetas_en_todos_los_stacks(plantillas):
    entorno, t = plantillas
    bucket = list(_recursos(t["datos"], "AWS::S3::Bucket").values())[0]
    etiquetas = {e["Key"]: e["Value"] for e in bucket["Properties"]["Tags"]}
    assert etiquetas.get("proyecto") == "hlf-priorizacion" and etiquetas.get("entorno") == entorno
