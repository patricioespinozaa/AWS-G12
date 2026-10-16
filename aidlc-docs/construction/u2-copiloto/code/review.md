# Copiloto U2: batch Bedrock analysis of prioritized requests

U2 adds `hlf-copiloto`, a batch sweep that takes U1's `priorizacion` proposals for one cut-off or a date range, rebuilds each patient context from the dataset (fingerprint-checked against U1), sends a minimized package to Bedrock Converse with a single forced tool, validates and corrects the structured answer, and appends it to `analisis.jsonl` with full audit. The design keeps model calls and I/O behind injected interfaces so selection, packaging and validation are pure and property-tested. The real range run 2026-07-19..07-21 left 95 of 95 analyses saved with no duplicates; the final audited run made 0 invocations.

Watch for: `--max-llamadas` caps requests, not invocations, so real spend can exceed it (run 1: 95 estimated, 148 made) (confirmed); `max_tokens` 8192 was raised without a user decision (confirmed, documented as deviation 6); the C6.5 negation window can let a forbidden equity reason through when an unrelated "no" precedes the verb (likely).

**Verdict**: APPROVED

## High-level view

The pipeline is plan → cap → package → call → validate → persist. Planning is pure and partitions every request of a cut into exactly one of pending or omitted-with-reason; omissions (`exclusion`, `gestion`, `sin_alerta`, `sin_cambio_en_rango`, `ya_analizada`, `limite_llamadas`) each produce an `analisis_omitido` event. Workers only call the model and validate; all writes happen afterwards on the main thread in `(fecha_corte, id_solicitud)` order, which is what makes the sequential-vs-parallel oracle hold.

The package is built only from `ContextoPaciente` fields, rendered as JSON inside `<datos_clinicos>` with `<` escaped, and refused with `huella_distinta` if the rebuilt context's fingerprint differs from U1's. On the way back, `metadatos` and `riesgo_poblacional` are overwritten by the system, IDs not in the package are stripped and `documentado` findings downgraded, and red-flag discrepancy and forbidden equity reasons reject the answer, with one retry carrying the error.

Fail-closed behavior is split in two. A model outside the local allowlist stops at config with exit 2 before any call; a Bedrock-side denial or credential error sets a stop event, marks remaining requests `detenido_por_permisos` and exits 4 with the backup-model hint. Logs go through a field allowlist (IDs, model_id, request_id, tokens, latency, codes); full model I/O lives only in `salidas/copiloto_io/` by fingerprint.

The cost guard is the soft spot. The pre-flight estimate counts one call per pending request, but each request can make up to two validation attempts, each with up to three service retries.

<details>
<summary>Issues (5)</summary>

1. **Call cap counts requests, not invocations** (confirmed): `llamadas_estimadas` is the count of pending requests, while each request can make up to 2 validation attempts × 4 service attempts. Run 1 estimated 95 and made 148. Either estimate the worst case, or enforce `--max-llamadas` as a live invocation budget that stops new calls when it's reached. Non-blocking, user decision.
2. **`max_tokens` 8192 not ratified** (confirmed): this raises the output-token ceiling (and per-call cost) without a user decision. Audit shows 33 of 176 real calls ended with `stop_reason = max_tokens` before the change. Ask the user to ratify deviation 6.
3. **`huella_distinta` used for unrelated failures** (confirmed): `SolicitudNoEncontrada` and any `ValueError` while building the package are recorded as `huella_distinta`, which hides a missing request behind a fingerprint mismatch. Use a separate reason (e.g. `contexto_no_disponible`).
4. **Exit code for a non-allowlisted model is 2, not 4** (confirmed): the local allowlist rejects before any call, which is stricter, but scripts expecting 4 for "model not permitted" will see 2. Document this in the README/CLI help or map `ErrorConfiguracion` on `HLF_BEDROCK_MODEL_ID` to exit 4.
5. **Negation window can mask a forbidden reason** (likely): any `no`/`sin`/`ni` within 60 characters before the lowering verb suppresses C6.5, even when it negates something else. Scope the negation to the verb phrase (e.g. require it immediately before the verb or its auxiliary) and add a property/example case. Non-blocking for the synthetic-data MVP, but it fails open on the equity rule.

</details>

<details>
<summary>Details</summary>

### Call cap versus real invocations

