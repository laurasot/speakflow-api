# Directrices de testing

Cómo construir una suite de tests que realmente detecte regresiones, para cualquier
servicio FastAPI (o similar) — no "tener tests", sino tests que fallen cuando lo que
prueban se rompe.

## 1. La pirámide de tests, y por qué existe cada capa

La pirámide clásica (Mike Cohn, *Succeeding with Agile*, 2009) sigue siendo válida: muchos
tests unitarios rápidos, menos tests de integración, muy pocos de punta a punta. Cada capa
responde una pregunta distinta, y saltarse una deja un punto ciego que ninguna otra cubre:

| Capa | Pregunta que responde | Velocidad | Lo que no puede detectar |
|---|---|---|---|
| Unitaria | ¿Esta función/clase hace lo que dice, de forma aislada? | Milisegundos | Si las piezas funcionan juntas; si la infraestructura real se comporta como se mockeó |
| Integración | ¿Dos componentes reales están de acuerdo en un contrato (un esquema de BD, la forma de una llamada HTTP, el formato de un mensaje de cola)? | Segundos | Si el sistema completo, ya ensamblado, produce el resultado correcto |
| Punta a punta | ¿Una request real contra el sistema real produce el resultado correcto? | Decenas de segundos a minutos | Nada estructuralmente, pero es demasiado lenta/cara para usar en cada caso |

Una suite 100% unitaria con todo mockeado puede pasar mientras el sistema real está roto,
porque los mocks codifican una suposición sobre cómo se comporta una dependencia real que
nunca se verificó. Una suite mayormente de punta a punta es precisa pero demasiado lenta
para correr en cada commit, y un fallo no dice dónde está el bug. Ambos modos de falla son
comunes en la práctica — no es hipotético.

**Regla:** las tres capas deben existir. Si el proyecto solo tiene tests unitarios con todo
lo externo mockeado, no hay forma de saber si el Dockerfile real, las migraciones reales o
el consumidor de cola real funcionan — solo si las suposiciones sobre ellos, codificadas
como mocks, son internamente consistentes.

## 2. Tests de contrato / de caracterización ("golden")

**El problema que resuelven:** un refactor (cambiar de librería HTTP, mover un archivo,
renombrar un campo) puede cambiar en silencio un comportamiento observable desde afuera —
la forma de una respuesta, un mensaje que el servicio publica, una columna de base de datos
que otro servicio lee — mientras todos los tests existentes siguen pasando, porque esos
tests verifican *cómo* el código hace algo, no *qué* produce.

**La técnica**, conocida como **characterization testing** (Michael Feathers, *Working
Effectively with Legacy Code*, 2004) o **golden/snapshot testing**: capturar la salida
actual, revisada y aceptada como correcta, de una unidad de comportamiento en un archivo
versionado, y verificar que las corridas futuras coincidan. Un desajuste no necesariamente
significa un bug — significa "esto cambió, hay que mirar el diff y decidir si es
intencional". Es la misma idea detrás del snapshot testing de Jest/Vitest en el ecosistema
JS y de `syrupy`/`pytest-snapshot` en Python, aplicada deliberadamente y no generada a
ciegas.

**Qué capturar en un servicio FastAPI**, como mínimo:
- El contrato completo observable de cada endpoint HTTP que encola trabajo en segundo
  plano: código de estado, cuerpo de la respuesta, **y** cada tarea/mensaje encolado como
  resultado — no solo la respuesta HTTP, que suele ser la parte menos interesante de un
  endpoint asíncrono.
- Las llamadas HTTP reales hechas a cada proveedor externo (método, URL, headers, body) —
  capturadas corriendo el cliente real contra un servidor stub real por un socket loopback,
  no mockeando las funciones internas del cliente. Mockear el cliente HTTP a nivel de
  función verifica que el código llama a un mock; correr el cliente real contra un servidor
  HTTP real verifica que la request está bien formada de verdad.
- Cualquier esquema (columnas de BD, forma de un mensaje) que lea un servicio *distinto,
  desplegado de forma independiente* — ahí no hay ningún compilador que detecte el
  desajuste.

