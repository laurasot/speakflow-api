# Especificación delta: ci-quality-gate (control de calidad en CI)

> Palabras clave (RFC 2119): DEBE = obligatorio (MUST/SHALL); NO DEBE = prohibido (MUST NOT); DEBERÍA = recomendado (SHOULD); PUEDE = opcional (MAY).

## Propósito

El lint, los tipos y las pruebas DEBEN bloquear el merge mediante GitHub Actions, con un piso de cobertura medido. La limpieza DEBE ser neutra en comportamiento y DEBE entrar (PR A) antes que el workflow (PR C).

## Requisitos

### REQ-01 Ruff limpio
`ruff check app tests` DEBE reportar 0 hallazgos (51 al inicio: 33 corregidos automáticamente, ~18 a mano). El commit de `--fix` DEBE ir separado de las correcciones manuales; sin cambios de comportamiento.

- Dado el árbol limpio, Cuando corre `ruff check app tests`, Entonces el código de salida es 0.
- Dada la suite completa antes y después de cada commit de limpieza, Entonces los resultados son idénticos (87 pruebas pasando al inicio).
- Dada una corrección manual que cambiaría el comportamiento, Entonces se deja la regla suprimida de forma puntual con `# noqa: <regla>` (única excepción a la norma de "sin comentarios" del `CLAUDE.md`) y se anota el motivo en el mensaje del commit.

### REQ-02 Mypy limpio
`mypy app` DEBE reportar 0 errores. El fallo de los stubs (archivos de tipos) de numpy DEBE resolverse con `[[tool.mypy.overrides]] module = "numpy.*"` y `follow_imports = "skip"`, y si el override no funciona, con el plan alternativo de usar `python_version = "3.12"` en mypy.

- Dado el override, Cuando corre `mypy app`, Entonces hay 0 errores.
- Dado que el override falla, Entonces se aplica la alternativa y el motivo se anota en `pyproject.toml`.
- Dado un Python de ejecución 3.11, Entonces la configuración de ejecución no cambia por la alternativa.

### REQ-03 Workflow de CI
`.github/workflows/ci.yml` DEBE ejecutarse en pull requests y en pushes a `develop`, y correr cuatro trabajos bloqueantes: `ruff check app tests`, `mypy app`, `pytest -m "not e2e"` en orden aleatorio y `pytest -m e2e` (flujo en el mismo proceso, sin Docker). Ninguno PUEDE usar `continue-on-error`. El CI NO DEBE depender de un `.env` ni de secretos reales.

- Dado un PR con una violación de ruff, Entonces el workflow falla.
- Dado un PR con un xfail que pasa inesperadamente, Entonces pytest hace fallar el workflow.
- Dado que no hay secretos configurados, Entonces el workflow igual pasa.

### REQ-04 Cobertura base y piso
La cobertura base DEBE medirse una sola vez, registrarse en `../PLAN-MEJORAS.md`, y `--cov-fail-under` DEBE fijarse en la base menos un margen (el margen se indica en la entrada del PLAN). El objetivo de 80% queda fuera de alcance.

- Dada una cobertura por debajo del piso, Entonces pytest falla.
- Dada una cobertura igual o mayor al piso, Entonces pytest pasa.
- Dada la base registrada, Entonces es igual al valor medido con el mismo comando que ejecuta el CI.

### REQ-05 Orden de entrega encadenada
El PR A (herramientas, limpieza, helpers) DEBE entrar antes que el PR B (xfails), y luego el PR C (stub, goldens, e2e, CI). Cada uno DEBE mantener la suite en verde por sí solo; si el PR A supera las 400 líneas después de la unidad 2, DEBE dividirse en A1 y A2.

- Dado solo el PR A, Entonces ruff, mypy y pytest pasan en local.
- Dado el PR C revertido, Entonces el PR A y el B siguen en verde.
