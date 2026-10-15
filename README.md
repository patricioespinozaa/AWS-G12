# Dataset – Atención Ambulatoria Dinámica HLF

Reto: Priorización Clínica Evolutiva y Uso del Recurso Box.
Datos 100% sintéticos. Semilla 20261013. Fecha de referencia 2026-10-13. 500 pacientes.

## Idea del reto
La prioridad de la lista de espera debe MOVERSE según cómo evoluciona el paciente mientras espera.
El dataset es una SERIE TEMPORAL de eventos: cada equipo diseña su propio algoritmo de priorización
dinámica y de uso de box. NO hay respuesta de referencia.

## Archivos (se unen por id_paciente; agenda_box es del hospital)

actualizar mediante Scoring, 


lista de demenisticas, criterios de que suban el scoring para que vaya sumando su problema, 




intercoustla pasa tiempo durante este irmpo la persona puede estar dentyro 
trazabilidad integracion de dtos

integrar dot ala infromacio que sucede en tel intergavto que yo le di priodadi media, opase a alta , a quien voy asignar los 30 cupos,

mas antugo amas nuevo, 


ASG 

G1 G2 G3


g1 pueden conseumir menos productos porque son menos riesgosos

g2 mitad

g3 consumer mas riesgos 

APS

misma prioridad del rieso G dependienod de la interconsutla

esttratificacion de riesgo 

repriorizacion instantanea, tomando de todos los items anteriores, para una vez despues de la repriozaicon , se reconsideren las variables les avise la medico quuien puede esperar o no

orden de todos factores, 

estos van a dar un alista, incial, 

ACG
GRD

funcionesles, 

listas de esperas distinas, consulta unueva especilidad, 

fx serian los examenes , pruebas funcionales

viau es antes de entrar al hopsitla que vea el dorcor

Qx qirurjicas

prioriodcasa de pasa ala ficha clininca thalamus , 
cud canad unica dericacion

qx lsita de esperasm

GRD es el consumo de recursos dque seria el pago de las para darle el Riesgo ACG, 


listo 



ALTA
MEDIA   
BAJA


APS trabaja sesde el cud


el acg les serviria 
medicina general a especialista


thalamus puede ser de especialista a especialista

dentro del sistemano tienen manera de saber hasta que llega al thalamus, 
a veces no se sabe del registro, porque no se sabe que es lo que le "pasa" al cliente hsata uqe llega a la consulta, que podíra pasar meses hasta que se vea




les serviria que el cud pudiera ser un aviso/alerta, para que sea revisado, ejemplo, si el usuario hizo la consulta para que le revisaran el corazon, por problemas cardiacos
deberia poder llegar un aviso o alerta para que el médico pueda revisar, si es necesario editar la prioridar ya que el paciente fue antes de que lograra entrar a la consulta incial, ese fue antes, puede ser porque se sintio mal de él corazon o tuvo un pre-infarto, y fue a urgencia o pidio una cita urgente con mas antelación, esas metricas no están funcionando "juntas" o siendo leidas por el software para avisar de alguna manera que el paciente volvió a ir por culpa de sus problemas al corazon. 


| Archivo | Filas | Grano |
|---|---|---|
| pacientes.csv | 500 | un paciente (tabla maestra) |
| lista_espera.csv | 500 | una solicitud en espera |
| eventos_clinicos.csv | 786 | un evento con fecha |
| mediciones.csv | 2487 | una medición con fecha |
| agenda_box.csv | 2188 | un bloque de agenda de un box |
| citaciones.csv | 257 | una cita ofrecida |
| perfiles.json | 500 | un objeto por paciente con sus series anidadas |

## Notas
- id_paciente ficticio (PAC-HLF-#####); sin RUT ni nombres reales.
- Comunas de la Red Sur Oriente (contexto Hospital La Florida); pacientes sintéticos.
- Diagnósticos con CIE-10 reales asignados sintéticamente.
- Para recalcular prioridad a una fecha de corte: usar solo eventos/mediciones con fecha <= corte.
- Control de exclusión: pacientes fallecidos deben salir de la lista (fallecido=true, fecha_defuncion).
