"""Pruebas de ejemplo de U2 (PBT-10) con cliente falso: nunca llaman a Bedrock."""

from __future__ import annotations

import functools
import itertools
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ayudantes import evento, medicion, perfil_base
from estrategias.copiloto import (
    RESUMEN_FALSO,
    correr_lote,
    datos_de_usuario,
    entrada_desde_datos,
    escribir_dataset,
    responder_eco,
)
from hlf_priorizacion.copiloto import cli
from hlf_priorizacion.copiloto.cliente import (
    ClienteFalso,
    ErrorPermisos,
    ErrorReintentable,
    PeticionModelo,
    RespuestaModelo,
    con_reintentos,
    esquema_herramienta,
    respuesta_falsa,
)
from hlf_priorizacion.copiloto.config import (
    MODELO_RESPALDO,
    ConfigModelo,
    ErrorConfiguracion,
    config_desde_entorno,
)
from hlf_priorizacion.copiloto.persistencia import leer_analisis, leer_fallidos
from hlf_priorizacion.copiloto.prompt import cargar_prompt

V = "reglas-v0.1.0"
ENTORNO = {"HLF_COPILOTO_CONCURRENCIA": "2"}


def _perfiles() -> list[dict[str, Any]]:
    """Dos pacientes: uno sube a crítica el 2026-07-20 (urgencia ESI 2), otro queda en gestión (sin registros)."""
    p1 = perfil_base(
        eventos_clinicos=[evento("EV-000001", "2026-07-20", "visita_urgencia", "triage ESI 2", "grave")],
        mediciones=[
            medicion("2026-06-01", "presion_sistolica", 120, "mmHg"),
            medicion("2026-07-08", "presion_sistolica", 167, "mmHg", True),
        ],
    )
    p2 = perfil_base(id_paciente="PAC-TST-00002")
    p2["lista_espera"]["id_solicitud"] = "IC-TST-00002"
    return [p1, p2]


@pytest.fixture
def entorno(tmp_path: Path) -> tuple[Path, Path]:
    datos = escribir_dataset(tmp_path / "datos", _perfiles())
    salidas = tmp_path / "salidas"
    correr_lote(datos, salidas, [date(2026, 7, 20), date(2026, 7, 21)])
    return datos, salidas


def _args(datos: Path, salidas: Path, *extra: str) -> list[str]:
    return [*extra, "--datos", str(datos), "--salidas", str(salidas)]


def _eventos(salidas: Path) -> list[dict[str, Any]]:
    ruta = salidas / "auditoria" / "eventos.jsonl"
    return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- CLI extremo a extremo


