#!/usr/bin/env bash
# Simulacros de F0013 (criterios de aceptación). Cada uno se corre a propósito y deja el sistema como estaba.
#
#   bash infra/scripts/simulacro.sh alarma      # fuerza el estado ALARM de api-5xx: llega el correo y vuelve a OK
#   bash infra/scripts/simulacro.sh tarea       # detiene una tarea del backend: la alarma backend-tareas, < 10 min
#   bash infra/scripts/simulacro.sh waf         # una inyección SQL conocida debe volver 403 desde CloudFront
#
# ENTORNO=demo por defecto (waf solo existe en piloto).
set -euo pipefail

entorno="${ENTORNO:-demo}"
Ent="$(tr '[:lower:]' '[:upper:]' <<< "${entorno:0:1}")${entorno:1}"
salida() { aws cloudformation describe-stacks --stack-name "Hlf${Ent}-$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text; }

case "${1:-}" in
  alarma)
    aws cloudwatch set-alarm-state --alarm-name "hlf-${entorno}-api-5xx" --state-value ALARM \
        --state-reason "Simulacro F0013 (infra/scripts/simulacro.sh)"
    echo "hlf-${entorno}-api-5xx en ALARM: revisa el correo. CloudWatch la devuelve a OK en el próximo minuto."
    ;;
  tarea)
    cluster=$(salida Backend SalidaCluster); servicio=$(salida Backend SalidaServicio)
    tarea=$(aws ecs list-tasks --cluster "$cluster" --service-name "$servicio" --query "taskArns[0]" --output text)
    aws ecs stop-task --cluster "$cluster" --task "$tarea" --reason "Simulacro F0013" > /dev/null
    echo "Tarea detenida a las $(date +%H:%M:%S). ECS la reemplaza sola; la alarma hlf-${entorno}-backend-tareas"
    echo "debe llegar por correo antes de 10 minutos (y volver a OK cuando la nueva pase el health check)."
    ;;
  waf)
    url=$(salida Frontend Url)
    codigo=$(curl -s -o /dev/null -w "%{http_code}" "${url}/api/salud?id=1%27%20OR%20%271%27%3D%271")
    echo "Respuesta a la inyección SQL: ${codigo} (esperado 403, bloqueado por WAF antes del backend)"
    [ "$codigo" = "403" ]
    ;;
  *)
    sed -n '2,8p' "$0"; exit 2 ;;
esac
