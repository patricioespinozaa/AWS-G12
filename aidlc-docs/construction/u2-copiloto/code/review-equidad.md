# C6.5 determinista sin negaciones, tercera pasada: normalización NFKD con separadores como espacio

This pass reviews the fix for pass two. `normalizar()` now applies NFKD, strips accents, casefolds and collapses every non-alphanumeric run (`_` included) into one space. The rule 1 stems became `\w*comuna\w*`, `\w*prevision\w*|fonasa|isapres?|fondo nacional de salud` and `socio ?economic\w*|n ?s ?e|gse`. All 11 pass-two leaks are now rejected and pinned by 12 new example rows. The normalization approach closed the separator, underscore, affix and full-width classes in one place, as recommended. The structural requirements still hold.

Watch for: rule 1 still leaks. 5 of 22 new adversarial phrasings pass (**confirmed**, run against `atributo_no_disponible()`). Two are plurals of listed acronyms ("FONASAs", "NSEs"). One is a derived noun ("socioeconomía"). Two are dotted acronyms ("F.O.N.A.S.A.", "I.S.A.P.R.E."), which the code already handles for "N.S.E." but not for the other two. The new `n ?s ?e` alternative also rejects "Cita n° se reprogramó" (**confirmed**). That one fails closed and isn't blocking.

**Verdict**: NEEDS_CHANGES

## High-level view

The normalization step works. It removed a whole family of leaks without per-spelling alternations. Soft hyphen, zero-width space, U+2011, NBSP, line breaks, combining accents and full-width forms were all handled correctly on the first try. What's left is at the token level. `fonasa` and `nse` are anchored on both sides with no plural allowance (only `isapres?` has one). The NSE stem is `economic`, which misses the noun "economía". Letter-by-letter acronyms only work for N-S-E, because that's the only acronym with a spaced pattern. Three small changes would close these: optional `s` on every acronym, the stem `socio ?econom\w*`, and joining single-letter runs before matching.

The fail-closed side has one new cost. Since `.`, `°` and `/` now become spaces, `n ?s ?e` matches "n se", and "n° se" is ordinary Spanish clinical shorthand. "En previsión de…" (meaning "anticipating") has been rejected since pass one. It's still the most likely false rejection in real model output. Both only cost a retry and a `fallidos` line, so neither blocks.

Everything else the brief asked for holds. All four gates pass with 223 passed and 1 deselected, which matches the latest row in `resumen.md`. The prompt hashes match the saved analyses, v1.2.0 is the default, and the saved `.jsonl` hashes were identical before and after this review.

<details>
<summary>Issues (5)</summary>

1. **Acronym plurals leak (blocking, confirmed)**: "Afiliados FONASAs del sector." and "Pacientes con NSEs distintos." pass. Use `fonasas?`, `nses?` and `gses?`, matching the existing `isapres?`.
2. **"socioeconomía" leaks (blocking, confirmed)**: "La socioeconomía familiar es precaria." passes because the stem is `socio ?economic\w*`. Use `socio ?econom\w*`. Check that it still doesn't touch "economía" alone, which isn't one of the attributes.
3. **Dotted acronyms other than N.S.E. leak (blocking, confirmed)**: "Afiliado a F.O.N.A.S.A." and "Afiliado a I.S.A.P.R.E." pass. They normalize to `f o n a s a` and `i s a p r e`. In `normalizar()`, join runs of single-letter tokens (`re.sub(r"\b\w(?: \w\b)+", lambda m: m.group().replace(" ", ""), s)`), or test a second, joined form. Then `n ?s ?e` can become `nses?`, which also resolves issue 4.
4. **`n ?s ?e` rejects "n° se" (non-blocking, confirmed)**: "Cita n° se reprogramó." is rejected as `nivel_socioeconomico`. It fails closed, but "n°" is common in clinical text. Dropping the optional spaces after the single-letter join from issue 3 fixes it. Add the phrase as a negative example.
5. **"En previsión de" rejects (non-blocking, likely)**: this sense of "previsión" ("anticipating") is common in clinical prose. The v1.2.0 prompt doesn't warn about it. It fails closed and costs a retry. Either accept that, or add a line to the next prompt version asking the model to avoid the word in any sense. Don't change v1.2.0 in place: its hash would change.

</details>

<details>
<summary>Details</summary>

### Adversarial phrasings for rule 1 (pass three, all new)

Each phrase was set as `justificacion` through `analisis_con_justificacion()` and passed to `atributo_no_disponible()`. No Bedrock calls were made. None of these appear in pass two or in the coder's test rows.

```
RECHAZA prevision             Beneficiaria de Fonasa-B desde 2020.
PASA    —                     Afiliados FONASAs del sector.
RECHAZA comuna                Zona COMUNAL-RURAL.
RECHAZA prevision             PREVISIÓN DE SALUD no informada.
RECHAZA nivel_socioeconomico  Nivel socio\u00ADeconómico medio (soft hyphen)
RECHAZA nivel_socioeconomico  Nivel socio\u200Beconómico medio (zero-width space)
RECHAZA nivel_socioeconomico  Nivel socio\u2011económico medio (non-breaking hyphen)
RECHAZA nivel_socioeconomico  Nivel socio-<LF>económico medio.
RECHAZA nivel_socioeconomico  Nivel socio\u00A0económico medio (NBSP)
RECHAZA prevision             Tiene iSaPrE Colmena.
PASA    —                     Pacientes con NSEs distintos.
PASA    —                     La socioeconomía familiar es precaria.
PASA    —                     Afiliado a F.O.N.A.S.A.
PASA    —                     Afiliado a I.S.A.P.R.E.
RECHAZA nivel_socioeconomico  Grupo ＮＳＥ bajo. (full-width)
RECHAZA comuna                Ｃｏｍｕｎａ de residencia. (full-width)
RECHAZA prevision             Previsio\u0301n desconocida. (combining acute)
RECHAZA comuna                No por su ComUnA ni por su PrEvIsIoN.
RECHAZA nivel_socioeconomico  Sin considerar lo SOCIOECONÓMICO.
RECHAZA nivel_socioeconomico  Estratos socio-económicos.
RECHAZA prevision             Prevision-Salud vacía.
RECHAZA prevision             Interprevisional y comunales.
```

