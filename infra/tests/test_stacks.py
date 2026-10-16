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
    assert len(api) == 1
    # Sin caché (TTL 0), pero nombrando Authorization para que CloudFront la reenvíe a la API (F0007)
    (politica,) = _recursos(t["frontend"], "AWS::CloudFront::CachePolicy").values()
    p = politica["Properties"]["CachePolicyConfig"]
    assert p["DefaultTTL"] == 0 and p["MinTTL"] == 0 and p["MaxTTL"] <= 1
    assert p["ParametersInCacheKeyAndForwardedToOrigin"]["HeadersConfig"]["Headers"] == ["Authorization"]
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
        "HealthCheckPath": "/api/salud", "Port": 8000})


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


def test_consolidacion_nocturna_solo_con_rds(plantillas):
    entorno, t = plantillas
    programaciones = _recursos(t["backend"], "AWS::Scheduler::Schedule")
    if entorno == "dev":
        assert programaciones == {}                       # sin base no hay histórico que consolidar
        return
    (prog,) = programaciones.values()
    p = prog["Properties"]
    assert p["ScheduleExpression"] == "cron(0 2 * * ? *)" and p["ScheduleExpressionTimezone"] == "America/Santiago"
    assert p["Target"]["EcsParameters"]["LaunchType"] == "FARGATE"
    tareas = _recursos(t["backend"], "AWS::ECS::TaskDefinition").values()
    nocturna = next(x["Properties"]["ContainerDefinitions"][0] for x in tareas
                    if x["Properties"]["ContainerDefinitions"][0].get("Command"))
    assert nocturna["Command"] == ["python", "-m", "servicios.nocturno"]
    variables = {v["Name"]: v["Value"] for v in nocturna["Environment"] if isinstance(v.get("Value"), str)}
    assert variables["HLF_AUTOCONFIRMAR"] == "1" and "HLF_DB_SECRET_ID" in {v["Name"] for v in nocturna["Environment"]}
    politicas = json.dumps(t["backend"].find_resources("AWS::IAM::Policy"))
    assert "/hlf/parquet/*" in politicas and "/hlf/historial/*" in politicas
    assert "ecs:RunTask" in politicas and "iam:PassRole" in politicas