`verificar_tope` compares `plan.llamadas_estimadas` (pending requests) against `--max-llamadas`. Inside `analizar`, each request can go through `MAX_INTENTOS_VALIDACION = 2` attempts, and `con_reintentos` adds up to 3 retries on throttling or timeout for each one. The worst case is 8 invocations per estimated call. The audit trail shows the gap in practice. Run `KJK0TPYK` estimated 95 and logged 148 `llamada_modelo` events (1,035,363 / 539,429 tokens). Run `7BP9Q1WZ` estimated 21 under `--max-llamadas 25` and made 25, which stayed inside the user's ~60-call allowance only because 18 requests passed on the first attempt. C2.5 is satisfied as written, since it only describes a pre-flight estimate. But the flag's name and the user's stated budget suggest it is meant as a ceiling on spend. The circuit breaker doesn't cover this, because validation failures don't feed it (deviation 9). The fix is cheap either way: count invocations in `_ClienteContador` and stop new calls at the cap, recording the rest as `limite_llamadas`.

### Validation path (C6)

The order is metadata → cohort replacement → D-1 pre-schema downgrade → strict schema plus `id_solicitud` → citation correction → red flag → forbidden reasons, and it matches business-rules C6.1–C6.6. `validar_salida` is idempotent (P10) because corrected outputs no longer trigger any correction. In the saved data, all 95 analyses have `estado = pendiente_revision_medica`, and every `documentado` finding carries at least one ID. There are 11 corrections in total (6 `hallazgo_a_inferido`, 5 `riesgo_poblacional_reemplazado`) and 2 disagreements with the engine, matching `resumen.md`. A `documentado` finding with some invalid IDs is downgraded even when valid IDs remain. That follows the literal text of C6.2 and costs some precision. The forbidden-reason detector now ignores negated verbs within a 60-character window (deviation 7). This keeps it from rejecting the prompt's own safety phrasing, but it also misses a real forbidden reason whenever any unrelated `no`/`sin`/`ni` appears in the 60 characters before the verb in the same sentence, e.g. "no hay motivo clínico urgente y por su comuna conviene bajarla" (likely: traced through `_bajada_afirmada`, not exercised by a test). The check fails open for the equity safeguard.

### Security posture and logs

