# Directrices de concurrencia y trabajos en segundo plano

Cómo diseñar el procesamiento asíncrono (colas, workers, tareas en segundo plano) de forma
que no se pierdan mensajes, no se dupliquen efectos y no se queme CPU en vano — para
cualquier servicio que desacople una API de su procesamiento.

## 1. "Al menos una vez" es el contrato real de cualquier cola

**El hecho de base:** SQS Standard, RabbitMQ, Kafka con `at-least-once`, Google Pub/Sub —
casi ninguna cola de mensajes real garantiza "exactamente una vez" sin trabajo adicional
explícito. Esto es documentado por cada uno de esos sistemas, no una limitación oculta: la
garantía por defecto es *at-least-once delivery*. Un mensaje se reentrega cuando el
consumidor no confirma a tiempo (timeout de visibilidad vencido, el proceso murió a mitad de
camino, una partición de red), sin importar si el mensaje ya se procesó.

**La consecuencia que hay que diseñar, no ignorar:** todo lo que un consumidor hace al
procesar un mensaje debe ser **idempotente** — ejecutarlo dos veces con el mismo mensaje debe
producir el mismo resultado que ejecutarlo una vez, nunca un efecto duplicado (un cobro
repetido, una notificación duplicada, una fila duplicada).

**El patrón: idempotencia con estados, no con una marca binaria.** La forma ingenua
("marcar la clave como vista antes de procesar, descartar si ya está marcada") rompe el
propio propósito de los reintentos: si la tarea falla después de marcar la clave, el
reintento legítimo que la cola iba a dar se descarta como "duplicado", y el trabajo real
nunca se completa — sin ningún error visible.

La forma correcta usa una máquina de estados explícita por clave de idempotencia:

```
claim(key)   -> crea el registro en IN_PROGRESS (falla si ya existe y no expiró)
...ejecutar la tarea...
complete(key) -> si tuvo éxito, pasa a DONE
release(key)  -> si falló, libera el registro para que el reintento pueda reclamarlo
```

Un mensaje se descarta como duplicado solo si su registro está en `DONE`. Esto es la misma
idea detrás del patrón **Idempotent Receiver** (Gregor Hohpe y Bobby Woolf, *Enterprise
Integration Patterns*, 2003) y de cómo Stripe documenta sus claves de idempotencia para la
API de pagos: una clave de idempotencia identifica una *operación*, no solo "ya vi este
mensaje una vez".

**La clave de idempotencia debe identificar el evento, no solo la entidad.** Si la clave es
`tarea:id_de_entidad` sin más, dos eventos legítimos y distintos sobre la misma entidad
(por ejemplo, "documento pendiente de firma" y luego "documento firmado" para el mismo caso)
colisionan en la misma clave, y el segundo se descarta como duplicado del primero. La clave
debe incluir lo que hace único al evento: un identificador de transacción propio si el
productor lo entrega, o al menos el tipo/estado del evento, no solo el identificador de la
entidad a la que pertenece.

## 2. Un efecto externo necesita su propia idempotencia, más fina que la del mensaje

**El problema:** una tarea que hace varios efectos visibles hacia afuera en secuencia (enviar
una notificación, luego consultar un proveedor pago, luego enviar otra notificación) tiene la
unidad de reintento equivocada si todo el método es un solo bloque. Si el último paso falla y
la tarea se reintenta completa, los pasos anteriores se repiten — se reenvía el mensaje que
el usuario ya recibió, se vuelve a pagar por la consulta al proveedor.

**El patrón: descomponer en pasos con su propio registro de progreso**, para que un
reintento salte los pasos ya completados y reutilice su resultado. Es la misma motivación
detrás de los **workflows duraderos** (Temporal, AWS Step Functions, Azure Durable
Functions): cada paso de un flujo de larga duración se registra por separado, así que el
motor puede retomar exactamente donde quedó, sin repetir efectos ya confirmados. No hace
falta adoptar un motor de orquestación completo para aplicar el principio a una escala menor
— basta con que cada paso con efecto externo compruebe (y registre) si ya se ejecutó antes
de actuar, usando la misma idea de idempotencia con estados de la sección 1, aplicada por
paso en vez de por mensaje completo.

## 3. Backpressure: nunca pedir más trabajo del que hay capacidad real para procesar

**El patrón, bien documentado en sistemas reactivos** (la especificación Reactive Streams, y
el patrón **Throttling** de la guía de Azure Architecture Center): un consumidor nunca debe
aceptar más unidades de trabajo de las que puede procesar en paralelo en ese momento. Sin
esto, el trabajo entrante se acumula en una cola interna sin límite (dentro del propio
proceso, no la cola externa), lo que crece la memoria sin tope bajo carga sostenida y puede
terminar en un *out-of-memory kill* — un fallo mucho más difícil de diagnosticar que "la cola
externa tiene mensajes esperando", porque el síntoma (el proceso muere) aparece lejos de la
causa (se pidió de más).

**La regla concreta:** si un consumidor usa un pool de hilos o de tareas con límite de
concurrencia `N`, nunca debe pedirle a la cola más de "cupos libres ahora mismo" mensajes por
vez — ni más (desperdicia la llamada y acumula en una cola interna sin control), ni menos de
lo posible (deja capacidad ociosa). Esto también evita el problema inverso y menos obvio:
**un consumidor que, al estar saturado, reintenta sin esperar nada** quema un núcleo de CPU
entero en un bucle que nunca hace trabajo real, compitiendo por el procesador con los hilos
que sí hacen trabajo. La corrección es **bloquear** (con un timeout razonable) hasta que haya
un cupo libre, no verificar y reintentar en un bucle apretado.