def test_corte_extremo_a_extremo_e_idempotente(entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    datos, salidas = entorno
    cliente = ClienteFalso(responder_eco)
    args = _args(datos, salidas, "--fecha-corte", "2026-07-20")
    assert cli.main(args, cliente=cliente, entorno=ENTORNO) == cli.SALIDA_OK
    salida = capsys.readouterr()
    assert len(cliente.llamadas) == 1 and cliente.llamadas[0].id_solicitud == "IC-TST-00001"
    assert "Analizadas: 1" in salida.out and "'gestion': 1" in salida.out
    # Logs JSON sin texto del modelo ni valores clínicos ni datos personales (C7.2).
    for linea in salida.err.strip().splitlines():
        assert {"timestamp", "nivel", "id_ejecucion", "mensaje"} <= set(json.loads(linea))
    for prohibido in (RESUMEN_FALSO, "167", "Comuna A", "Paciente Prueba", "FONASA"):
        assert prohibido not in salida.err

    analisis = leer_analisis(salidas, date(2026, 7, 20), V)
    assert len(analisis) == 1
    a = analisis[0]
    assert a.analisis.prioridad_sugerida == "critica"
    assert a.analisis.metadatos.estado == "pendiente_revision_medica"
    assert a.analisis.metadatos.model_id == ConfigModelo().model_id
    assert a.version_prompt == "copiloto-v1.2.0" and a.huella_prompt == cargar_prompt().huella
    assert a.revision_equidad == []
    tipos = [e["tipo"] for e in _eventos(salidas) if e["actor"] == "sistema:copiloto"]
    assert sorted(tipos) == ["analisis_ia", "analisis_omitido", "llamada_modelo"]
    # La E/S completa del modelo queda en salidas/copiloto_io, referenciada por huella.
    llamada = next(e for e in _eventos(salidas) if e["tipo"] == "llamada_modelo")
    io = salidas / "copiloto_io" / "fecha_corte=2026-07-20"
    assert (io / (llamada["huella_salida"].removeprefix("sha256:") + ".json")).is_file()

    # Segunda ejecución: ninguna llamada nueva y sin duplicados (C5.1).
    cliente2 = ClienteFalso(responder_eco)
    assert cli.main(args, cliente=cliente2, entorno=ENTORNO) == cli.SALIDA_OK
    assert cliente2.llamadas == []
    assert "invocaciones al modelo: 0" in capsys.readouterr().out
    assert leer_analisis(salidas, date(2026, 7, 20), V) == analisis


def test_rango_omite_sin_cambio_y_envia_evaluacion_anterior(entorno: tuple[Path, Path]) -> None:
    datos, salidas = entorno
    cliente = ClienteFalso(responder_eco)
    args = _args(datos, salidas, "--desde", "2026-07-20", "--hasta", "2026-07-21")
    assert cli.main(args, cliente=cliente, entorno=ENTORNO) == cli.SALIDA_OK
    # 07-20 se analiza (primer día, sin anterior); 07-21 no cambió: sin_cambio_en_rango.
    assert [p.id_solicitud for p in cliente.llamadas] == ["IC-TST-00001"]
    assert datos_de_usuario(cliente.llamadas[0].usuario)["evaluacion_anterior"] is None
    omitidas = [e for e in _eventos(salidas) if e["tipo"] == "analisis_omitido" and e["fecha_corte"] == "2026-07-21"]
    motivos = {e["id_solicitud"]: e["motivo"] for e in omitidas}
    assert motivos == {"IC-TST-00001": "sin_cambio_en_rango", "IC-TST-00002": "gestion"}
    assert next(e for e in omitidas if e["id_solicitud"] == "IC-TST-00001")["referencia_fecha_corte"] == "2026-07-20"

    # --forzar analiza 07-21 e incluye la evaluación del 07-20.
    forzado = ClienteFalso(responder_eco)
    assert cli.main([*args, "--forzar"], cliente=forzado, entorno=ENTORNO) == cli.SALIDA_OK
    assert [p.id_solicitud for p in forzado.llamadas] == ["IC-TST-00001"]
    anterior = datos_de_usuario(forzado.llamadas[0].usuario)["evaluacion_anterior"]
    assert anterior["fecha_corte"] == "2026-07-20"


# --------------------------------------------------------------------------- C2.3: errores de fecha


@pytest.mark.parametrize(
    "extra",
    [
        ["--fecha-corte", "2026-7-20"],
        ["--fecha-corte", "2026-02-30"],
        ["--fecha-corte", "20260720"],
        ["--desde", "2026/07/19", "--hasta", "2026-07-20"],
    ],
)
def test_formato_de_fecha_invalido_sale_con_2(entorno: tuple[Path, Path], extra: list[str]) -> None:
    datos, salidas = entorno
    cliente = ClienteFalso(responder_eco)
    with pytest.raises(SystemExit) as e:
        cli.main(_args(datos, salidas, *extra), cliente=cliente, entorno=ENTORNO)
    assert e.value.code == cli.SALIDA_ENTRADA
    assert cliente.llamadas == []


@pytest.mark.parametrize(
    ("extra", "mensaje"),
    [
        (["--desde", "2026-07-20", "--hasta", "2026-07-20"], "estrictamente anterior"),
        (["--desde", "2026-07-21", "--hasta", "2026-07-20"], "estrictamente anterior"),
        (["--fecha-corte", "2026-10-14"], "posterior a la fecha de extracción"),
        (["--desde", "2026-10-01", "--hasta", "2026-10-14"], "posterior a la fecha de extracción"),
        (["--desde", "2026-06-01", "--hasta", "2026-07-02"], "el máximo es 31"),
        (["--fecha-corte", "2026-07-20", "--desde", "2026-07-19", "--hasta", "2026-07-20"], "no se puede combinar"),
        (["--desde", "2026-07-19"], "se usan juntos"),
        ([], "indique --fecha-corte"),
    ],
)
def test_reglas_de_fecha_c23(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str], extra: list[str], mensaje: str
) -> None:
    datos, salidas = entorno
    cliente = ClienteFalso(responder_eco)
    assert cli.main(_args(datos, salidas, *extra), cliente=cliente, entorno=ENTORNO) == cli.SALIDA_ENTRADA
    assert cliente.llamadas == []
    salida = capsys.readouterr().out
    assert mensaje in salida and "No se llamó a Bedrock" in salida