def test_login_de_la_administradora(plantillas):
    """F0007: User Pool sin registro abierto, un grupo, cliente público con PKCE y la API leyendo su configuración."""
    entorno, t = plantillas
    t["identidad"].has_resource_properties("AWS::Cognito::UserPool", {
        "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True}})
    grupos = [g["Properties"]["GroupName"] for g in _recursos(t["identidad"], "AWS::Cognito::UserPoolGroup").values()]
    assert grupos == ["administracion"]
    (cliente,) = _recursos(t["frontend"], "AWS::Cognito::UserPoolClient").values()
    c = cliente["Properties"]
    assert c["GenerateSecret"] is False and c["AllowedOAuthFlows"] == ["code"]
    assert "implicit" not in json.dumps(c)
    t["frontend"].has_resource_properties("AWS::SSM::Parameter", {"Name": f"/hlf/{entorno}/cognito"})
    tarea = next(x for x in _recursos(t["backend"], "AWS::ECS::TaskDefinition").values()
                 if not x["Properties"]["ContainerDefinitions"][0].get("Command"))
    variables = {v["Name"]: v.get("Value") for v in tarea["Properties"]["ContainerDefinitions"][0]["Environment"]}
    assert variables["HLF_COGNITO_PARAMETRO"] == f"/hlf/{entorno}/cognito"
    assert "ssm:GetParameter" in json.dumps(t["backend"].find_resources("AWS::IAM::Policy"))



def test_ia_solo_bedrock_con_guardrail_y_minimo_privilegio(plantillas):
    """F0008: guardrail en español (nivel Standard), temas denegados solo en la salida, e invocación solo del perfil
    elegido. En dev (sin IA) la tarea no recibe permisos de Bedrock."""
    entorno, t = plantillas
    (guardrail,) = _recursos(t["ia"], "AWS::Bedrock::Guardrail").values()
    g = guardrail["Properties"]
    assert g["ContentPolicyConfig"]["ContentFiltersTierConfig"]["TierName"] == "STANDARD"
    assert g["TopicPolicyConfig"]["TopicsTierConfig"]["TierName"] == "STANDARD"
    assert all(tp["InputEnabled"] is False and tp["OutputEnabled"] is True and tp["Type"] == "DENY"
               for tp in g["TopicPolicyConfig"]["TopicsConfig"])
    assert _recursos(t["ia"], "AWS::Bedrock::GuardrailVersion")
    politicas = json.dumps(t["ia"].find_resources("AWS::IAM::ManagedPolicy"))
    assert '"bedrock:*"' not in politicas and '"Resource": "*"' not in politicas
    tarea = next(x for x in _recursos(t["backend"], "AWS::ECS::TaskDefinition").values()
                 if not x["Properties"]["ContainerDefinitions"][0].get("Command"))
    variables = {v["Name"]: v.get("Value") for v in tarea["Properties"]["ContainerDefinitions"][0]["Environment"]}
    roles = json.dumps(t["backend"].find_resources("AWS::IAM::Role"))
    if entorno == "demo":
        assert variables["LLM_PROVEEDOR"] == "bedrock"
        assert variables["BEDROCK_MODEL_ID"].startswith("us.anthropic.")
        assert {"BEDROCK_GUARDRAIL_ID", "BEDROCK_GUARDRAIL_VERSION"} <= set(variables)
        assert "inference-profile/us.anthropic" in politicas and "bedrock:InvokeModel" in politicas
        assert "PoliticaInvocacion" in roles or "ImportValue" in roles
    else:
        assert variables["LLM_PROVEEDOR"] == "" and "BEDROCK_GUARDRAIL_ID" not in variables
        assert "PoliticaInvocacion" not in roles and "HlfDev-Ia" not in roles


def test_consulta_kb_sobre_s3_vectors_y_permisos_de_solo_lectura(plantillas):
    """F0009: KB del equipo clínico en S3 Vectors con Titan V2; Athena solo con el workgroup del entorno; la API
    recibe la KB solo donde hay Bedrock y RDS."""
    entorno, t = plantillas
    indices = {x["Properties"]["IndexName"]: x["Properties"] for x in _recursos(t["consulta"], "AWS::S3Vectors::Index").values()}
    assert set(indices) == {"equipo-clinico", "paciente-faq"}                  # F0009 y F0010
    for i in indices.values():
        assert i["Dimension"] == 1024 and i["DistanceMetric"] == "cosine"
        assert set(i["MetadataConfiguration"]["NonFilterableMetadataKeys"]) == {"AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"}
    kbs = list(_recursos(t["consulta"], "AWS::Bedrock::KnowledgeBase").values())
    assert len(kbs) == 2 and all(kb["Properties"]["StorageConfiguration"]["Type"] == "S3_VECTORS" for kb in kbs)
    assert all("titan-embed-text-v2" in json.dumps(kb["Properties"]["KnowledgeBaseConfiguration"]) for kb in kbs)
    prefijos = sorted(f["Properties"]["DataSourceConfiguration"]["S3Configuration"]["InclusionPrefixes"][0]
                      for f in _recursos(t["consulta"], "AWS::Bedrock::DataSource").values())
    assert prefijos == ["hlf/kb/equipo/", "hlf/kb/paciente/"]
    politicas = json.dumps(t["consulta"].find_resources("AWS::IAM::ManagedPolicy"))
    assert "athena:StartQueryExecution" in politicas and f"workgroup/hlf-priorizacion-{entorno}" in politicas
    assert '"athena:*"' not in politicas and '"glue:*"' not in politicas and "s3:DeleteObject" not in politicas
    tarea = next(x for x in _recursos(t["backend"], "AWS::ECS::TaskDefinition").values()
                 if not x["Properties"]["ContainerDefinitions"][0].get("Command"))
    variables = {v["Name"] for v in tarea["Properties"]["ContainerDefinitions"][0]["Environment"]}
    assert ({"HLF_KB_ID", "HLF_KB_DATA_SOURCE_ID"} <= variables) == (entorno == "demo")


def test_asistente_cifrado_secretos_y_lambda_sin_vpc(plantillas):
    """F0010: clave KMS con rotación, secretos generados por AWS, tema SNS solo para End User Messaging Social y una
    Lambda sin VPC que no recibe secretos en claro. La API recibe la clave y los secretos solo donde hay asistente."""
    entorno, t = plantillas
    t["asistente"].has_resource_properties("AWS::KMS::Key", {"EnableKeyRotation": True})
    secretos = _recursos(t["asistente"], "AWS::SecretsManager::Secret").values()
    assert len(secretos) == 2 and all("GenerateSecretString" in s["Properties"] for s in secretos)
    politica = json.dumps(_recursos(t["asistente"], "AWS::SNS::TopicPolicy"))
    assert "social-messaging.amazonaws.com" in politica
    (funcion,) = [f for f in _recursos(t["asistente"], "AWS::Lambda::Function").values()
                  if f["Properties"].get("Handler") == "lambda_whatsapp.handler"]
    assert "VpcConfig" not in funcion["Properties"]
    variables = funcion["Properties"]["Environment"]["Variables"]
    assert set(variables) == {"HLF_SERVICIO_SECRET_ID", "HLF_API_PARAMETRO", "HLF_WHATSAPP_ORIGEN"}
    tarea = next(x for x in _recursos(t["backend"], "AWS::ECS::TaskDefinition").values()
                 if not x["Properties"]["ContainerDefinitions"][0].get("Command"))
    nombres = {v["Name"] for v in tarea["Properties"]["ContainerDefinitions"][0]["Environment"]}
    esperadas = {"HLF_KMS_KEY_ID", "HLF_HMAC_SECRET_ID", "HLF_SERVICIO_SECRET_ID", "HLF_KB_PACIENTE_ID"}
    assert (esperadas <= nombres) == (entorno == "demo")
    t["frontend"].has_resource_properties("AWS::SSM::Parameter", {"Name": f"/hlf/{entorno}/api_url"})



def test_voz_connect_lex_y_grabacion_solo_con_consentimiento(plantillas):
    """F0011: solo donde se activa. Lex en es_US con voz neural; toda intención pasa por la Lambda (sin VPC);
    Connect con flujo versionado, cola humana y grabaciones en el bucket de datos; el número no se reclama solo."""
    entorno, t = plantillas
    if entorno == "dev":
        assert "voz" not in t
        return
    (bot,) = _recursos(t["voz"], "AWS::Lex::Bot").values()
    (locale,) = bot["Properties"]["BotLocales"]
    assert locale["LocaleId"] == "es_US" and locale["VoiceSettings"] == {"VoiceId": "Lupe", "Engine": "neural"}
    assert all(i["FulfillmentCodeHook"]["Enabled"] for i in locale["Intents"])
    assert any(i.get("ParentIntentSignature") == "AMAZON.FallbackIntent" for i in locale["Intents"])
    (alias,) = _recursos(t["voz"], "AWS::Lex::BotAlias").values()
    assert "LambdaArn" in json.dumps(alias["Properties"]["BotAliasLocaleSettings"])
    (funcion,) = _recursos(t["voz"], "AWS::Lambda::Function").values() if len(
        _recursos(t["voz"], "AWS::Lambda::Function")) == 1 else [f for f in _recursos(t["voz"], "AWS::Lambda::Function").values()
                                                                 if f["Properties"].get("Handler") == "lambda_voz.handler"]
    assert "VpcConfig" not in funcion["Properties"]
    (flujo,) = _recursos(t["voz"], "AWS::Connect::ContactFlow").values()
    assert "Fn::Sub" in json.dumps(flujo["Properties"]["Content"])            # alias de Lex y cola sustituidos
    t["voz"].has_resource_properties("AWS::Connect::InstanceStorageConfig", {"ResourceType": "CALL_RECORDINGS"})
    assert _recursos(t["voz"], "AWS::Connect::Queue") and _recursos(t["voz"], "AWS::Connect::IntegrationAssociation")
    assert not _recursos(t["voz"], "AWS::Connect::PhoneNumber")               # tiene costo: se activa a propósito


def test_examenes_cifrados_escaneados_y_sin_descarga_de_amenazas(plantillas):
    """F0012: clave KMS propia con rotación; subida directa al bucket (CORS solo POST); un objeto con amenaza no se
    descarga; con GuardDuty, el plan protege solo el prefijo de evidencias y su resultado llega a una Lambda sin VPC."""
    entorno, t = plantillas
    claves = _recursos(t["asistente"], "AWS::KMS::Key").values()
    assert len(claves) == 2 and all(k["Properties"]["EnableKeyRotation"] for k in claves)
    (bucket,) = [b for b in _recursos(t["datos"], "AWS::S3::Bucket").values() if "CorsConfiguration" in b["Properties"]]
    (regla,) = bucket["Properties"]["CorsConfiguration"]["CorsRules"]
    assert regla["AllowedMethods"] == ["POST"]
    politica = json.dumps(_recursos(t["datos"], "AWS::S3::BucketPolicy"))
    assert "THREATS_FOUND" in politica and "SinDescargaDeArchivosConAmenaza" in politica
    tarea = next(x for x in _recursos(t["backend"], "AWS::ECS::TaskDefinition").values()
                 if not x["Properties"]["ContainerDefinitions"][0].get("Command"))
    variables = {v["Name"]: v.get("Value") for v in tarea["Properties"]["ContainerDefinitions"][0]["Environment"]}
    planes = _recursos(t["asistente"], "AWS::GuardDuty::MalwareProtectionPlan")
    if entorno == "piloto":                    # demo no puede: la SCP del hackatón niega GuardDuty
        (plan,) = planes.values()
        assert "canal/evidencias/" in json.dumps(plan["Properties"]["ProtectedResource"])
        assert plan["Properties"]["Actions"]["Tagging"]["Status"] == "ENABLED"
        (regla_ev,) = _recursos(t["asistente"], "AWS::Events::Rule").values()
        assert regla_ev["Properties"]["EventPattern"]["source"] == ["aws.guardduty"]
        (funcion,) = [f for f in _recursos(t["asistente"], "AWS::Lambda::Function").values()
                      if f["Properties"].get("Handler") == "lambda_escaneo.handler"]
        assert "VpcConfig" not in funcion["Properties"]
        assert "HLF_EXAMENES_KMS_KEY_ID" in variables and variables.get("HLF_EXAMENES_ESCANEO") == "1"
    else:
        assert not planes
        if entorno == "demo":
            assert variables.get("HLF_EXAMENES_ESCANEO") == "0"


def test_observabilidad_tablero_alarmas_y_presupuesto(plantillas):
    """F0013: tablero `hlf-<entorno>`, alarmas de API, backend y Lambdas al tema SNS; en demo también RDS, corrida
    nocturna (log + EventBridge) y presupuesto con alertas al 50, 80 y 100 %."""
    entorno, t = plantillas
    o = t["observabilidad"]
    o.has_resource_properties("AWS::CloudWatch::Dashboard", {"DashboardName": f"hlf-{entorno}"})
    nombres = {a["Properties"]["AlarmName"] for a in _recursos(o, "AWS::CloudWatch::Alarm").values()}
    base = {f"hlf-{entorno}-{n}" for n in ("api-5xx", "backend-tareas", "lambda-whatsapp")}
    assert base <= nombres
    con_rds = {f"hlf-{entorno}-{n}" for n in ("rds-almacenamiento", "nocturno-fallido", "lambda-voz")}
    assert (con_rds <= nombres) == (entorno == "demo")
    assert all(a["Properties"]["AlarmActions"] for a in _recursos(o, "AWS::CloudWatch::Alarm").values())
    tareas = next(a for a in _recursos(o, "AWS::CloudWatch::Alarm").values()
                  if a["Properties"]["AlarmName"].endswith("backend-tareas"))["Properties"]
    assert tareas["TreatMissingData"] == "breaching" and tareas["EvaluationPeriods"] * tareas["Period"] <= 600
    presupuestos = list(_recursos(o, "AWS::Budgets::Budget").values())
    if entorno == "demo":
        (p,) = presupuestos
        umbrales = sorted(n["Notification"]["Threshold"] for n in p["Properties"]["NotificationsWithSubscribers"])
        assert umbrales == [50, 80, 100]
        o.has_resource_properties("AWS::Logs::MetricFilter", {"MetricTransformations": [Match.object_like(
            {"MetricName": "NocturnoFallido"})]})
        (regla,) = _recursos(o, "AWS::Events::Rule").values()
        assert regla["Properties"]["EventPattern"]["detail"]["containers"]["name"] == ["nocturno"]
    else:
        assert not presupuestos
    # Sin correo en el repo: la suscripción solo aparece si HLF_CORREO_ALARMAS está definido al desplegar
    assert not _recursos(o, "AWS::SNS::Subscription")


def test_seguridad_waf_y_cloudtrail_solo_donde_se_activan(plantillas):
    """F0013: WAF y CloudTrail tienen costo fijo; ni dev ni demo los crean (decisión del plan)."""
    _, t = plantillas
    assert not _recursos(t["seguridad"], "AWS::WAFv2::WebACL")
    assert not _recursos(t["seguridad"], "AWS::CloudTrail::Trail")
    (dist,) = _recursos(t["frontend"], "AWS::CloudFront::Distribution").values()
    assert "WebACLId" not in dist["Properties"]["DistributionConfig"]


@pytest.fixture(scope="module")
def piloto(tmp_path_factory, monkeypatch_module):
    monkeypatch_module.setenv("HLF_REGION", "us-east-1")
    monkeypatch_module.setenv("HLF_CUENTA", "123456789012")
    monkeypatch_module.setenv("HLF_CORREO_ALARMAS", "equipo@example.org")
    dist = tmp_path_factory.mktemp("dist_piloto")
    (dist / "index.html").write_text("<!doctype html><title>HLF</title>", encoding="utf-8")
    app = cdk.App(context={"entorno": "piloto"})
    stacks = construir(app, "piloto", dist=dist)
    return {nombre: Template.from_stack(s) for nombre, s in stacks.items()}


@pytest.fixture(scope="module")
def monkeypatch_module():
    with pytest.MonkeyPatch.context() as mp:
        yield mp


def test_piloto_cumple_la_lista_previa_a_datos_reales(piloto):
    """F0013, lista de verificación: NAT y tareas privadas, CMK en datos y logs, WAF con inyección SQL y solo Chile,
    CloudTrail multirregión con bloqueo de objetos, AWS Backup con copia en otra región, RDS 35 días, rotación del
    secreto, MFA obligatorio y logs de un año."""
    t = piloto
    assert _recursos(t["red"], "AWS::EC2::NatGateway")
    tarea = next(x for x in _recursos(t["backend"], "AWS::ECS::TaskDefinition").values()
                 if not x["Properties"]["ContainerDefinitions"][0].get("Command"))
    assert tarea                                                               # sigue habiendo API
    (servicio,) = _recursos(t["backend"], "AWS::ECS::Service").values()
    assert servicio["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]["AssignPublicIp"] == "DISABLED"
    bucket = next(b for b in _recursos(t["datos"], "AWS::S3::Bucket").values() if "CorsConfiguration" in b["Properties"])
    regla = bucket["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
    assert regla["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "aws:kms"
    (base,) = _recursos(t["datos"], "AWS::RDS::DBInstance").values()
    assert "KmsKeyId" in base["Properties"] and base["Properties"]["BackupRetentionPeriod"] == 35
    assert _recursos(t["datos"], "AWS::SecretsManager::RotationSchedule")
    (grupo,) = [g for g in _recursos(t["backend"], "AWS::Logs::LogGroup").values()]
    assert grupo["Properties"]["RetentionInDays"] == 365 and "KmsKeyId" in grupo["Properties"]
    (acl,) = _recursos(t["seguridad"], "AWS::WAFv2::WebACL").values()
    reglas = {r["Name"]: r for r in acl["Properties"]["Rules"]}
    assert {"SoloChile", "LimitePorIp", "AWSManagedRulesCommonRuleSet", "AWSManagedRulesKnownBadInputsRuleSet",
            "AWSManagedRulesSQLiRuleSet"} <= set(reglas) and acl["Properties"]["Scope"] == "CLOUDFRONT"
    (dist,) = _recursos(t["frontend"], "AWS::CloudFront::Distribution").values()
    assert "WebACLId" in dist["Properties"]["DistributionConfig"]
    (trail,) = _recursos(t["seguridad"], "AWS::CloudTrail::Trail").values()
    assert trail["Properties"]["IsMultiRegionTrail"] and trail["Properties"]["EnableLogFileValidation"]
    auditoria = next(b for b in _recursos(t["seguridad"], "AWS::S3::Bucket").values() if b["Properties"].get("ObjectLockEnabled"))
    assert auditoria["Properties"]["ObjectLockConfiguration"]["Rule"]["DefaultRetention"]["Mode"] == "GOVERNANCE"
    (plan,) = _recursos(t["seguridad"], "AWS::Backup::BackupPlan").values()
    (regla_respaldo,) = plan["Properties"]["BackupPlan"]["BackupPlanRule"]
    assert "us-west-2" in json.dumps(regla_respaldo["CopyActions"])
    assert "respaldo_copia" in t and _recursos(t["respaldo_copia"], "AWS::Backup::BackupVault")
    t["identidad"].has_resource_properties("AWS::Cognito::UserPool", {"MfaConfiguration": "ON"})
    t["observabilidad"].has_resource_properties("AWS::SNS::Subscription", {"Protocol": "email"})
    assert _recursos(t["asistente"], "AWS::GuardDuty::MalwareProtectionPlan")      # escaneo obligatorio
    assert "voz" not in t                                                      # sin voz en el piloto


def test_todo_lleva_etiquetas_proyecto_y_entorno(piloto):
    """F0013, criterio: ningún recurso etiquetable sin `proyecto` y `entorno` en el entorno real."""
    for nombre, t in piloto.items():
        for id_logico, r in t.to_json()["Resources"].items():
            etiquetas = r.get("Properties", {}).get("Tags")
            if isinstance(etiquetas, list) and etiquetas and isinstance(etiquetas[0], dict) and "Key" in etiquetas[0]:
                claves = {e["Key"] for e in etiquetas}
                assert {"proyecto", "entorno"} <= claves, (nombre, id_logico)
