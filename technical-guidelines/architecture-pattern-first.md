# Directriz: nunca empezar un proyecto sin decidir primero su patrón de arquitectura

Antes de escribir la primera línea de código de un proyecto nuevo — o de un subsistema
nuevo dentro de uno existente — se decide explícitamente qué patrón o estilo arquitectónico
va a regirlo, se documenta esa decisión con su razonamiento, y recién entonces se empieza a
construir.

## 1. Por qué esto va primero, no después

**El problema que previene:** sin una decisión explícita, el patrón de arquitectura no deja
de existir — simplemente queda implícito, y cada desarrollador lo infiere a su manera a
medida que escribe código. El resultado típico no es "sin arquitectura", es una mezcla no
intencional de dos o tres patrones distintos conviviendo en el mismo sistema, cada uno
aplicado solo donde a quien escribió ese módulo le pareció razonable en el momento. Eso es
más difícil de mantener que haber elegido mal un solo patrón desde el principio, porque un
error de patrón se corrige con una migración deliberada; una mezcla implícita no tiene ni
siquiera un nombre claro que discutir.

**La secuencia correcta de decisiones**, siguiendo cómo lo plantea el método **ATAM**
(*Architecture Tradeoff Analysis Method*, Kazman et al., Software Engineering Institute /
Carnegie Mellon, 2000) y la práctica estándar de documentar una **ADR-0** (la primera
*Architecture Decision Record* de un proyecto, convención popularizada por Michael Nygard,
2011): primero se identifican los atributos de calidad que más importan para este sistema
en particular (¿importa más la latencia, el desacople entre equipos, la facilidad de
testear, el costo de cómputo, la velocidad de entrega?), después se elige el patrón que
mejor sirve a esos atributos — nunca al revés. Un patrón no es "bueno" o "malo" en
abstracto; es más o menos adecuado para las prioridades concretas de este sistema.

## 2. Qué significa "decidir el patrón", en concreto

No es elegir un framework ni una tecnología — es decidir la forma en que las
responsabilidades se dividen y cómo las partes se comunican entre sí. Algunos estilos
reconocidos, documentados en la literatura de arquitectura de software (Mary Shaw y David
Garlan, *Software Architecture: Perspectives on an Emerging Discipline*, 1996; y su
tratamiento más reciente en Mark Richards y Neal Ford, *Fundamentals of Software
Architecture*, 2020), entre los que cualquier proyecto nuevo debería elegir
conscientemente:

- **Monolito en capas** (presentación → lógica de negocio → acceso a datos): el punto de
  partida razonable cuando el equipo es pequeño, el dominio aún no está bien delimitado, y
  el costo de operar varios servicios no se justifica todavía.
- **Arquitectura hexagonal / Ports & Adapters** (Alistair Cockburn, 2005): el núcleo de
  negocio no conoce los detalles de infraestructura (qué base de datos, qué cola, qué
  proveedor externo); se comunica con ellos a través de interfaces (*puertos*) que
  implementaciones concretas (*adaptadores*) satisfacen. Adecuado cuando se espera cambiar
  de proveedor de infraestructura, cuando hace falta portabilidad entre entornos (nube,
  on-premise), o cuando se quiere testear la lógica de negocio sin infraestructura real.
- **Arquitectura dirigida por eventos / Producer-Consumer** (Hohpe y Woolf, *Enterprise
  Integration Patterns*, 2003): los componentes se comunican a través de colas o streams de
  eventos en vez de llamadas directas. Adecuado cuando el trabajo se puede procesar de
  forma asíncrona, cuando distintas partes del sistema escalan a ritmos distintos, o cuando
  se necesita absorber picos de carga sin que el productor espere al consumidor.
- **Microservicios**: el sistema se divide en servicios desplegados de forma independiente,
  cada uno dueño de sus propios datos. Adecuado cuando distintos equipos necesitan
  desplegar sin coordinarse, o cuando partes del sistema tienen necesidades de escala
  radicalmente distintas — no adecuado solo "porque es lo moderno": trae un costo operativo
  real (observabilidad distribuida, consistencia eventual, más piezas que desplegar) que
  debe justificarse contra ese costo, no asumirse gratis.