17 rejected, 5 leaked. Negation ("No por su…", "Sin considerar…") has no effect on rejection. Case, accents (precomposed and combining), Unicode separators and full-width text are handled in every combination tried. All 5 leaks are token-shape problems, covered in issues 1–3.

Near-misses checked for over-matching: "Se comunicó el resultado", "Control comunitario", "Evolución previsible" and "insensibilidad" produce no rejection and no mark. "Cita n° se reprogramó." and "En previsión de una descompensación, control precoz." are rejected (issues 4 and 5).

### Why the remaining leaks happen

The combined pattern is wrapped in `\b(?:…)\b`. `fonasa` and `nse` are bare alternatives, so the trailing `s` in "FONASAs" and "NSEs" breaks the closing boundary. The NSE stem was chosen as `economic\w*` to cover "económico/a/os/amente", but "socioeconomía" has `economi` followed by `a`. The dotted forms work for N.S.E. only because `n ?s ?e` explicitly allows spaces between letters. FONASA and ISAPRE have no such allowance, and adding `f ?o ?n ?a ?s ?a` alternations would start the per-spelling treadmill again. Collapsing single-letter runs in `normalizar()` handles every acronym at once. Rule 2 normalizes per sentence after `oraciones()` splits the raw text, so a join step there wouldn't affect sentence splitting.

### Structural requirements, re-checked

There's no negation logic in `src/`. `_usa_atributo_para_bajar`, `_RE_BAJAR` and any window or clause helpers are absent. `NEGACIONES` exists only as test filler in `tests/estrategias/copiloto.py`, where P16a/P16b use it to prove negations don't matter. All word lists live in the single module-level `EQUIDAD_TERMINOS: Final`. Rule 1 runs before rule 2 and rejects with `equidad_atributo_no_disponible: <campo> menciona <atributo>, que no está en los datos`. That string carries the field path and the attribute key, never sentence text. It reaches `fallidos.jsonl` and the retry message, which `test_copiloto.py` asserts.

Rule 2 marks go from `ResultadoValidacion.revision_equidad` to `RegistroAnalisis.revision_equidad`, never into `AnalisisIA`. `leer_analisis()` returns them and defaults to `[]` for older records. The `analisis_ia` audit event carries `revision_equidad=len(...)`. Corrections are reduced to `{tipo, campo}` by `_corr()`, and the `revision_equidad` correction's `detalle` is the fixed `DETALLE_REVISION_EQUIDAD` constant. The "análisis fallido" warning logs only the motivo code.

### Prompts, saved data and gates

`cargar_prompt()` hashes for v1.0.0 and v1.1.0 match the `huella_prompt` of all 74 and 21 saved analyses. No saved analysis carries the v1.2.0 hash, and `VERSION_PROMPT_POR_DEFECTO == "copiloto-v1.2.0"`. `revision-equidad-guardados.md` exists, and its five SHA-256 prefixes match the files on disk. I hashed every file under `salidas/analisis` before the gates and again after the adversarial script, and they were identical. The script only read through `json.loads` and was deleted afterwards.

From the repo root, after `chcp 65001` and `. .\scripts\entorno-demo.ps1`, `ruff check` passed and `mypy src` reported no issues in 39 files. `pytest` with the default markers gave **223 passed, 1 deselected** in 50.6 s, and `pip-audit` exited 0 with no known vulnerabilities. The brief expected about 194, which was the count three changes ago. `resumen.md` records 205 → 211 → 223 across the E-1 = C replacement and the two review passes, so there's no divergence.

Two items from earlier passes are still waiting on a user decision, with no change in this pass. Rule 2 splits on `;`, so "No asistió a dos citas; no corresponde postergar." isn't marked. IC-HLF-00349 also reads back with `revision_equidad = []`.

</details>

<details>
<summary>File map</summary>

- `src/hlf_priorizacion/copiloto/validacion.py`: `normalizar()` switched to NFKD plus a `[\W_]+` → space step. `EQUIDAD_TERMINOS["atributo_no_disponible"]` now uses `\w*` stems, "fondo nacional de salud", `n ?s ?e` and `gse`. `no_asistio` simplified to `no asistio`.
- `tests/estrategias/copiloto.py`: `ATRIBUTOS_NO_DISPONIBLES` extended with the pass-two leaks for P16a
- `tests/ejemplos/test_copiloto.py`: 12 new rows in `test_c65_regla_determinista_sin_negaciones`
- `aidlc-docs/construction/u2-copiloto/code/resumen.md`, `revision-equidad-guardados.md`: re-run recorded (223 passed; 0 rejected and 1 marked among the 95 saved)

Everything is untracked relative to `main`, so no git diff is available. The source files were reviewed directly.

</details>