## 4. Apagado ordenado (graceful shutdown)

**El patrón:** todo proceso de larga duración que consume de una cola debe manejar la señal
de apagado del orquestador (SIGTERM en Docker/Kubernetes/systemd) haciendo tres cosas, en
orden: dejar de aceptar trabajo nuevo, esperar (con un tope de tiempo) a que el trabajo en
curso termine, y recién entonces salir. Esto está documentado explícitamente como requisito
por Kubernetes (el período de gracia entre SIGTERM y el SIGKILL forzado) y es la base del
patrón **graceful shutdown** en cualquier runtime de workers serio (Celery, Sidekiq, BullMQ
todos lo implementan por defecto).

**Por qué es crítico, no un detalle de limpieza:** sin esto, cada despliegue mata procesos
con trabajo en curso. Combinado con el problema de la sección 1 (si la idempotencia descarta
reintentos legítimos), un despliegue puede perder trabajo en producción sin que ningún log de
error lo señale — el mensaje simplemente nunca se completa, y se descarta como "duplicado" al
reintentarse. Un proceso sin manejo de apagado ordenado es una fuente activa de pérdida de
datos, no una mejora cosmética.

**Verificación concreta:** un test de resiliencia que envía SIGTERM al proceso con trabajo en
curso y confirma que ese trabajo se completa (o se libera limpiamente para reintento) antes
de que el proceso termine — ver `testing-guidelines.md` §4 sobre probar el artefacto
real.

## 5. No reinventar el consumidor si existe una librería madura para el broker elegido

**El problema:** un consumidor de cola escrito a mano (hilos propios, semáforo propio,
sondeo propio) tiende a acumular exactamente los bugs de las secciones 1 a 4, uno por uno, a
medida que se descubren bajo carga real.

**La alternativa:** frameworks de colas maduros (Celery para Python con varios brokers,
BullMQ para Node/Redis, Sidekiq para Ruby) ya resolvieron backpressure, confirmación tardía
(`acks_late`), reintentos con backoff, apagado ordenado y paralelismo seguro, con miles de
horas de producción detrás. Adoptar uno no es un lujo arquitectónico: es evitar reconstruir,
peor y más lento, lo que ya existe probado. Reservar el consumidor hecho a mano para casos
donde ningún framework cubre el broker elegido, y aun así, revisar la lista de esta sección
explícitamente contra la implementación propia.

## 6. Resiliencia hacia servicios externos

**Tres patrones independientes, los tres necesarios, ninguno sustituye a los otros:**

- **Reintentos con backoff exponencial y jitter** para errores transitorios (5xx, timeouts).
  El jitter (variación aleatoria en el tiempo de espera) evita que muchos clientes
  reintenten sincronizados exactamente al mismo instante tras una caída compartida — descrito
  en el paper de AWS *"Exponential Backoff And Jitter"* (Marc Brooker, 2015) y estándar en
  cualquier SDK de AWS/GCP moderno.
- **Circuit breaker** (Michael Nygard, *Release It!*, 2007): tras una racha de fallos hacia
  un proveedor, dejar de intentar durante una ventana de tiempo en vez de seguir golpeando (y
  acumulando timeouts en) un servicio que ya se sabe caído. Sin esto, un proveedor caído
  satura el pool de workers esperando timeouts, en vez de fallar rápido y liberar capacidad.
- **Reutilización de conexiones** (un cliente/sesión HTTP persistente, no una conexión nueva
  por llamada): abrir TCP y negociar TLS en cada request es un costo medible y evitable con
  cualquier cliente HTTP moderno, y se vuelve significativo exactamente bajo la carga donde
  más importa el rendimiento.

**Nunca reintentar a ciegas una operación que no es idempotente del lado del proveedor** (por
ejemplo, un envío de notificación o un cobro): eso se resuelve con la idempotencia por paso
de la sección 2, no con un reintento automático a nivel de transporte, que repetiría el
efecto.

## 7. Checklist

- [ ] Todo consumidor de cola asume entrega "al menos una vez" y es idempotente por diseño.
- [ ] La idempotencia usa estados (`IN_PROGRESS` / `DONE`, con liberación en fallo), no una
      marca binaria que se fija antes de ejecutar.
- [ ] La clave de idempotencia identifica el evento (tipo/estado), no solo la entidad.
- [ ] Un flujo con varios efectos externos en secuencia registra su progreso por paso, para
      que un reintento no repita efectos ya confirmados.
- [ ] El consumidor nunca pide a la cola más mensajes que cupos libres de concurrencia real.
- [ ] Un consumidor saturado espera (bloqueante, con timeout) por un cupo libre; nunca
      reintenta en un bucle apretado sin pausa.
- [ ] El proceso maneja SIGTERM: deja de tomar trabajo nuevo, espera el trabajo en curso
      (con tope), y recién entonces sale.
- [ ] Se evaluó un framework de colas maduro para el broker elegido antes de escribir un
      consumidor a mano.
- [ ] Las llamadas a servicios externos tienen reintentos con backoff + jitter, circuit
      breaker, y reutilización de conexiones — las tres cosas, no solo una.
- [ ] Ninguna llamada no idempotente del lado del proveedor se reintenta a ciegas a nivel de
      transporte.