**La no determinación no es excusa para saltarse esto.** Un UUID generado, un timestamp, un
orden aleatorio — normalizar cada uno a un placeholder estable numerado por orden de
aparición (`<uuid-0>`, `<uuid-1>`, ...) antes de comparar. Esto sigue detectando las
regresiones que importan (por ejemplo, dos valores que deberían coincidir y dejan de
hacerlo) sin volver inestable el test por los valores que no importan.

**Verificar el mecanismo mismo, no solo las aserciones.** Un test de snapshot vale solo lo
que vale su capacidad de fallar. Antes de confiar en un golden test nuevo: romper a
propósito el comportamiento que dice proteger (introducir el bug deliberadamente), confirmar
que el test falla por esa razón exacta, y revertir. Un test de snapshot que nunca falla
porque su setup queda en silencio sin ejercitar nada (por ejemplo, el mock del que depende
nunca se activó de verdad) da una falsa sensación de seguridad — peor que no tener el test,
porque aparenta cobertura.

## 3. Escribir el test que falla *antes* de escribir la corrección

**La práctica:** al encontrar un bug, escribir primero el test que lo reproduce, confirmar
que falla por la razón correcta, y solo entonces corregir el código. Es la mitad "test
primero" de TDD (Kent Beck, *Test-Driven Development: By Example*, 2002), aplicada
específicamente a corrección de bugs en vez de a funcionalidad nueva — a veces llamado
*regression-test-first*, o escribir un "test en rojo".

**Por qué esto importa más para bugs que para funcionalidad nueva:** una corrección sin un
test que la reproduzca prueba que el bug desapareció *hoy*, en *este* camino de código, tal
como lo ejercitó *una revisión manual*. No prueba nada sobre mañana, después de que el
siguiente refactor toque el mismo código. El test es lo que sobrevive.

**En Python/pytest, marcar el test que reproduce el bug como `xfail(strict=True)`** mientras
el bug sigue abierto:

```python
@pytest.mark.xfail(strict=True, reason="BUG-123: el reintento descarta un mensaje en vez de reprocesarlo")
def test_un_fallo_transitorio_se_reintenta_y_termina_bien():
    ...
```

`strict=True` es el detalle crítico: sin él, un test que empieza a *pasar* (porque alguien
corrigió el código de fondo sin saber que este test existía) se reporta en silencio como
"fallo esperado, pero pasó" y nadie lo nota. Con `strict=True`, pytest convierte eso en un
fallo duro de la suite (`XPASS(strict)`), lo que obliga a quien corrigió el bug a encontrar
este test y quitarle la marca — dejando la corrección demostrada, no asumida. Este patrón de
"fallo esperado que eventualmente debe dejar de fallar" es también cómo varios proyectos
open source grandes (CPython, Django) registran problemas conocidos dentro de su propia
suite de tests, no solo en un issue tracker externo.

**Antes de confiar en un test `xfail`, correrlo saltándose la marca**
(`pytest --runxfail`) y leer el traceback real — confirmar que falla por la razón
documentada, no por un error de setup no relacionado que también lanza una excepción.

## 4. Probar el artefacto real, no un sustituto de él

**El antipatrón:** una suite de tests que pasa, un Dockerfile que nunca se construyó en CI,
una migración de base de datos que nunca corrió contra una base real, un archivo
docker-compose que nadie levantó en meses. Cada uno de estos es una sorpresa de despliegue
esperando a ocurrir, y ninguno aparece como "un test que falla" — aparece como un incidente.

**La práctica, alineada con la capa superior de la pirámide:** tener al menos un test, que
corra con regularidad (idealmente en CI, no solo localmente y de memoria), que:
- construya el Dockerfile de producción real (no uno parecido), y
- corra el contenedor real, pegándole a su endpoint de salud, y
- si el servicio es dueño de un esquema, aplique las migraciones reales contra una
  instancia real del motor de base de datos real (por ejemplo vía `testcontainers` o un
  stack `docker compose` descartable — no SQLite haciendo de MySQL o PostgreSQL, cuyo
  dialecto SQL, comportamiento de constraints y requisitos de índices difieren todos), y
