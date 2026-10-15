"""main.py sigue funcionando con el cliente simulado (sin red, auditoría temporal)."""
import runpy

from conftest import RAIZ, leer_jsonl
from servidor.inferencia import ClienteSimulado, instalar_cliente


def test_main_con_cliente_simulado(monkeypatch, ruta_auditoria, capsys):
    monkeypatch.chdir(RAIZ)
    instalar_cliente(ClienteSimulado())
    runpy.run_path(str(RAIZ / "main.py"), run_name="__main__")
    salida = capsys.readouterr().out
    assert "Válidos: 500" in salida and "[SIMULADO]" in salida
    assert any(x["tipo"] == "analisis_ia" for x in leer_jsonl(ruta_auditoria))
