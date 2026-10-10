# Directrices de revisión de seguridad

Cómo auditar un servicio HTTP (FastAPI o equivalente) buscando vulnerabilidades reales y
explotables, no una lista genérica de buenas prácticas — y cómo evitar que una auditoría de
seguridad se vuelva ella misma una fuente de falsa confianza.

## 1. El principio rector: nunca inventar, siempre distinguir qué se puede verificar

**La regla central, la que separa una auditoría útil de un checklist cosmético:** cada
hallazgo debe estar respaldado por código concreto — una línea, un archivo, un flujo
reproducible. Cuando algo depende de infraestructura, configuración externa, variables de
entorno, o el comportamiento de otro servicio que el código no muestra, se marca
explícitamente como **NO VERIFICABLE**, nunca se asume que "probablemente está bien
configurado".

**Por qué esto importa más que la lista de vulnerabilidades en sí:** una auditoría que
afirma "no hay rate limiting" cuando en realidad el rate limiting vive en un API Gateway
fuera del código revisado es un hallazgo falso que hace perder tiempo persiguiendo un
problema que no existe — y, peor, resta credibilidad a los hallazgos reales de la misma
auditoría. Distinguir con disciplina entre cuatro estados evita esto:

- **VULNERABLE** — demostrado con código y un escenario de explotación concreto.
- **CORRECTO** — verificado, el control existe y funciona como corresponde.
- **NO VERIFICABLE** — depende de algo fuera del código disponible (infraestructura, config
  de despliegue, otro servicio).
- **NO APLICA** — el control no es relevante para este servicio (por ejemplo, una política
  de sesiones de navegador en un servicio que solo expone una API server-to-server).

**No convertir cada mala práctica en una vulnerabilidad.** Un header de seguridad ausente
solo importa si el servicio tiene un vector donde ese header haría una diferencia real
(por ejemplo, CORS abierto importa si hay credenciales de sesión de por medio; en un API
server-to-server con solo tokens Bearer, puede ser irrelevante). Marcar como hallazgo algo
sin impacto real diluye la atención sobre lo que sí importa.

## 2. Reconstruir el sistema antes de buscar vulnerabilidades

**Antes de auditar código línea por línea**, reconstruir el mapa del sistema: qué hace el
servicio, qué endpoints expone, qué datos recibe y devuelve, qué actores existen
(usuario final, otro servicio, un integrador externo), qué operaciones son sensibles
(mueven dinero, cambian permisos, exponen datos personales), y la cadena completa:

```
Cliente → framework HTTP → autenticación → autorización → lógica de negocio → datos → servicios externos
```