Credentials are never touched: boto3 uses the default chain, and the only credential-related code maps `NoCredentialsError` to `sin_credenciales`. `logs.py` drops any field outside `CAMPOS_PERMITIDOS`, and the per-call log line is built from an explicit tuple of ID, token and latency fields. `error_proceso` records only the code before the first `:` of the failure reason. The full rejection text (Pydantic paths and messages without input values, or the matched attribute word) goes only to `fallidos.jsonl` under the git-ignored `salidas/`. The package excludes comuna, previsión, NSE and fantasy name by construction (they're absent from `ContextoPaciente`), and P06 checks both field names and raw `PerfilCrudo` values against the rendered text. Bedrock Guardrails are absent by design (G-4) and stay a mandatory follow-up before any real clinical text.

### Fingerprint and failure labeling

`armar_paquete` refuses the package when the context's request or date differs from the evaluation, or when `huella_contexto` differs. That gives the required `huella_distinta` fail path, and an example test covers it. The caller in `ejecutar_barrido` catches `(ErrorHuella, SolicitudNoEncontrada, ValueError)` together and labels all of them `huella_distinta`. A request missing from the rebuilt repository is a different operational problem (dataset drift or a contract-invalid profile dropped by `cargar_repositorio`), and the audit can't tell the two apart.

### Fail-closed and exit codes

`ErrorPermisos` covers AccessDenied, unrecognized or expired credentials, invalid signatures, ResourceNotFound and `ValidationException` messages about model access. It sets a shared stop event: in-flight tasks finish, and remaining tasks are recorded as `detenido_por_permisos`. The CLI then exits 4 with a backup-model hint, and the example test confirms `permisos:AccessDeniedException` with exit 4. A model ID outside `MODELOS_PERMITIDOS` never reaches Bedrock; `ErrorConfiguracion` yields exit 2 (the example test asserts `SALIDA_ENTRADA`). This is fail-closed, but the exit code differs from the "exit 4 on non-allowlisted model" expectation in the review brief.

### Idempotence and saved outputs

The append-only `analisis.jsonl` per cut holds 95 rows: 85 for 07-19, 5 for 07-20 and 5 for 07-21; 74 from v1.0.0 and 21 from v1.1.0. There are 0 duplicate full keys and 0 duplicates on `(id_solicitud, fecha_corte, model_id)`, so D-2 cross-version idempotence held while v1.1.0 was introduced. `fallidos.jsonl` has 24 rows (21 + 3, all `validacion`), and every failed `(id_solicitud, fecha_corte)` has a later saved analysis. The audit has four copiloto runs with 176 `llamada_modelo`, 95 `analisis_ia` and 24 `error_proceso` events. The last run (`5BFVQKS8`) has 0 `llamada_modelo` and 95 `ya_analizada` omissions, alongside sin_alerta 984, exclusion 117, gestion 47 and sin_cambio_en_rango 162. All of this was read from disk. The optional CLI re-run was not needed.

### Acceptance criteria for IC-HLF-00002

For 07-20 in the range, the saved analysis is `critica` on attempt 1. Its `documentado` findings cite EV-000004 and the four systolic measurements (MED-43528798…, MED-668054b1…, MED-6f2b6169…, MED-372ba075…), and `riesgo_poblacional` is n=13, k=0, p=0.0, IC95 0–0.228. There are no rows for 07-19 or 07-21, which agrees with the coder's `sin_alerta` and `sin_cambio_en_rango` omissions. The 2026-08-10 check ran in `tmp_path` by design, so its only evidence is the recorded result in `resumen.md`: 1 passed in 39 s, 6,834 / 3,426 tokens, `critica`, cites EV-000005 and the four measurements, cohort n=13/k=0/p=0.0. The test asserts the cited IDs, critical-or-justified-discrepancy and cohort equality, so the criterion is met per that record.

### Test coverage

All 14 properties from `business-logic-model.md` are present in `tests/propiedades/test_prop_copiloto.py` (P01–P14 plus P03b). They include the 1-vs-4 thread oracle with `ClienteFalso` and a `RuleBasedStateMachine` for the circuit breaker, backed by a concurrency test at 1, 4 and 8 threads. Example tests live separately in `tests/ejemplos/test_copiloto.py`; every `cli.main` call there injects `ClienteFalso`. The only real-client test is marked `@pytest.mark.bedrock`, and `addopts` excludes it by default. Not tested: the invocation count against `--max-llamadas` when validation retries occur; a sentence with an unrelated negation that still uses a forbidden attribute to lower priority; a request missing from the rebuilt repository (it currently shows up as `huella_distinta`).

### Verification run by the reviewer

From the workspace root, after `. .\scripts\entorno-demo.ps1`:

```text
uv run ruff check     -> All checks passed!
uv run mypy src       -> Success: no issues found in 39 source files
uv run pytest         -> 166 passed, 1 deselected in 68.37s
uv run pip-audit      -> No known vulnerabilities found (local package skipped)
```

All 30 plan items in `u2-copiloto-code-generation-plan.md` are `[x]`; none are open. The U1 suites (`test_calidad`, `test_casos_referencia`, `test_contrato`, `test_ingesta`, `test_lote`, `test_modelos`, `test_motor`, `test_persistencia`, `test_repositorio` and U1 properties) pass inside the 166. Dependencies are pinned: `boto3==1.43.114`, `botocore==1.43.114`, dev `boto3-stubs[bedrock-runtime]==1.43.114`.

</details>

<details>
<summary>File map</summary>

- `src/hlf_priorizacion/copiloto/config.py`: env config, model allowlist, temperature rule, `max_tokens` 8192
- `copiloto/prompts/copiloto-v1.0.0/`, `copiloto-v1.1.0/`: system and user prompts (v1.1.0 default)
- `copiloto/prompt.py`: prompt loading and fingerprint
- `copiloto/fechas.py`: ISO parsing and C2.3 range rules
- `copiloto/seleccion.py`: pure plan, omission reasons, call estimate and cap
- `copiloto/modelos.py`: package, correction, saved record, failure entities
- `copiloto/paquete.py`: fingerprint-checked package and escaped render
- `copiloto/cliente.py`: Converse client, forced tool, error classification, retries, fake client
- `copiloto/validacion.py`: C6 validation and corrections
- `copiloto/barrido.py`: orchestration, circuit breaker, ordered persistence and audit
- `copiloto/persistencia.py`: append-only analyses and failures, I/O by fingerprint, U1 readers
- `copiloto/cli.py`: `hlf-copiloto`, exit codes 0–4
- `auditoria/registro.py`, `logs.py`: `analisis_omitido` event type, U2 log fields
- `pyproject.toml`, `uv.lock`: pinned boto3/botocore, stubs, script, `bedrock` marker
- `tests/estrategias/copiloto.py`, `tests/propiedades/test_prop_copiloto.py`, `tests/ejemplos/test_copiloto.py`, `tests/integracion/test_bedrock_real.py`

Full diff: working tree against the last commit (`git diff HEAD`; nothing committed for U2).

</details>