- para un proyecto con workers en segundo plano, ejercite un mensaje real a través de la
  tecnología de cola real (por ejemplo ElasticMQ, SQS vía LocalStack, o un contenedor
  RabbitMQ real) de punta a punta — no un cliente de cola mockeado.

**Esta capa es cara, así que hay que mantenerla acotada** (uno o dos flujos críticos, no
cada endpoint) y marcarla para que quede excluida de la corrida rápida por defecto (un
marker dedicado de pytest, por ejemplo `integration`, o un job separado de CI) — pero igual
debe correr en algún programa regular o en cada merge, o se pudre en silencio.

**Para qué sirve esta capa, en concreto:** es la única que detecta un Dockerfile roto, una
migración que referencia una columna que no existe, un fallback que estaba documentado pero
nunca implementado, o una variable de entorno que el contenedor real necesita pero ningún
test unitario definió. Ninguna de estas es una categoría hipotética — es exactamente el tipo
de bug que los tests unitarios, por construcción, no pueden ver, porque el mock del test ya
codifica la suposición que resultó estar equivocada.

## 5. Disciplina de mocking

**Mockear en el borde del sistema, no dentro de él.** Mockear el transporte del cliente
HTTP (lo que viaja por la red), no la función propia que lo envuelve — mockear la función
propia solo verifica que esa función se llama a sí misma correctamente. Cuanto más adentro
del código propio llega un mock, más probable que un refactor rompa el test por una razón
que no tiene nada que ver con el comportamiento que debía proteger.

**Una variable de entorno, archivo de configuración o `.env.example` de test debe ser
responsabilidad de la suite de tests, no heredado de lo que haya en la máquina del
desarrollador.** Si la corrección de un test depende de que exista un `.env` real con
valores específicos que ningún fixture del test verifica, el resultado del test depende de
qué máquina lo corre. En CI (donde ese archivo no existe) puede fallar o tomar en silencio
un camino de código distinto al que realmente se despliega. La corrección es que el setup
del test (un fixture, no un archivo personal del desarrollador) defina cada variable de
entorno que el código bajo prueba lee, explícitamente, para que el comportamiento del test
sea reproducible en cualquier máquina, incluido CI.

**Nunca dejar que un test dependa del orden de ejecución o de estado mutable compartido**
(una caché a nivel de módulo, un pool de hilos en segundo plano, un atributo de clase). Los
tests que pasan solos y fallan en la suite completa (o al revés) son la fuente más común de
CI "inestable" y erosionan la confianza en toda la suite más rápido que casi cualquier otra
cosa — una vez que un equipo empieza a reintentar un job de CI fallido "porque seguro es
intermitente", la suite dejó de cumplir su función.

## 6. Checklist

- [ ] Unit tests cubren la lógica de negocio de forma aislada, con lo externo mockeado en el
      borde del sistema (transporte HTTP, driver de BD), no más adentro.
- [ ] Cada endpoint HTTP que dispara trabajo en segundo plano tiene un test que verifica el
      contrato completo: la respuesta **y** lo que se encoló/envió.
- [ ] Cada integración saliente (la API de otro servicio) tiene al menos un test que
      ejercita el cliente real contra un servidor stub real, no un método de cliente
      mockeado.
- [ ] Cada bug conocido tiene un test de regresión, escrito para fallar primero y mantenido
      como `xfail(strict=True)` hasta que la corrección llegue.
- [ ] Al menos un test construye el Dockerfile real y le pega al endpoint de salud del
      contenedor real.
- [ ] Si el servicio es dueño de un esquema, al menos un test aplica las migraciones reales
      contra una instancia real del motor de base de datos real.
- [ ] Si el servicio tiene workers en segundo plano, al menos un test ejercita un mensaje a
      través de la tecnología de cola real de punta a punta.
- [ ] Ningún test depende, para ser correcto, de una variable de entorno no verificada, un
      archivo local del desarrollador, o el orden de ejecución.
- [ ] CI corre las capas rápidas (unitaria, contrato/golden) en cada commit; la capa lenta
      (punta a punta, infraestructura real) corre en un programa regular o como gate, no
      solo "cuando alguien se acuerda".
