"""Observabilidad y costos (F0013): tablero `hlf-<entorno>`, alarmas a un tema SNS (correo del equipo) y presupuesto.

Alarmas (todas al mismo tema; el correo sale de HLF_CORREO_ALARMAS al desplegar):
- API con 5xx > 5 % durante 5 minutos (errores del backend y del ALB, que da 503 si no hay tareas sanas).
- Backend con menos tareas sanas que las deseadas (tarea detenida o reiniciando) durante 2 de 3 minutos.
- RDS con almacenamiento libre < 20 %.
- Corrida nocturna fallida (F0006): por su línea de log y por la tarea ECS que termina con código distinto de 0.
- Errores en las Lambdas del asistente y del escaneo de exámenes.
Cómo reaccionar a cada una: infra/README.md, "Runbook".
"""
from __future__ import annotations

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as acciones
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as suscripciones
from constructs import Construct

from config.entornos import Entorno

from .backend import BackendStack
from .datos import DatosStack

UMBRALES_PRESUPUESTO = (50, 80, 100)
UN_MINUTO, CINCO_MINUTOS = Duration.minutes(1), Duration.minutes(5)


class ObservabilidadStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, datos: DatosStack, backend: BackendStack,
                 lambdas: dict[str, lambda_.IFunction] | None = None, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: tablero, alarmas y presupuesto (F0013)", **kwargs)
        lambdas = lambdas or {}
        espacio = f"HLF/{entorno.nombre}"

        self.tema = sns.Topic(self, "Alarmas", display_name=f"HLF {entorno.nombre}: alarmas")
        if entorno.correo_alarmas:
            self.tema.add_subscription(suscripciones.EmailSubscription(entorno.correo_alarmas))
        accion = acciones.SnsAction(self.tema)
        self.alarmas: dict[str, cw.Alarm] = {}

        def alarma(nombre: str, descripcion: str, **props) -> cw.Alarm:
            a = cw.Alarm(self, nombre, alarm_name=f"hlf-{entorno.nombre}-{nombre}", alarm_description=descripcion,
                         **props)
            a.add_alarm_action(accion)
            a.add_ok_action(accion)
            self.alarmas[nombre] = a
            return a

        # -- API: 5xx y latencia ----------------------------------------------------------------------------
        alb = backend.alb.metrics
        peticiones = alb.request_count(period=UN_MINUTO)
        errores_api = cw.MathExpression(
            expression="IF(req >= 20, 100 * (FILL(e5t, 0) + FILL(e5e, 0)) / req, 0)", label="% 5xx", period=UN_MINUTO,
            using_metrics={"req": peticiones,
                           "e5t": alb.http_code_target(elbv2.HttpCodeTarget.TARGET_5XX_COUNT, period=UN_MINUTO),
                           "e5e": alb.http_code_elb(elbv2.HttpCodeElb.ELB_5XX_COUNT, period=UN_MINUTO)})
        alarma("api-5xx", "La API responde 5xx en más del 5 % de las peticiones durante 5 minutos",
               metric=errores_api, threshold=5, evaluation_periods=5,
               comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
               treat_missing_data=cw.TreatMissingData.NOT_BREACHING)
        latencia = alb.target_response_time(period=CINCO_MINUTOS, statistic="p90")

        # -- Backend: tareas sanas --------------------------------------------------------------------------
        sanas = backend.objetivo.metrics.healthy_host_count(period=UN_MINUTO, statistic="Minimum")
        alarma("backend-tareas", f"El backend tiene menos de {backend.tareas_deseadas} tarea(s) sana(s): "
               "detenida, reiniciando o sin pasar el health check",
               metric=sanas, threshold=backend.tareas_deseadas, evaluation_periods=3, datapoints_to_alarm=2,
               comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD,
               treat_missing_data=cw.TreatMissingData.BREACHING)
        dims_servicio = {"ClusterName": backend.cluster.cluster_name, "ServiceName": backend.servicio.service_name}
        corriendo = cw.Metric(namespace="ECS/ContainerInsights", metric_name="RunningTaskCount",
                              dimensions_map=dims_servicio, period=UN_MINUTO, statistic="Minimum", label="Tareas")

        # -- RDS ---------------------------------------------------------------------------------------------
        widgets_rds: list[cw.IWidget] = []
        if datos.rds is not None:
            asignado_bytes = 20 * 1024 ** 3            # allocated_storage de infra/stacks/datos.py
            alarma("rds-almacenamiento", "RDS con menos del 20 % de almacenamiento libre",
                   metric=datos.rds.metric_free_storage_space(period=CINCO_MINUTOS, statistic="Minimum"),
                   threshold=0.2 * asignado_bytes, evaluation_periods=1,
                   comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD)
            widgets_rds = [
                cw.GraphWidget(title="RDS: conexiones y CPU", width=8,
                               left=[datos.rds.metric_database_connections(period=CINCO_MINUTOS)],
                               right=[datos.rds.metric_cpu_utilization(period=CINCO_MINUTOS)]),
                cw.GraphWidget(title="RDS: almacenamiento libre (bytes)", width=8,
                               left=[datos.rds.metric_free_storage_space(period=CINCO_MINUTOS)]),
            ]

        # -- Corrida nocturna (F0006) ------------------------------------------------------------------------
        widgets_nocturno: list[cw.IWidget] = []
        if backend.nocturno is not None:
            metricas = {}
            for nombre, patron in (("NocturnoOk", '{ $.evento = "nocturno" && $.resultado = "ok" }'),
                                   ("NocturnoFallido", '{ $.evento = "nocturno" && $.resultado != "ok" }')):
                logs.MetricFilter(self, f"Filtro{nombre}", log_group=backend.grupo_logs, metric_namespace=espacio,
                                  metric_name=nombre, filter_pattern=logs.FilterPattern.literal(patron),
                                  metric_value="1", default_value=0)
                metricas[nombre] = cw.Metric(namespace=espacio, metric_name=nombre, period=Duration.hours(1),
                                             statistic="Sum", label=nombre)
            alarma("nocturno-fallido", "La consolidación nocturna terminó con error o con entregas rechazadas",
                   metric=metricas["NocturnoFallido"], threshold=1, evaluation_periods=1,
                   comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                   treat_missing_data=cw.TreatMissingData.NOT_BREACHING)
            # Si la tarea muere sin escribir su línea (memoria, imagen, red), avisa EventBridge
            events.Rule(self, "NocturnoDetenido", description="Tarea nocturna terminada con código distinto de 0",
                        event_pattern=events.EventPattern(
                            source=["aws.ecs"], detail_type=["ECS Task State Change"],
                            detail={"clusterArn": [backend.cluster.cluster_arn], "lastStatus": ["STOPPED"],
                                    "containers": {"name": ["nocturno"], "exitCode": [{"anything-but": 0}]}}),
                        targets=[targets.SnsTopic(self.tema, message=events.RuleTargetInput.from_text(
                            f"HLF {entorno.nombre}: la consolidación nocturna terminó con error. Tarea "
                            f"{events.EventField.from_path('$.detail.taskArn')}, motivo: "
                            f"{events.EventField.from_path('$.detail.stoppedReason')}. Ver infra/README.md, Runbook."))])
            widgets_nocturno = [cw.GraphWidget(title="Corrida nocturna (por hora)", width=8,
                                               left=list(metricas.values()), stacked=True)]

        # -- Lambdas -----------------------------------------------------------------------------------------
        for nombre, funcion in lambdas.items():
            alarma(f"lambda-{nombre}", f"La Lambda {nombre} tuvo errores en los últimos 5 minutos",
                   metric=funcion.metric_errors(period=CINCO_MINUTOS, statistic="Sum"), threshold=1,
                   evaluation_periods=1, comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                   treat_missing_data=cw.TreatMissingData.NOT_BREACHING)

        # -- Presupuesto -------------------------------------------------------------------------------------
        if entorno.presupuesto_usd:
            self.tema.add_to_resource_policy(iam.PolicyStatement(
                actions=["sns:Publish"], resources=[self.tema.topic_arn],
                principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
                conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
            budgets.CfnBudget(self, "Presupuesto", budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=f"hlf-{entorno.nombre}", budget_type="COST", time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=entorno.presupuesto_usd, unit="USD")),
                notifications_with_subscribers=[budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL", comparison_operator="GREATER_THAN", threshold=umbral,
                        threshold_type="PERCENTAGE"),
                    subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="SNS",
                                                                     address=self.tema.topic_arn)])
                    for umbral in UMBRALES_PRESUPUESTO])

        # -- Tablero -----------------------------------------------------------------------------------------
        modelos = [m for m in {entorno.bedrock_model_id, entorno.asistente_modelo_id} if m]
        bedrock = lambda metrica, estadistica="Sum": [
            cw.Metric(namespace="AWS/Bedrock", metric_name=metrica, dimensions_map={"ModelId": m},
                      period=Duration.hours(1), statistic=estadistica, label=m.split(".")[-1][:28]) for m in modelos]
        athena = cw.MathExpression(
            expression=f"SUM(SEARCH('{{AWS/Athena,QueryState,QueryType,WorkGroup}} MetricName=\"ProcessedBytes\" "
                       f"WorkGroup=\"{entorno.workgroup}\"', 'Sum', 3600))",
            label="Bytes escaneados", period=Duration.hours(1))
        costo = cw.Metric(namespace="AWS/Billing", metric_name="EstimatedCharges", dimensions_map={"Currency": "USD"},
                          period=Duration.hours(6), statistic="Maximum", region="us-east-1", label="USD del mes")
        tablero = cw.Dashboard(self, "Tablero", dashboard_name=f"hlf-{entorno.nombre}",
                               default_interval=Duration.hours(24))
        tablero.add_widgets(
            cw.AlarmStatusWidget(title="Estado", alarms=list(self.alarmas.values()), width=16, height=4),
            cw.SingleValueWidget(title="Costo estimado del mes (requiere alertas de facturación)", metrics=[costo],
                                 width=8, height=4, set_period_to_time_range=False),
        )
        tablero.add_widgets(
            cw.GraphWidget(title="API: peticiones y % 5xx", width=8, left=[peticiones], right=[errores_api]),
            cw.GraphWidget(title="API: latencia p90 (s)", width=8, left=[latencia]),
            cw.GraphWidget(title="Backend: tareas sanas y en ejecución", width=8, left=[sanas, corriendo]),
        )
        tablero.add_widgets(
            cw.GraphWidget(title="Backend: CPU y memoria (%)", width=8,
                           left=[backend.servicio.metric_cpu_utilization(period=CINCO_MINUTOS),
                                 backend.servicio.metric_memory_utilization(period=CINCO_MINUTOS)]),
            *widgets_rds)
        fila = [*widgets_nocturno]
        if lambdas:
            fila.append(cw.GraphWidget(title="Lambdas: errores", width=8,
                                       left=[f.metric_errors(period=CINCO_MINUTOS, label=n) for n, f in lambdas.items()]))
        if modelos:
            fila.append(cw.GraphWidget(title="Bedrock: tokens (entrada / salida) y latencia", width=8,
                                       left=bedrock("InputTokenCount") + bedrock("OutputTokenCount"),
                                       right=bedrock("InvocationLatency", "p90")))
        fila.append(cw.GraphWidget(title="Athena: bytes escaneados", width=8, left=[athena]))
        tablero.add_widgets(*fila)

        CfnOutput(self, "SalidaTemaAlarmas", value=self.tema.topic_arn)
        CfnOutput(self, "SalidaTablero", value=f"https://console.aws.amazon.com/cloudwatch/home#dashboards:name=hlf-{entorno.nombre}")