- **Flujos definidos en código versionado, en vez de un motor de configuración/DSL
  genérico:** cuando la variabilidad entre casos (distintos clientes, distintos flujos de
  negocio) se resuelve mejor con módulos de código propios, testeables y con control de
  versiones real, que con un lenguaje de configuración ad hoc que termina reimplementando,
  peor, las capacidades de un lenguaje de programación de verdad (sin depurador, sin tests,
  sin trazas de pila) en cuanto aparece el primer caso no previsto.

Esta lista no es exhaustiva ni mutuamente excluyente — un sistema real suele combinar más
de uno (por ejemplo, hexagonal *dentro* de un servicio, dirigido por eventos *entre*
servicios). Lo que importa no es memorizar la lista, sino que la combinación elegida sea
explícita y argumentada, no accidental.

## 3. Qué significa "documentarlo", en concreto

La decisión se registra como una ADR, con la misma estructura que cualquier otra decisión
de arquitectura (ver `architecture-documentation.md` §2 y §3): contexto, alternativas
consideradas, decisión tomada, justificación, consecuencias aceptadas. La justificación
debe responder, explícitamente, a los atributos de calidad que están detrás de la elección
— no basta con nombrar el patrón, hay que explicar *para qué* se eligió y qué se sacrifica
a cambio.

**Las consecuencias aceptadas son la parte que más se omite y la que más importa.** Todo
patrón de arquitectura tiene un costo: el monolito en capas facilita empezar rápido y
sacrifica el aislamiento entre módulos a largo plazo; lo dirigido por eventos gana
desacople y escalabilidad y sacrifica la capacidad de razonar sobre el sistema con un
simple stack trace (ver `concurrency-and-background-jobs.md` sobre los problemas reales que
esto introduce si no se maneja con disciplina); los microservicios ganan despliegue
independiente y sacrifican simplicidad operativa. Documentar la decisión sin documentar su
costo es solo publicidad del patrón elegido, no una decisión de arquitectura real.

## 4. Señales de que un proyecto se empezó sin esta decisión

- Dos módulos que resuelven el mismo tipo de problema (comunicación entre componentes,
  acceso a datos, configuración) de formas estructuralmente distintas, sin que ninguna
  decisión documentada explique por qué.
- Un intento de abstracción genérica (un motor de configuración, una capa de
  compatibilidad) que quedó a medio construir y sin uso real en el código — rastro visible
  de que el patrón se decidió a mitad de camino, después de que ya existía código escrito
  bajo un supuesto distinto, y migrar a esa altura costaba más que vivir con el fragmento
  muerto.
- La necesidad de preguntar "¿por qué esto se hizo así?" sobre una decisión estructural
  básica (síncrono vs. asíncrono, un servicio vs. varios, capas vs. eventos) y que la
  respuesta sea "así se fue dando", en vez de una justificación citable.

## 5. Checklist

- [ ] Antes de escribir código, se identificaron explícitamente los atributos de calidad
      que más importan para este sistema (latencia, desacople, costo, velocidad de entrega,
      testabilidad, portabilidad) — no se asumió un patrón por costumbre o por lo último
      que se usó en otro proyecto.
- [ ] Se eligió un patrón o combinación de patrones explícito (en capas, hexagonal,
      dirigido por eventos, microservicios, u otro) que responde a esos atributos.
- [ ] La decisión está documentada como una ADR (ver `architecture-documentation.md`), con
      contexto, alternativas consideradas, justificación y consecuencias aceptadas.
- [ ] La justificación explica para qué se eligió el patrón, no solo qué se eligió.
- [ ] Las consecuencias documentadas incluyen el costo real del patrón elegido, no solo sus
      beneficios.
- [ ] Antes de agregar un subsistema nuevo a un proyecto existente (un motor de
      configuración, un nuevo mecanismo de comunicación entre componentes), se verificó que
      encaje con el patrón ya decidido, o se documentó explícitamente por qué este
      subsistema se aparta de él.
- [ ] Ningún módulo nuevo resuelve un problema ya resuelto en otra parte del sistema con un
      patrón estructuralmente distinto, sin una decisión documentada que lo justifique.
