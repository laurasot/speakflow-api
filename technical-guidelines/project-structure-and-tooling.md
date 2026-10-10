# Directrices de estructura de proyecto y tooling

Decisiones de layout, dependencias y build que, tomadas al inicio de un proyecto Python
empaquetado con `uv`/`poetry`/`pip` y Docker, evitan una migración dolorosa más adelante.

## 1. `pyproject.toml` y los tests van en la raíz del repositorio, no dentro del código fuente

**El error común:** poner `pyproject.toml`, el lockfile y `tests/` dentro de un
subdirectorio de código (por ejemplo `app/` o `src_antiguo/`), tratando ese subdirectorio
como si fuera el proyecto completo. Funciona mientras nadie necesite nada fuera de ese
subdirectorio — hasta que aparece infraestructura que sí lo necesita: un `docker-compose` de
punta a punta que construye desde la raíz del repo, un linter o verificador de tipos que
debería cubrir también los tests, una herramienta de CI que asume un único manifiesto en la
raíz, o un segundo servicio hermano que debería compartir el mismo tooling.

**La convención estándar** (la que sigue cualquier proyecto Python moderno con `hatch`,
`poetry`, `uv`, y la que documenta la guía oficial de empaquetado de Python,
*Python Packaging User Guide*): un `pyproject.toml` por raíz de proyecto. Hay dos layouts
aceptados:

- **Flat layout:** el código fuente vive directo en subdirectorios de la raíz, sin un
  directorio `src/` intermedio.
- **Src layout:** el código fuente vive bajo `src/<nombre_del_paquete>/`, instalado en modo
  editable. Es más robusto frente a errores de resolución de imports (no depende de qué
  directorio está en `sys.path`), al costo de una capa extra de anidamiento.

Cualquiera de los dos es válido. Lo que no es válido es que el `pyproject.toml` y los tests
vivan *dentro* del código fuente, porque eso ata la raíz lógica del proyecto (donde vive el
tooling) a la raíz de un paquete específico, sin margen para agregar nada que necesite ver
el proyecto completo.

**Cómo migrar sin romper los imports (flat layout):** si el código usa imports absolutos sin
prefijo de paquete, basta con decirle explícitamente a cada herramienta dónde está el
código, en vez de dejar que lo infiera de "desde dónde se invoca el comando":
- pytest: `pythonpath = [...]` en `[tool.pytest.ini_options]`, apuntando al directorio de
  código.
- mypy: `mypy_path = "..."` en `[tool.mypy]`.
- ruff: `src = [...]` en `[tool.ruff]`, para que el ordenador de imports (isort) reconozca
  los paquetes propios como first-party en vez de tratarlos como dependencias externas.

## 2. Un solo lockfile de dependencias, nunca dos sincronizados a mano

**El error común:** cuando el código de producción vive en un subdirectorio distinto de
donde vive el tooling de desarrollo, la tentación es duplicar el manifiesto de dependencias
(uno "completo" para desarrollo, uno "solo producción" para el Dockerfile), para no tener
que ajustar el contexto de build.

**Por qué es un error:** dos lockfiles de dependencias de producción son dos fuentes de
verdad que alguien tiene que mantener sincronizadas a mano, para siempre. El día que se
actualiza una dependencia en uno y se olvida el otro, CI prueba una versión y el Dockerfile
instala otra — exactamente el tipo de desajuste silencioso que un pipeline de CI/CD existe
para prevenir, reintroducido por la propia estructura del repositorio.

**La alternativa correcta:** un único manifiesto con grupos de dependencias
(`[dependency-groups]` en el estándar moderno de PEP 735, o el equivalente de la herramienta
elegida: `[tool.poetry.group]` en Poetry, `devDependencies` en npm/yarn), y el Dockerfile
instala solo el subconjunto de producción explícitamente (`uv sync --frozen --no-dev`,
`npm ci --omit=dev`, o el equivalente). El costo de esto es que el contexto de build de
Docker puede pasar a ser la raíz del repo completo en vez de un subdirectorio — se resuelve
con un `.dockerignore` bien armado (ver sección 4), no duplicando el manifiesto de
dependencias.

## 3. Elegir la versión del runtime por soporte y adopción, no por ser la más reciente