**Sin este mapa, la auditoría se vuelve una búsqueda de patrones de texto** ("buscar
`eval`", "buscar `except Exception`") desconectada de qué partes del sistema realmente
importan. Con el mapa, cada hallazgo se puede ubicar en el flujo real y evaluar su impacto
real — un `SELECT *` sin filtrar en un endpoint interno de health-check no es lo mismo que
el mismo patrón en un endpoint que recibe un ID desde el cliente.

## 3. Autenticación vs. autorización: la distinción que más se confunde en la práctica

**Son dos preguntas distintas, y confundirlas es el origen de la mayoría de las
vulnerabilidades de control de acceso en APIs reales:**

- **Autenticación:** ¿quién es este cliente? (tiene credenciales válidas)
- **Autorización:** ¿puede este cliente hacer *esta* operación sobre *este* recurso
  específico?

**Verificar que el código las separe explícitamente.** Un endpoint puede exigir
autenticación (un token válido) y aun así no verificar autorización (si el token pertenece
al usuario A, pero el endpoint deja que A opere sobre un recurso de B porque confía en un
`user_id`/`account_id` que llega en el propio request sin contrastarlo contra la identidad
del token). Esto es la causa de **IDOR** (Insecure Direct Object Reference) y **BOLA**
(Broken Object Level Authorization) — la categoría #1 en el OWASP API Security Top 10 desde
su primera edición, y la más común en auditorías reales de APIs.

**El patrón de verificación concreto:** para cada endpoint que opera sobre un recurso
identificado por ID, confirmar dónde exactamente el código verifica que el actor autenticado
tiene permiso sobre *ese* recurso específico — no solo que está autenticado en general. Si
esa verificación no existe, o depende de un dato que el propio cliente controla (un
`user_id` en el body, no derivado del token verificado), es una vulnerabilidad de
autorización, con un escenario de ataque concreto y reproducible.

## 4. OWASP API Security Top 10 como checklist de cobertura

**Usar la lista oficial de OWASP** (actualizada periódicamente, consultar la versión vigente
en [owasp.org/API-Security](https://owasp.org/www-project-api-security/)) como garantía de
cobertura, no como única fuente de hallazgos. Para cada categoría, registrar
PASS/PARTIAL/FAIL/NO VERIFICABLE con su evidencia — las categorías cubren, entre otras:
autorización a nivel de objeto y de propiedad rota, autenticación rota, consumo irrestricto
de recursos, autorización a nivel de función rota, exposición de flujos de negocio
sensibles, SSRF, configuración de seguridad incorrecta, inventario de APIs incompleto, y
consumo inseguro de APIs de terceros.

**Las categorías menos obvias, que una revisión superficial suele saltarse:**
- **Unrestricted Resource Consumption:** ¿puede un cliente autenticado pedir una página de
  10.000 resultados, subir un archivo sin límite de tamaño, o disparar una operación costosa
  (una llamada a un LLM, una consulta a un proveedor pago) sin ningún límite de tasa o de
  tamaño? Esto es tanto un problema de seguridad (DoS) como de costo (facturación
  descontrolada hacia un proveedor externo).
- **Unsafe Consumption of APIs:** el servicio confía ciegamente en lo que devuelve un
  proveedor externo (sin validar el esquema de la respuesta, sin timeouts, propagando datos
  no saneados de un tercero hacia el propio sistema o hacia el cliente).

## 5. Inyección: evaluar controlabilidad real, no solo presencia del patrón

**Encontrar `execute`, `subprocess`, `eval`, una consulta construida con f-strings, o un
motor de templates no es, por sí solo, una vulnerabilidad.** El hallazgo real requiere
confirmar que un atacante puede controlar el valor que llega a ese punto — si el valor
siempre proviene de una constante interna o de una fuente ya validada estrictamente, el
patrón existe pero no es explotable, y debe clasificarse como tal (sin dejar de señalar que
es una práctica de riesgo, útil para una regla de SAST — ver sección 8).

**Confirmar, para cada caso, la cadena completa:** ¿desde qué parámetro de entrada (path,
query, body, header) hasta qué sumidero (una consulta SQL, un comando de shell, un `eval`)
hay una ruta sin saneamiento ni parametrización en el medio? Sin esa cadena trazada, el
hallazgo es una hipótesis, no una vulnerabilidad confirmada.

## 6. Manejo de errores, logging y exposición de información

**Un `except Exception` genérico que expone el traceback, el mensaje de la excepción
original, o datos de otro usuario en la respuesta HTTP** es una fuente de fuga de
información que ayuda a un atacante a mapear el sistema (nombres de tablas, rutas internas,
versiones de librerías) incluso sin lograr explotar nada más. Los mensajes de error deben
distinguir entre lo que el cliente necesita saber (una operación falló, por qué en términos
de negocio) y lo que es un detalle de implementación interno (nunca expuesto).

**Logging:** verificar que no se registren contraseñas, tokens, API keys, números de
documento de identidad, ni cuerpos completos de requests que puedan contener datos
personales o financieros — y, en la dirección opuesta, que sí se registren los eventos
relevantes de seguridad (fallos de autenticación, cambios de permisos, operaciones
administrativas) para que un incidente real sea investigable después.

## 7. Lógica de negocio: la categoría con más impacto y menos herramientas automáticas

**Ninguna herramienta de SAST encuentra esto — requiere entender el dominio.** Un atacante
con credenciales legítimas puede, sin explotar ningún bug técnico clásico, encontrar que el
sistema permite: repetir una operación que debería ser única (duplicar una transacción
aprovechando falta de idempotencia — ver `concurrency-and-background-jobs.md`), ejecutar
pasos de un flujo fuera del orden esperado, modificar un monto o un estado que el servidor
debería validar de forma independiente del cliente, o aprovechar una ventana de
"comprobar-y-luego-modificar" (ver sección 9, condiciones de carrera) para obtener un
resultado que el flujo normal nunca permitiría.

**El formato de cada hallazgo de este tipo:** describir el flujo esperado, y después el
desvío concreto que un atacante podría ejecutar — no una afirmación abstracta de
"la lógica de negocio podría tener problemas".

## 8. Lo que debería automatizarse (SAST/SCA), no quedar solo en una auditoría manual

**Una auditoría puntual encuentra el estado de hoy; sin automatización, las mismas clases de
bugs vuelven a aparecer en el próximo cambio.** Traducir los hallazgos recurrentes en reglas
de herramientas de análisis estático (Bandit, Semgrep, CodeQL para Python) y de composición
de software (Dependabot, Snyk, `pip-audit`) que corran en cada pull request — ver también
`project-structure-and-tooling.md` sobre CI. Para cada regla candidata, decidir
explícitamente si su violación debe bloquear el merge o solo generar una advertencia —
tratarlas todas igual (todo bloqueante, o todo ignorado) desperdicia la herramienta.

**Sin esto, la seguridad depende de que alguien se acuerde de revisarla manualmente en cada
cambio** — lo mismo que ya se documenta como antipatrón en `testing-guidelines.md` para
cualquier capa de verificación que no corre en CI.

## 9. Condiciones de carrera en operaciones con estado

**El patrón de vulnerabilidad:** cualquier operación que haga "leer el estado actual,
decidir, luego escribir" sin una garantía atómica (una transacción con el nivel de
aislamiento correcto, un lock, una operación atómica a nivel de base de datos como
`UPDATE ... WHERE` condicional) tiene una ventana donde dos requests concurrentes pueden
leer el mismo estado "antes" y ambas escribir, produciendo un resultado que ninguna de las
dos habría producido sola — doble gasto de un cupo limitado, un descuento aplicado dos
veces, un recurso único reclamado por dos actores a la vez.

**Dónde buscarlo específicamente:** creación de recursos con una restricción de unicidad de
negocio (no solo técnica), cualquier contador o cupo, y cualquier operación financiera o de
reserva. La verificación real requiere revisar si la operación usa una primitiva atómica del
almacén de datos, no solo "parece que valida antes de escribir" en el código de aplicación.

## 10. SSRF y confianza en servicios externos

**Cualquier funcionalidad donde el servidor hace una petición HTTP hacia una URL que, directa
o indirectamente, proviene de un cliente** (un webhook configurable, un callback, una
descarga de un recurso por URL) es candidata a SSRF: un atacante puede apuntar esa URL hacia
`localhost`, una IP de red privada, un puerto interno, o el endpoint de metadata de la nube
(`169.254.169.254` en AWS/GCP/Azure, usado para obtener credenciales temporales de la
instancia). Verificar si existe una lista de permitidos de hosts/esquemas, o si el valor
simplemente se usa tal cual en el cliente HTTP saliente.

**La contraparte, igual de importante:** confiar ciegamente en lo que un servicio externo
devuelve (sin validar su esquema, sin timeout, propagando su respuesta sin saneamiento hacia
la lógica propia o hacia el cliente) traslada la superficie de ataque del propio sistema a
cualquier proveedor que se integre, presente o futuro.

## 11. Informe: priorizar por probabilidad de explotación × impacto, no por volumen

**Un informe de 80 hallazgos de severidad INFORMATIONAL no ayuda tanto como 5 hallazgos
CRITICAL/HIGH bien explicados con su escenario de ataque.** Estructurar el informe con un
resumen ejecutivo (riesgo general, conteo por severidad, qué debe corregirse antes de
cualquier entrega), una tabla de hallazgos con severidad/categoría/archivo/línea/impacto/
confianza, y una sección final explícita de **gaps de auditoría**: todo lo que no puede
verificarse solo con el código (IAM, configuración de red, TLS de despliegue, rate limiting
de infraestructura, gestión de secretos del entorno real) — para que el lector del informe
sepa exactamente qué quedó cubierto y qué no, en vez de asumir que "no mencionado" significa
"revisado y correcto".

## 12. Checklist

- [ ] Cada hallazgo está respaldado por código concreto (archivo y línea) o marcado
      explícitamente como NO VERIFICABLE, nunca asumido.
- [ ] Autenticación y autorización se evaluaron como preguntas separadas; para cada endpoint
      sobre un recurso con ID, se confirmó dónde se verifica la propiedad/permiso sobre ese
      recurso específico, no solo la identidad del actor.
- [ ] Se usó el OWASP API Security Top 10 (versión vigente) como checklist de cobertura, con
      estado y evidencia por categoría.
- [ ] Cada posible inyección se trazó de principio a fin (entrada controlable → sumidero sin
      saneamiento), no se marcó como hallazgo solo por la presencia del patrón.
- [ ] Se revisaron logs y manejo de errores por fuga de información sensible, y por registro
      insuficiente de eventos de seguridad relevantes.
- [ ] Se evaluó explícitamente la lógica de negocio (orden de operaciones, duplicación,
      manipulación de estado) además de las categorías técnicas clásicas.
- [ ] Los hallazgos recurrentes se tradujeron en reglas de SAST/SCA para CI, con una decisión
      explícita de si bloquean el merge.
- [ ] Toda operación "leer-decidir-escribir" sobre un recurso con restricción de negocio se
      revisó por condiciones de carrera, verificando si usa una primitiva atómica real.
- [ ] Cualquier URL construida parcial o totalmente desde datos de un cliente se evaluó por
      SSRF.
- [ ] El informe final distingue CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL, prioriza por
      probabilidad × impacto, e incluye una sección de gaps de auditoría explícita.