def test_rango_de_31_dias_es_aceptado_hasta_el_lote(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    datos, salidas = entorno
    args = _args(datos, salidas, "--desde", "2026-06-21", "--hasta", "2026-07-21")
    assert cli.main(args, cliente=ClienteFalso(responder_eco), entorno=ENTORNO) == cli.SALIDA_ENTRADA
    assert "faltan salidas del lote" in capsys.readouterr().out


def test_faltan_salidas_del_lote_lista_los_comandos(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    datos, salidas = entorno
    cliente = ClienteFalso(responder_eco)
    args = _args(datos, salidas, "--desde", "2026-07-19", "--hasta", "2026-07-21")
    assert cli.main(args, cliente=cliente, entorno=ENTORNO) == cli.SALIDA_ENTRADA
    salida = capsys.readouterr().out
    assert cliente.llamadas == []
    assert f'uv run hlf-lote --fecha-corte 2026-07-19 --datos "{datos}" --salidas "{salidas}"' in salida
    assert "2026-07-20 --datos" not in salida and "No se llamó a Bedrock" in salida
    assert not (salidas / "analisis").exists()


def test_tope_de_llamadas_no_llama_y_registra_limite(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    datos, salidas = entorno
    cliente = ClienteFalso(responder_eco)
    args = _args(datos, salidas, "--desde", "2026-07-20", "--hasta", "2026-07-21", "--forzar", "--max-llamadas", "1")
    assert cli.main(args, cliente=cliente, entorno=ENTORNO) == cli.SALIDA_ENTRADA
    assert cliente.llamadas == []
    salida = capsys.readouterr().out
    assert "Solicitudes pendientes: 2 (peor caso 16 invocaciones); presupuesto 1" in salida
    limites = [e for e in _eventos(salidas) if e.get("motivo") == "limite_llamadas"]
    assert len(limites) == 2


def test_el_peor_caso_sobre_el_presupuesto_no_aborta(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """C2.5: 2 pendientes con peor caso 16 y presupuesto 2 se ejecutan; sin reintentos alcanzan."""
    datos, salidas = entorno
    cliente = ClienteFalso(responder_eco)
    args = _args(datos, salidas, "--desde", "2026-07-20", "--hasta", "2026-07-21", "--forzar", "--max-llamadas", "2")
    assert cli.main(args, cliente=cliente, entorno=ENTORNO) == cli.SALIDA_OK
    assert len(cliente.llamadas) == 2
    assert "invocaciones al modelo: 2 de 2 (--max-llamadas) · sin procesar por limite_llamadas: 0" in (
        capsys.readouterr().out
    )


def test_presupuesto_agotado_a_mitad_deja_limite_llamadas_y_la_reejecucion_completa(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2.5: los reintentos de servicio consumen presupuesto; ninguna invocación pasa de --max-llamadas."""
    from hlf_priorizacion.copiloto import barrido

    monkeypatch.setattr(cli, "ejecutar_barrido", functools.partial(barrido.ejecutar_barrido, dormir=lambda _s: None))
    datos, salidas = entorno
    secuencial = {"HLF_COPILOTO_CONCURRENCIA": "1"}

    def nuevo_cliente() -> ClienteFalso:
        n = itertools.count(1)

        def responder(p: PeticionModelo) -> RespuestaModelo | Exception:
            # Cada solicitud: la primera invocación se limita (reintento de servicio), la segunda responde.
            return ErrorReintentable("ThrottlingException") if next(n) % 2 else responder_eco(p)

        return ClienteFalso(responder)

    args = _args(datos, salidas, "--desde", "2026-07-20", "--hasta", "2026-07-21", "--forzar")
    cliente = nuevo_cliente()
    assert cli.main([*args, "--max-llamadas", "3"], cliente=cliente, entorno=secuencial) == cli.SALIDA_FALLIDAS
    # 07-20: limitada + válida (2); 07-21: limitada (3) y el reintento ya no cabe: no se invoca.
    assert len(cliente.llamadas) == 3
    salida = capsys.readouterr().out
    assert "invocaciones al modelo: 3 de 3 (--max-llamadas) · sin procesar por limite_llamadas: 1" in salida
    assert len(leer_analisis(salidas, date(2026, 7, 20), V)) == 1
    assert leer_analisis(salidas, date(2026, 7, 21), V) == []
    assert leer_fallidos(salidas, date(2026, 7, 21), V) == []  # no es un fallido
    limites = [e for e in _eventos(salidas) if e["tipo"] == "analisis_omitido" and e["motivo"] == "limite_llamadas"]
    assert [(e["id_solicitud"], e["fecha_corte"]) for e in limites] == [("IC-TST-00001", "2026-07-21")]

    # Re-ejecución con presupuesto: 07-20 ya analizada, 07-21 se completa.
    cliente2 = nuevo_cliente()
    assert cli.main([*args, "--max-llamadas", "300"], cliente=cliente2, entorno=secuencial) == cli.SALIDA_OK
    assert len(cliente2.llamadas) == 2
    assert len(leer_analisis(salidas, date(2026, 7, 20), V)) == 1
    assert len(leer_analisis(salidas, date(2026, 7, 21), V)) == 1


def test_presupuesto_con_llamadas_en_curso_las_deja_terminar_y_no_empieza_otra() -> None:
    """C2.5 con solapamiento real: 3 llamadas abiertas a la vez agotan B = 3; una cuarta no empieza y las
    tres en curso terminan con su respuesta."""
    import threading

    from hlf_priorizacion.copiloto.barrido import ClienteConPresupuesto, LimiteLlamadas

    abiertas = threading.Barrier(4, timeout=10)  # 3 llamadas en curso + el hilo de la prueba
    liberar = threading.Event()

    def responder(p: PeticionModelo) -> RespuestaModelo:
        abiertas.wait()
        assert liberar.wait(10)
        return respuesta_falsa({"id_solicitud": p.id_solicitud})

    falso = ClienteFalso(responder)
    presupuesto = ClienteConPresupuesto(falso, 3)
    respuestas: dict[str, RespuestaModelo] = {}

    def invocar(i: int) -> None:
        pet = PeticionModelo(f"IC-{i}", "s", "u", {})
        respuestas[pet.id_solicitud] = presupuesto.converse(pet, ConfigModelo())

    hilos = [threading.Thread(target=invocar, args=(i,)) for i in range(3)]
    for h in hilos:
        h.start()
    abiertas.wait()  # las tres están dentro del cliente al mismo tiempo
    with pytest.raises(LimiteLlamadas):
        presupuesto.converse(PeticionModelo("IC-9", "s", "u", {}), ConfigModelo())
    assert len(falso.llamadas) == 3 and presupuesto.invocaciones == 3  # la cuarta no llegó al cliente
    liberar.set()
    for h in hilos:
        h.join(10)
    assert sorted(respuestas) == ["IC-0", "IC-1", "IC-2"]
    assert len(falso.llamadas) == presupuesto.invocaciones == 3


@pytest.mark.parametrize("valor", ["0", "9", "abc", "-1"])
def test_concurrencia_invalida_sale_con_2(entorno: tuple[Path, Path], valor: str) -> None:
    datos, salidas = entorno
    args = _args(datos, salidas, "--fecha-corte", "2026-07-20")
    entorno_malo = {"HLF_COPILOTO_CONCURRENCIA": valor}
    assert cli.main(args, cliente=ClienteFalso(responder_eco), entorno=entorno_malo) == cli.SALIDA_ENTRADA


def test_config_modelo() -> None:
    assert config_desde_entorno({}).model_id == "us.anthropic.claude-sonnet-5"
    assert config_desde_entorno({}).concurrencia == 4
    assert config_desde_entorno({"HLF_BEDROCK_MODEL_ID": MODELO_RESPALDO}).model_id == MODELO_RESPALDO
    with pytest.raises(ErrorConfiguracion):
        config_desde_entorno({"HLF_BEDROCK_MODEL_ID": "us.anthropic.claude-sonnet-5-5"})
    with pytest.raises(ErrorConfiguracion):
        config_desde_entorno({"HLF_BEDROCK_REGION": "us east"})


def test_temperatura_solo_a_modelos_que_la_aceptan() -> None:
    sonnet = config_desde_entorno({})
    assert not sonnet.envia_temperatura and "temperature" not in sonnet.inference_config()
    haiku = config_desde_entorno({"HLF_BEDROCK_MODEL_ID": MODELO_RESPALDO})
    assert haiku.inference_config() == {"maxTokens": 8192, "temperature": 0.0}
    nova = config_desde_entorno({"HLF_BEDROCK_MODEL_ID": "us.amazon.nova-pro-v1:0"})
    assert nova.inference_config()["temperature"] == 0.0


def test_el_analisis_registra_si_se_envio_temperatura(entorno: tuple[Path, Path]) -> None:
    datos, salidas = entorno
    args = _args(datos, salidas, "--fecha-corte", "2026-07-20")
    assert cli.main(args, cliente=ClienteFalso(responder_eco), entorno=ENTORNO) == cli.SALIDA_OK
    assert leer_analisis(salidas, date(2026, 7, 20), V)[0].temperatura_enviada is None
    entorno_haiku = {**ENTORNO, "HLF_BEDROCK_MODEL_ID": MODELO_RESPALDO}
    assert cli.main(args, cliente=ClienteFalso(responder_eco), entorno=entorno_haiku) == cli.SALIDA_OK
    por_modelo = {r.model_id: r.temperatura_enviada for r in leer_analisis(salidas, date(2026, 7, 20), V)}
    assert por_modelo == {"us.anthropic.claude-sonnet-5": None, MODELO_RESPALDO: 0.0}


# --------------------------------------------------------------------------- huella, permisos, reintentos


def test_huella_distinta_falla_sin_llamar(entorno: tuple[Path, Path]) -> None:
    datos, salidas = entorno
    perfiles = _perfiles()
    perfiles[0]["eventos_clinicos"].append(evento("EV-000002", "2026-07-10", "hospitalizacion", "ingreso UCI", "grave"))
    escribir_dataset(datos, perfiles)  # los datos cambiaron después del lote
    cliente = ClienteFalso(responder_eco)
    args = _args(datos, salidas, "--fecha-corte", "2026-07-20")
    assert cli.main(args, cliente=cliente, entorno=ENTORNO) == cli.SALIDA_FALLIDAS
    assert cliente.llamadas == []
    fallidos = leer_fallidos(salidas, date(2026, 7, 20), V)
    assert [(f.id_solicitud, f.motivo) for f in fallidos] == [("IC-TST-00001", "huella_distinta")]


def test_solicitud_ausente_del_dataset_es_contexto_no_disponible(entorno: tuple[Path, Path]) -> None:
    """Una solicitud que ya no está en el dataset no se confunde con una huella distinta."""
    datos, salidas = entorno
    escribir_dataset(datos, _perfiles()[1:])  # el paciente de IC-TST-00001 desapareció después del lote
    cliente = ClienteFalso(responder_eco)
    args = _args(datos, salidas, "--fecha-corte", "2026-07-20")
    assert cli.main(args, cliente=cliente, entorno=ENTORNO) == cli.SALIDA_FALLIDAS
    assert cliente.llamadas == []
    fallidos = leer_fallidos(salidas, date(2026, 7, 20), V)
    assert [(f.id_solicitud, f.motivo, f.intentos) for f in fallidos] == [("IC-TST-00001", "contexto_no_disponible", 0)]
    errores = [e for e in _eventos(salidas) if e["tipo"] == "error_proceso" and e.get("etapa") == "copiloto"]
    assert [e["motivo"] for e in errores] == ["contexto_no_disponible"]


def test_modelo_fuera_de_la_lista_sale_con_4_como_un_permiso_denegado(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    datos, salidas = entorno
    cliente = ClienteFalso(responder_eco)
    args = _args(datos, salidas, "--fecha-corte", "2026-07-20")
    malo = {**ENTORNO, "HLF_BEDROCK_MODEL_ID": "us.anthropic.claude-sonnet-5-5"}
    assert cli.main(args, cliente=cliente, entorno=malo) == cli.SALIDA_PERMISOS
    assert cliente.llamadas == []
    salida = capsys.readouterr().out
    assert "No se llamó a Bedrock" in salida and f"HLF_BEDROCK_MODEL_ID={MODELO_RESPALDO}" in salida
    # El resto de los errores de configuración siguen siendo exit 2.
    region_mala = {**ENTORNO, "HLF_BEDROCK_REGION": "us east"}
    assert cli.main(args, cliente=cliente, entorno=region_mala) == cli.SALIDA_ENTRADA


def test_permiso_denegado_sale_con_4_y_sugiere_respaldo(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    datos, salidas = entorno
    cliente = ClienteFalso(lambda _p: ErrorPermisos("AccessDeniedException"))
    args = _args(datos, salidas, "--fecha-corte", "2026-07-20")
    assert cli.main(args, cliente=cliente, entorno=ENTORNO) == cli.SALIDA_PERMISOS
    assert len(cliente.llamadas) == 1
    assert MODELO_RESPALDO in capsys.readouterr().out
    assert leer_fallidos(salidas, date(2026, 7, 20), V)[0].motivo == "permisos:AccessDeniedException"


def test_validacion_fallida_reintenta_una_vez_con_el_error(entorno: tuple[Path, Path]) -> None:
    datos, salidas = entorno

    def responder(p: PeticionModelo) -> RespuestaModelo:
        if p.intento == 1:
            return respuesta_falsa({"id_solicitud": p.id_solicitud})  # malformada
        return responder_eco(p)

    cliente = ClienteFalso(responder)
    assert cli.main(_args(datos, salidas, "--fecha-corte", "2026-07-20"), cliente=cliente, entorno=ENTORNO) == 0
    assert [p.intento for p in cliente.llamadas] == [1, 2]
    assert "rechazada por el validador" in cliente.llamadas[1].usuario
    assert leer_analisis(salidas, date(2026, 7, 20), V)[0].intentos == 2


def test_dos_validaciones_fallidas_dejan_analisis_fallido(entorno: tuple[Path, Path]) -> None:
    datos, salidas = entorno

    def responder(p: PeticionModelo) -> RespuestaModelo:
        e = entrada_desde_datos(datos_de_usuario(p.usuario), p.id_solicitud)
        e["justificacion"] = "Se sugiere bajar la prioridad por la comuna."
        return respuesta_falsa(e)

    cliente = ClienteFalso(responder)
    assert cli.main(_args(datos, salidas, "--fecha-corte", "2026-07-20"), cliente=cliente, entorno=ENTORNO) == 1
    assert len(cliente.llamadas) == 2
    f = leer_fallidos(salidas, date(2026, 7, 20), V)[0]
    assert f.motivo.startswith("validacion: equidad_atributo_no_disponible") and f.intentos == 2
    assert "equidad_atributo_no_disponible" in cliente.llamadas[1].usuario  # C6.7: el reintento lleva el error
    assert leer_analisis(salidas, date(2026, 7, 20), V) == []


RECHAZO, MARCA, NADA = "rechazo", "marca", "nada"


@pytest.mark.parametrize(
    ("frase", "esperado"),
    [
        # Frases que se colaron en las tres revisiones anteriores: la regla 1 no mira negaciones.
        ("No hay motivo urgente y por su comuna conviene bajarla.", RECHAZO),
        ("Paciente sin previsión, se sugiere postergar.", RECHAZO),
        ("Sin comuna registrada.", RECHAZO),
        ("Conviene bajarla no solo por su comuna.", RECHAZO),
        ("No solo por su nivel socioeconómico.", RECHAZO),
        ("No se debe bajar por la clínica, sino por su comuna.", RECHAZO),
        ("No corresponde bajarla, salvo por su previsión.", RECHAZO),
        ("Conviene no bajarla salvo por su comuna.", RECHAZO),
        ("Se baja la prioridad por su comuna.", RECHAZO),
        ("Bajamos la prioridad por su previsión.", RECHAZO),
        ("Paciente sin previsión; no corresponde postergar.", RECHAZO),
        # Mencionarlos aunque sea en negativo también rechaza; mayúsculas y tildes no importan.
        ("La comuna no se usa para decidir.", RECHAZO),
        ("No se consideró la PREVISION del paciente.", RECHAZO),
        ("Beneficiario FONASA.", RECHAZO),
        ("Tiene isapre.", RECHAZO),
        ("El NSE no influye.", RECHAZO),
        ("Nivel socioeconomico desconocido.", RECHAZO),
        # Formas separadas y derivadas (revisión review-equidad, hallazgos 1 y 2).
        ("nivel socio-económico bajo, conviene postergar", RECHAZO),
        ("nivel socio económico bajo, conviene postergar", RECHAZO),
        ("Situación previsional desconocida.", RECHAZO),
        ("Consultorio comunal de origen.", RECHAZO),
        ("Grupo N.S.E. C3.", RECHAZO),
        # Separadores, "_", afijos y vocabulario (review-equidad, segunda pasada, hallazgos 1 a 4).
        ("Nivel socio - económico bajo.", RECHAZO),
        ("Nivel socio\u2014económico bajo.", RECHAZO),
        ("Condición socio/económica precaria.", RECHAZO),
        ("Sin datos de comuna_residencia.", RECHAZO),
        ("El campo prevision_salud no está.", RECHAZO),
        ("Atención intercomunal.", RECHAZO),
        ("Previsionalmente cubierto.", RECHAZO),
        ("Afiliado al Fondo Nacional de Salud.", RECHAZO),
        ("Grupo GSE C3.", RECHAZO),
        # Tercera pasada de review-equidad: plurales de siglas, siglas con puntos y otra raíz.
        ("Pacientes de FONASAs distintas.", RECHAZO),
        ("Comparado con otros NSEs.", RECHAZO),
        ("Su socioeconomía no está registrada.", RECHAZO),
        ("Afiliado a F.O.N.A.S.A.", RECHAZO),
        ("Afiliada a I.S.A.P.R.E. privada.", RECHAZO),
        # Palabras comunes que no deben confundirse con las siglas cortas.
        ("Pensé que el ingreso fue reciente.", NADA),
        ("Se comunicó con el CESFAM para coordinar el examen.", NADA),
        ("Grupo N S E bajo.", RECHAZO),
        ("\uff26\uff2f\uff2e\uff21\uff33\uff21 tramo A.", RECHAZO),  # FONASA en ancho completo
        # Regla 2: inasistencias + verbo de bajada en la misma oración se marcan, aunque estén negadas.
        ("Se baja la prioridad por sus inasistencias.", MARCA),
        ("Las inasistencias no se usan para bajar la prioridad.", MARCA),
        ("El paciente no asistió a su cita, por lo que conviene bajar la prioridad.", MARCA),
        ("Registra una cita no_asistio y se sugiere postergarla.", MARCA),
        ("Dos citas fallidas no justifican una rebaja.", MARCA),
        ("Sus ausencias a citas no implican reducción de la urgencia.", MARCA),
        # Falsos positivos reales del primer barrido con Bedrock (2026-07-19): ahora se marcan, no se rechazan.
        ("No asistió a una cita (CT-000005), lo que no se usa aquí como motivo para bajar prioridad.", MARCA),
        ("La inasistencia (CT-000184) no debe interpretarse como mejoría ni usarse para bajar prioridad.", MARCA),
        # Inasistencias sin verbo de bajada en la misma oración: nada.
        ("Tiene inasistencias previas; se recomienda disminuir la prioridad.", NADA),
        ("Registra dos inasistencias (CT-000005); conviene confirmar la próxima cita.", NADA),
        ("El paciente no asistió a su última cita. Se sugiere postergar el examen.", NADA),
        ("Hay riesgo de no-show en la próxima cita.", NADA),
        # Verbo de bajada sin atributo: nada.
        ("Se sugiere postergar el control hasta tener la medición.", NADA),
        ("La presión bajó tras el ajuste de dosis.", NADA),
        ("La urgencia reciente obliga a subir la prioridad.", NADA),
        # Palabra completa: "comunicación" no es "comuna" ni "intenso" es "NSE".
        ("Se mejoró la comunicación con atención primaria por dolor intenso.", NADA),
        ("Evolución previsible; se comunicó el resultado.", NADA),
        ("Control comunitario; revisar insensible a cambios.", NADA),
    ],
)
def test_c65_regla_determinista_sin_negaciones(frase: str, esperado: str) -> None:
    from estrategias.copiloto import analisis_con_justificacion
    from hlf_priorizacion.copiloto.validacion import atributo_no_disponible, frases_revision_equidad

    a = analisis_con_justificacion(frase)
    rechazo = atributo_no_disponible(a)
    marcas = frases_revision_equidad(a)
    if esperado == RECHAZO:
        assert rechazo is not None and rechazo[0] == "justificacion"
    else:
        assert rechazo is None
        assert bool(marcas) is (esperado == MARCA)
        assert all(m.campo == "justificacion" and m.texto in frase for m in marcas)


def test_c65_atributo_en_cualquier_campo_de_texto() -> None:
    from estrategias.copiloto import analisis_con_justificacion
    from hlf_priorizacion.copiloto.validacion import atributo_no_disponible

    a = analisis_con_justificacion("Coincide con el motor.")
    casos = {
        "hallazgos[0].texto": {"hallazgos": [a.hallazgos[0].model_copy(update={"texto": "Vive en otra comuna."})]},
        "acciones_sugeridas[1]": {"acciones_sugeridas": ["Confirmar cita.", "Revisar previsión."]},
        "datos_faltantes[0]": {"datos_faltantes": ["NSE"]},
        "escalas_sustitutas[0]": {"escalas_sustitutas": ["nivel socioeconómico"]},
        "propuesta_agenda": {"propuesta_agenda": "Agendar según comuna."},
        "relacion_con_derivacion.texto": {
            "relacion_con_derivacion": a.relacion_con_derivacion.model_copy(update={"texto": "Por FONASA."})
        },
    }
    assert atributo_no_disponible(a) is None
    for campo, cambio in casos.items():
        hallado = atributo_no_disponible(a.model_copy(update=cambio))
        assert hallado is not None and hallado[0] == campo, campo


def test_c65_marca_se_guarda_y_se_lee_sin_texto_en_auditoria(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Regla 2: el análisis se guarda con la marca, leer_analisis la expone y la auditoría solo cuenta."""
    datos, salidas = entorno
    frase = "Las inasistencias (CT-INASISTENCIA-TEXTO) no se usan para bajar la prioridad."

    def responder(p: PeticionModelo) -> RespuestaModelo:
        e = entrada_desde_datos(datos_de_usuario(p.usuario), p.id_solicitud)
        e["justificacion"] = f"Coincide con el motor. {frase}"
        return respuesta_falsa(e)

    cliente = ClienteFalso(responder)
    assert cli.main(_args(datos, salidas, "--fecha-corte", "2026-07-20"), cliente=cliente, entorno=ENTORNO) == 0
    assert len(cliente.llamadas) == 1  # marcar no reintenta
    reg = leer_analisis(salidas, date(2026, 7, 20), V)[0]
    assert [(m.campo, m.texto) for m in reg.revision_equidad] == [("justificacion", frase)]
    assert reg.analisis.justificacion == f"Coincide con el motor. {frase}"  # el texto del modelo no cambia
    assert [(c.tipo, c.campo) for c in reg.correcciones if c.tipo == "revision_equidad"] == [
        ("revision_equidad", "justificacion")
    ]
    evento_ia = next(e for e in _eventos(salidas) if e["tipo"] == "analisis_ia")
    assert evento_ia["revision_equidad"] == 1
    auditoria = (salidas / "auditoria" / "eventos.jsonl").read_text(encoding="utf-8")
    assert "CT-INASISTENCIA-TEXTO" not in auditoria and "CT-INASISTENCIA-TEXTO" not in capsys.readouterr().err


def test_documentado_sin_ids_pasa_a_inferido_d1(entorno: tuple[Path, Path]) -> None:
    """D-1 = A: igual que C6.2 con IDs inválidos; el análisis se guarda con la corrección registrada."""
    datos, salidas = entorno

    def responder(p: PeticionModelo) -> RespuestaModelo:
        e = entrada_desde_datos(datos_de_usuario(p.usuario), p.id_solicitud)
        e["hallazgos"].append({"texto": "Afirmación sin cita.", "tipo": "documentado", "ids_registro": []})
        e["hallazgos"].append({"texto": "Otra sin el campo.", "tipo": "documentado"})
        return respuesta_falsa(e)

    cliente = ClienteFalso(responder)
    assert cli.main(_args(datos, salidas, "--fecha-corte", "2026-07-20"), cliente=cliente, entorno=ENTORNO) == 0
    assert len(cliente.llamadas) == 1
    reg = leer_analisis(salidas, date(2026, 7, 20), V)[0]
    sin_cita = [h for h in reg.analisis.hallazgos if h.texto in {"Afirmación sin cita.", "Otra sin el campo."}]
    assert [(h.tipo, h.ids_registro) for h in sin_cita] == [("inferido", []), ("inferido", [])]
    assert [c.detalle for c in reg.correcciones if c.tipo == "hallazgo_a_inferido"] == ["sin IDs", "sin IDs"]


def test_analisis_de_otra_version_de_prompt_cuenta_como_ya_analizada(entorno: tuple[Path, Path]) -> None:
    """Desviación C5.1 (D-2): un análisis con v1.0.0 no se recalcula al pasar a v1.2.0, salvo --forzar."""
    from hlf_priorizacion.copiloto.barrido import ConfigBarrido, ejecutar_barrido

    datos, salidas = entorno
    corte = date(2026, 7, 20)
    cfg = ConfigBarrido([corte], False, date(2026, 10, 13), datos, salidas, V, 10)
    viejo, nuevo = cargar_prompt("copiloto-v1.0.0"), cargar_prompt()
    assert nuevo.version_prompt == "copiloto-v1.2.0" and viejo.huella != nuevo.huella
    primero = ClienteFalso(responder_eco)
    assert ejecutar_barrido(cfg, ConfigModelo(), viejo, primero, "e1").analizadas == 1
    assert len(primero.llamadas) == 1

    sin_forzar = ClienteFalso(responder_eco)
    r = ejecutar_barrido(cfg, ConfigModelo(), nuevo, sin_forzar, "e2")
    assert sin_forzar.llamadas == [] and r.omitidas.get("ya_analizada") == 1

    otro_modelo = ClienteFalso(responder_eco)  # la clave sigue incluyendo model_id
    ejecutar_barrido(cfg, ConfigModelo(model_id=MODELO_RESPALDO), nuevo, otro_modelo, "e3")
    assert len(otro_modelo.llamadas) == 1

    forzado = ClienteFalso(responder_eco)
    cfg_forzar = ConfigBarrido([corte], False, date(2026, 10, 13), datos, salidas, V, 10, forzar=True)
    ejecutar_barrido(cfg_forzar, ConfigModelo(), nuevo, forzado, "e4")
    assert len(forzado.llamadas) == 1
    versiones = sorted(
        r.version_prompt for r in leer_analisis(salidas, corte, V) if r.model_id == ConfigModelo().model_id
    )
    assert versiones == ["copiloto-v1.0.0", "copiloto-v1.2.0"]
    # Con --forzar otra vez, la clave completa ya existe: no se vuelve a llamar ni se duplica.
    otra_vez = ClienteFalso(responder_eco)
    ejecutar_barrido(cfg_forzar, ConfigModelo(), nuevo, otra_vez, "e5")
    assert otra_vez.llamadas == []


def test_prompt_v1_1_0_exige_ids_y_nota_y_v1_0_0_sigue_disponible() -> None:
    nuevo, viejo = cargar_prompt("copiloto-v1.1.0"), cargar_prompt("copiloto-v1.0.0")
    assert "Nunca entregues un hallazgo `documentado` con `ids_registro` vacío" in nuevo.sistema
    assert "campo obligatorio" in nuevo.sistema and "nota_preconsulta" in nuevo.plantilla_usuario
    assert "Nunca entregues" not in viejo.sistema


def test_prompt_v1_2_0_por_defecto_y_versiones_anteriores_intactas() -> None:
    """E-1 = C: v1.2.0 es la versión por defecto; v1.0.0 y v1.1.0 no cambian (sus huellas están guardadas)."""
    actual = cargar_prompt()
    assert actual.version_prompt == "copiloto-v1.2.0"
    assert "Nunca menciones la comuna" in actual.sistema and "nivel socioeconómico" in actual.sistema
    assert "riesgo de que el paciente no asista" in actual.sistema
    assert "Nunca entregues un hallazgo `documentado`" in actual.sistema  # conserva lo de v1.1.0
    # Huellas que llevan los 95 análisis guardados en salidas/analisis.
    assert cargar_prompt("copiloto-v1.0.0").huella == (
        "sha256:3fe60933f1049701c7ad48bf891f7d1b4c1b42910fa658614127bbc95c26f47d"
    )
    assert cargar_prompt("copiloto-v1.1.0").huella == (
        "sha256:3d1efa92f77334a3972e8d83a1e6735bb5f6812b0588bde62e9192d4b433fc7f"
    )


def test_reintentos_ante_limitacion() -> None:
    estado = {"n": 0}

    def responder(p: PeticionModelo) -> RespuestaModelo | Exception:
        estado["n"] += 1
        return ErrorReintentable("ThrottlingException") if estado["n"] <= 2 else respuesta_falsa({})

    esperas: list[float] = []
    pet = PeticionModelo("IC-1", "s", "u", {})
    r = con_reintentos(ClienteFalso(responder), pet, ConfigModelo(), dormir=esperas.append, aleatorio=lambda: 0.5)
    assert r.entrada_herramienta == {} and esperas == [1.0, 2.0]

    siempre = ClienteFalso(lambda _p: ErrorReintentable("ThrottlingException"))
    with pytest.raises(ErrorReintentable):
        con_reintentos(siempre, pet, ConfigModelo(), dormir=lambda _s: None)
    assert len(siempre.llamadas) == 4  # la original + 3 reintentos


def test_esquema_de_la_herramienta_sin_metadatos() -> None:
    e = esquema_herramienta()
    texto = json.dumps(e)
    assert "metadatos" not in e["properties"] and "$ref" not in texto and "$defs" not in texto
    assert e["additionalProperties"] is False and "id_solicitud" in e["required"]


# --------------------------------------------------------------------------- dataset real: IC-HLF-00002


RAIZ = Path(__file__).resolve().parents[2]
DATOS_REALES = RAIZ / "data" / "dataset_hlf_ambulatorio"


@pytest.fixture(scope="module")
def lote_real(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not (DATOS_REALES / "perfiles.json").is_file():
        pytest.skip(f"Dataset real no disponible en {DATOS_REALES} (está en .gitignore)")
    salidas = tmp_path_factory.mktemp("salidas_reales")
    correr_lote(DATOS_REALES, salidas, [date(2026, 7, 19), date(2026, 7, 20), date(2026, 7, 21), date(2026, 8, 10)])
    return salidas


def _respuesta_00002(p: PeticionModelo) -> RespuestaModelo:
    datos = datos_de_usuario(p.usuario)
    e = entrada_desde_datos(datos, p.id_solicitud)
    meds = [m["id_medicion"] for m in datos["mediciones"] if m["tipo_medicion"] == "presion_sistolica"]
    e["hallazgos"] = [
        {"texto": "Urgencia ESI 2 y hospitalización durante la espera.", "tipo": "documentado",
         "ids_registro": ["EV-000004", "EV-000005"]},
        {"texto": "Presión sistólica en alza.", "tipo": "documentado", "ids_registro": meds[-2:]},
        {"texto": "Cita inventada por el modelo.", "tipo": "documentado", "ids_registro": ["EV-999999"]},
    ]
    e["riesgo_poblacional"] = {"n": 1, "k": 1, "p": 1.0, "ic95_inf": 0.5, "ic95_sup": 1.0,
                               "advertencia_muestra_pequena": True, "advertencia_sesgo_acceso": True}
    return respuesta_falsa(e)


def test_00002_al_2026_08_10_con_cliente_falso(lote_real: Path) -> None:
    from hlf_priorizacion.copiloto.barrido import ConfigBarrido, ejecutar_barrido
    from hlf_priorizacion.copiloto.persistencia import leer_cohortes
    from hlf_priorizacion.copiloto.validacion import riesgo_de_paquete  # noqa: F401  (documenta el origen)

    corte = date(2026, 8, 10)
    cfg = ConfigBarrido([corte], False, date(2026, 10, 13), DATOS_REALES, lote_real, V, 5,
                        filtro_ids=frozenset({"IC-HLF-00002"}))
    cliente = ClienteFalso(_respuesta_00002)
    r = ejecutar_barrido(cfg, ConfigModelo(concurrencia=1), cargar_prompt(), cliente, "prueba-00002")
    assert r.analizadas == 1 and r.total_fallidas == 0
    reg = leer_analisis(lote_real, corte, V)[0]
    a = reg.analisis
    documentados = [h for h in a.hallazgos if h.tipo == "documentado"]
    assert {"EV-000004", "EV-000005"} <= {i for h in documentados for i in h.ids_registro}
    assert all(i.startswith("MED-") for i in documentados[1].ids_registro) and documentados[1].ids_registro
    assert any(c.tipo == "hallazgo_a_inferido" for c in reg.correcciones)
    assert all("EV-999999" not in h.ids_registro for h in a.hallazgos)
    assert a.prioridad_sugerida == "critica"
    cohorte = leer_cohortes(lote_real, corte, V)["IC-HLF-00002"]
    assert a.riesgo_poblacional is not None
    assert (a.riesgo_poblacional.n, a.riesgo_poblacional.k, a.riesgo_poblacional.p) == (cohorte.n, cohorte.k, cohorte.p)
    assert any(c.tipo == "riesgo_poblacional_reemplazado" for c in reg.correcciones)


def test_rango_real_00002_del_19_al_21_de_julio(lote_real: Path) -> None:
    from hlf_priorizacion.copiloto.barrido import ConfigBarrido, ejecutar_barrido
    from hlf_priorizacion.copiloto.seleccion import firma_evaluacion
    from hlf_priorizacion.persistencia.salidas import leer_propuestas

    cortes = [date(2026, 7, 19), date(2026, 7, 20), date(2026, 7, 21)]
    cfg = ConfigBarrido(cortes, True, date(2026, 10, 13), DATOS_REALES, lote_real, V, 10,
                        filtro_ids=frozenset({"IC-HLF-00002"}))
    cliente = ClienteFalso(responder_eco)
    r = ejecutar_barrido(cfg, ConfigModelo(concurrencia=1), cargar_prompt(), cliente, "prueba-rango")
    ev = {c: next(e for e in leer_propuestas(lote_real, c, V) if e.id_solicitud == "IC-HLF-00002") for c in cortes}
    assert ev[cortes[0]].tipo_resultado != "priorizacion"
    assert r.por_corte["2026-07-19"].get("analizadas") == 0
    assert r.por_corte["2026-07-20"]["analizadas"] == 1
    anterior = datos_de_usuario(cliente.llamadas[0].usuario)["evaluacion_anterior"]
    assert anterior["fecha_corte"] == "2026-07-19"
    if firma_evaluacion(ev[cortes[2]]) == firma_evaluacion(ev[cortes[1]]):
        assert r.por_corte["2026-07-21"].get("omitidas_sin_cambio_en_rango") == 1
        assert len(cliente.llamadas) == 1