**El error común:** fijar la versión de un lenguaje o runtime (Python, Node.js, Java) a la
última recién publicada, sin revisar cuánto tiempo de soporte le queda ni qué tan probada
está en producción por el resto del ecosistema.

**Qué revisar antes de fijar una versión, para cualquier lenguaje con un calendario de
soporte publicado:**
- **Cuánto tiempo de soporte activo le queda.** Casi todo lenguaje con ciclo de versiones
  publica, para cada versión, cuándo termina el soporte de bugfixes (activo) y cuándo
  termina el soporte de seguridad (fin de vida) — por ejemplo la página oficial de estado de
  versiones de Python, o la página de LTS de Node.js. Una versión que está saliendo de
  soporte activo justo cuando el proyecto la adopta es una mala elección — a partir de ahí,
  solo recibe parches de seguridad, no correcciones de bugs del intérprete mismo.
- **Qué tan adoptada está en producción**, no solo cuántos meses lleva publicada. Las
  encuestas anuales de desarrolladores (encuestas oficiales de cada lenguaje, el Stack
  Overflow Developer Survey) suelen mostrar que la versión más usada en producción no es la
  más reciente, sino la que lleva uno o dos ciclos de release detrás — el ecosistema de
  librerías, las guías de troubleshooting y la compatibilidad binaria maduran con el tiempo,
  no al momento del lanzamiento.
- **Si el código usa sintaxis específica de una versión reciente**, verificar el mínimo real
  necesario antes de asumir que hace falta la versión más nueva — con frecuencia la sintaxis
  en uso ya es compatible con una versión anterior y más madura.

**La recomendación general, salvo que el proyecto necesite una feature específica de la
última versión:** adoptar la versión con mejor balance entre soporte restante y adopción
real — típicamente la penúltima versión mayor estable, no la recién salida.

## 4. El contexto de build de Docker debe ser mínimo y explícito

**El problema:** cuando el contexto de build incluye más de lo estrictamente necesario, un
`COPY . .` sin un `.dockerignore` cuidado copia dentro de la imagen todo lo que hay
disponible en ese contexto — tests, documentación, artefactos de pruebas versionados, el
historial de git — infla el tamaño de la imagen y el tiempo de build, y puede filtrar
archivos sensibles (`.env` locales, claves) si no están excluidos explícitamente.

**La práctica:**
- Un `.dockerignore` versionado igual que el Dockerfile — nunca excluido del propio control
  de versiones del proyecto (si el `.gitignore` lo excluye por error, nadie revisa sus
  cambios en pull requests, y el archivo diverge en silencio de lo que el repo realmente
  contiene).
- Excluir explícitamente: entornos virtuales, caches de herramientas, el directorio de
  control de versiones, documentación, artefactos de pruebas, y cualquier archivo de
  configuración local (`.env`, `.env.*`).
- Usar builds multi-stage (un stage `builder` que resuelve dependencias, un stage `runtime`
  final que solo copia el entorno ya resuelto y el código de producción) para que la imagen
  final no cargue herramientas de compilación ni el gestor de paquetes mismo.
- Verificar el contenido real de la imagen construida, no asumirlo: inspeccionar el
  filesystem de la imagen después de cualquier cambio al Dockerfile o al `.dockerignore`
  (`docker run --rm <imagen> find /app -maxdepth 1`, o equivalente), para confirmar que no
  quedó nada de más.

## 5. Checklist

- [ ] El manifiesto de dependencias, el lockfile y los tests viven en la raíz del proyecto,
      no dentro de un subdirectorio de código fuente.
- [ ] Un único lockfile de dependencias; el Dockerfile instala solo el subconjunto de
      producción explícitamente, nunca desde un manifiesto duplicado.
- [ ] La versión del runtime se eligió revisando soporte restante y adopción real en
      producción, no solo "es la más nueva disponible".
- [ ] Hay un `.dockerignore` versionado en la raíz del contexto de build, revisado en pull
      requests igual que cualquier otro archivo de configuración.
- [ ] El Dockerfile usa build multi-stage; la imagen final no incluye herramientas de
      compilación, el gestor de paquetes, ni archivos de desarrollo.
- [ ] Se verificó el contenido real de la imagen construida después del último cambio al
      Dockerfile o al `.dockerignore`.
