# Directrices de fallbacks y abstracciones

Cómo evitar que una abstracción (un fallback, una capa de compatibilidad, un patrón
repetido en varios módulos) se vuelva, con el tiempo, una fuente de fragilidad en vez de
protección contra ella.

## 1. Un fallback documentado pero no implementado es peor que no tener fallback

**El patrón de error:** un módulo central de infraestructura (por ejemplo, un lector de
secretos o de configuración) documenta explícitamente, en su propio docstring o README, que
tiene un camino de respaldo ("si el servicio de secretos falla, cae a una variable de
entorno"). Esa función de respaldo existe y funciona. Pero un módulo hermano, con la misma
responsabilidad para otro caso (leer las credenciales de un proveedor distinto), llama a la
función equivocada del mismo paquete — una que no tiene ese respaldo y devuelve un valor
vacío si falla — así que ante cualquier fallo real del servicio de secretos (no solo en
pruebas: throttling, un permiso mal configurado, una región equivocada), el código falla con
un error de clave faltante al intentar leer de ese valor vacío, en vez de usar la variable de
entorno que el sistema decía soportar.

**Por qué esto es peor que directamente no tener fallback:** un desarrollador que lee la
documentación, o que ve el mismo patrón funcionando en otro módulo del mismo proyecto, asume
razonablemente que el comportamiento documentado existe en todos lados. El costo de la
promesa rota no se paga al escribir el código — se paga en producción, en el peor momento
posible (cuando el servicio externo ya está fallando), y de la forma más confusa posible (un
error que no menciona en ningún lado "el servicio de secretos no respondió").

**La regla:** si un fallback, un valor por defecto, o un camino de degradación se
documenta como existente, debe verificarse con un test que lo ejercite de verdad
(simulando el fallo que dispara el fallback, no solo el camino feliz) — ver
`testing-guidelines.md` §4 sobre probar comportamiento real, no solo lo que un mock
deja ver. Un fallback sin un test que simule su disparador es una afirmación no verificada,
indistinguible de una mentira hasta que falla en producción.

## 2. Principio DRY aplicado a *contratos*, no solo a líneas de código

**El error común:** copiar un patrón (cómo se lee un secreto, cómo se hace una llamada HTTP,
cómo se reintenta una operación) de un módulo a otro a mano, en vez de centralizarlo en una
sola función o clase que todos los casos llaman. Cada copia es una oportunidad de que una
diverja sutilmente de las demás — como en el caso de la sección 1: dos módulos con la misma
responsabilidad (leer secretos con fallback), dos implementaciones, solo una completa.

**El principio detrás, bien establecido:** *Don't Repeat Yourself* (Andy Hunt y Dave Thomas,
*The Pragmatic Programmer*, 1999) se enuncia casi siempre sobre líneas de código duplicadas,
pero su forma más peligrosa es la duplicación de **conocimiento o contrato**: dos lugares que
deberían garantizar lo mismo ("este secreto siempre cae a una variable de entorno si el
servicio falla") pero que lo implementan cada uno por su cuenta. La duplicación de código se
nota al leer; la duplicación de contrato solo se nota cuando uno de los dos caminos falla de
una forma que el otro nunca haría.

**La regla:** cuando dos o más módulos resuelven el mismo tipo de problema (leer un secreto,
llamar a un proveedor externo, reintentar una operación), deben pasar por la **misma**
función o clase base — no por implementaciones paralelas que *deberían* comportarse igual.
Si un caso legítimamente necesita algo distinto, eso se modela como un parámetro o una
subclase de la abstracción compartida, no como una reimplementación desde cero.

**Cómo detectarlo en revisión de código:** cuando se agrega un módulo nuevo que hace "lo
mismo que ya existe en otro lado" (leer config, llamar a una API, loguear una métrica),
preguntar explícitamente: ¿por qué este no reutiliza la función/clase que ya resuelve esto
para el otro caso? Si la respuesta es "porque es un poco distinto", verificar si esa
diferencia es real o si es simplemente que nadie generalizó la abstracción existente para
cubrir ambos casos.

## 3. Fallar rápido y explícito es mejor que degradar en silencio

**El patrón: fail-fast** (documentado extensamente en el diseño de sistemas distribuidos,
por ejemplo en *Release It!* de Michael Nygard, 2007, y en la guía de Google SRE): cuando
una precondición no se cumple, es preferible que el sistema falle de inmediato y de forma
visible, en vez de continuar con un estado parcial o inconsistente que produce un fallo más
confuso más adelante, lejos de la causa real.

**Ejemplo del tipo de caso donde aplica:** un despachador de tareas en segundo plano que, al
no encontrar la configuración de a qué cola enviar un mensaje, lanza una excepción clara de
inmediato — en vez de, como alternativa peor, caer en silencio a ejecutar la tarea de forma
local/síncrona "para no romper nada". Esa alternativa parece más tolerante a fallos, pero en
realidad enmascara una configuración incompleta en vez de hacerla fallar donde se nota, y
deja un camino de código (el modo local) que nadie prueba ni mantiene a propósito.

**La regla:** cuando una configuración requerida falta, o una dependencia no está
disponible, el código debe fallar con un error específico que identifique exactamente qué
falta — no continuar con un valor vacío, un `None` silencioso, o un camino alternativo no
solicitado. Esto aplica tanto a errores de configuración (una URL vacía) como a errores de
lectura (una excepción capturada que se convierte en un valor vacío sin volver a lanzarse) —
ver también la sección 4.

## 4. Capturar una excepción sin distinguir sus causas esconde bugs reales

**El antipatrón:** un `except Exception: return None` (o `return {}`, o `return []`) que
trata cualquier fallo —una excepción de red transitoria, un bug de programación, un error de
permisos— de la misma forma indistinguible. El llamador no puede diferenciar "no había
datos" de "algo salió mal leyéndolos", y por lo tanto no puede reaccionar de forma distinta a
cada caso.

**Ejemplo del tipo de caso donde aplica:** la lectura del estado de una sesión de usuario que
captura cualquier excepción de la base de datos y devuelve "no hay sesión" — el mismo valor
que "esta sesión nunca existió". El resultado es que un error transitorio de infraestructura,
a mitad de una interacción activa, reinicia al usuario en silencio desde el principio del
flujo, en vez de mostrar un error recuperable.

**La regla:** distinguir explícitamente entre "no hay dato" (un caso de negocio válido,
representable como `None` o una lista vacía) y "no se pudo leer el dato" (un error técnico,
que debe propagarse o registrarse de forma visible, nunca camuflarse como ausencia de dato).
Capturar `Exception` a secas rara vez es correcto — capturar el tipo específico esperado
(una excepción de cliente HTTP, una excepción del driver de base de datos) dice, con el tipo
mismo, qué se esperaba que pudiera fallar y por qué.

## 5. Checklist

- [ ] Todo fallback documentado tiene un test que simula su disparador y confirma que se
      ejecuta — no solo que existe en el código.
- [ ] Ningún módulo reimplementa desde cero un patrón (leer config, llamar a una API externa,
      reintentar una operación) que ya resuelve una función o clase compartida en el
      proyecto.
- [ ] Al agregar código que hace "algo parecido a lo que ya existe", se evaluó
      explícitamente reutilizar la abstracción existente antes de escribir una nueva.
- [ ] Una configuración requerida que falta produce un error explícito e inmediato, no una
      ejecución en un modo alternativo no solicitado.
- [ ] Ningún `except Exception` (o equivalente) devuelve un valor indistinguible de "no hay
      dato" cuando en realidad significa "no se pudo leer el dato".
- [ ] Las excepciones capturadas son del tipo específico esperado, no `Exception` genérico,
      salvo en el borde más externo del sistema (un manejador de errores de último recurso).
