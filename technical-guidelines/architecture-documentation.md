# Directrices de documentación de arquitectura

Cómo escribir y, sobre todo, mantener vivo un documento de arquitectura de solución — para
cualquier proyecto, no solo al iniciarlo.

## 1. Usar una plantilla reconocida, no inventar una estructura propia

**La plantilla:** la estructura de 13 secciones (introducción y objetivos, restricciones,
contexto y alcance, estrategia de solución, arquitectura de componentes, flujos de
operación, infraestructura y despliegue, conceptos transversales, decisiones de
arquitectura, requisitos de calidad, riesgos, glosario, pendientes de definición) es, casi
sección por sección, el modelo **arc42** (Gernot Starke y Peter Hruschka, de uso extendido en
Europa y documentado en detalle en [arc42.org](https://arc42.org)). No hace falta
reinventarla: arc42 ya resuelve qué información necesita un documento de arquitectura para
ser útil a quien no participó en el diseño, y en qué orden presentarla.

**Las tres vistas que arc42 separa deliberadamente**, y por qué no deben mezclarse en un
mismo diagrama:
- **Vista de bloques de construcción** (sección "Arquitectura de componentes"): de qué
  partes está hecho el sistema y cómo se relacionan — estática, sin tiempo.
- **Vista de ejecución/runtime** (sección "Flujos de operación"): cómo se comporta el
  sistema en el tiempo, para los escenarios concretos que importan — dinámica.
- **Vista de despliegue** (sección "Infraestructura y despliegue"): dónde corre
  físicamente cada componente (qué cuenta cloud, qué red, qué cómputo) — la vista de
  infraestructura.

Un diagrama que mezcla las tres (componentes lógicos, su secuencia de llamadas, y la
infraestructura donde corren, todo junto) termina siendo ilegible para cualquiera de las tres
preguntas que un lector real se hace: "¿qué hace esto?", "¿cómo se comporta bajo esta
situación?", "¿dónde corre y cuánto cuesta?". Mantener las vistas separadas, aunque se
repita algo de información entre ellas, es la decisión correcta — esto es lo que arc42 llama
explícitamente la razón de tener vistas separadas en primer lugar.

## 2. Disciplina de rigor: nunca inventar, siempre distinguir qué se sabe de qué se asume

**La regla central, la que hace la diferencia entre un documento útil y uno que genera falsa
confianza:** cada afirmación del documento debe poder rastrearse a una fuente verificable
(código real, configuración real, una decisión de negocio ya comunicada) — nunca a lo que
"sería razonable que el sistema hiciera". Cuando falta información necesaria para completar
una sección, se marca explícitamente como **"Pendiente de definición"** o
**"Información no disponible"**, nunca se rellena con una suposición plausible.

**Por qué esto importa más de lo que parece:** un documento de arquitectura se usa para
tomar decisiones — de capacidad, de seguridad, de presupuesto. Una afirmación inventada que
"suena razonable" es peor que un espacio en blanco, porque el espacio en blanco visiblemente
pide ser completado, mientras que la afirmación inventada se lee como un hecho verificado y
se arrastra a decisiones posteriores sin que nadie vuelva a cuestionarla.

**Distinguir explícitamente, en cada sección donde aplique:**
- Situación actual (lo que el sistema hace hoy, verificado contra código/configuración real).
- Solución propuesta (lo que se plantea, pero aún no existe).
- Decisiones ya tomadas (con su fecha y quién las tomó, si se sabe).
- Decisiones pendientes (una alternativa posible no es una decisión tomada).
- Supuestos (lo que el documento asume por falta de información, marcado como tal).

**Cuando dos fuentes se contradicen** (dos documentos, un documento y el código real, dos
configuraciones de distintos entornos), no se elige una arbitrariamente para que el
documento quede "limpio" — se documenta la contradicción explícitamente y se marca como
pendiente de resolución, citando ambas fuentes.

## 3. El documento es un artefacto vivo, no un entregable de una sola vez

**El problema más común en la práctica:** el documento se escribe con buen rigor al inicio
de un proyecto o tras un ejercicio de arquitectura, y luego queda congelado mientras el
sistema real sigue cambiando — una nueva integración, un cambio de proveedor cloud, una
corrección de una decisión previa. Meses después, el documento describe un sistema que ya no
existe, y es peor que no tener documento: alguien lo lee, confía en él, y toma una decisión
basada en información obsoleta sin saberlo.

**La disciplina a establecer desde el principio, no después:**
- **Revisar el documento como parte de cualquier cambio arquitectónico significativo**
  (una integración nueva, un cambio de topología de despliegue, una decisión que reemplaza
  una ya documentada) — del mismo modo que un cambio de esquema de base de datos requiere
  una migración, un cambio de arquitectura requiere actualizar el documento que la describe.
  Si el equipo usa ADRs (*Architecture Decision Records*, Michael Nygard, 2011) para
  decisiones puntuales, el documento de arquitectura de solución es el lugar donde esas
  decisiones se consolidan en una vista completa y coherente del sistema — los ADRs
  documentan el momento de la decisión; el documento de arquitectura describe el estado
  resultante.
- **La sección "Pendientes de definición" no es un archivo muerto.** Cada entrada debe tener,
  si es posible, una fecha o un disparador de revisión ("pendiente hasta que se confirme el
  volumen de producción", no solo "pendiente"). Una lista de pendientes que crece sin que
  ninguna entrada se resuelva ni se revise es la señal de que el documento dejó de usarse
  activamente — vale la pena revisarla completa periódicamente, no solo agregarle entradas.
- **Un documento desactualizado con fecha visible es mejor que uno actualizado sin ella.**
  Cada versión del documento debe declarar su fecha de última revisión, para que cualquier
  lector pueda evaluar por sí mismo qué tan vigente es la información, en vez de asumir
  que un documento sin fecha está siempre al día.

## 4. Formato: explicar en prosa, usar tablas para lo tabular

**Evitar convertir todo el documento en listas con viñetas.** Las secciones que explican
*por qué* se tomó una decisión, *cómo* funciona un flujo, o *qué* implica una restricción se
redactan en párrafos — una lista de viñetas no transmite la relación causal ni el
razonamiento, solo enumera hechos sueltos. Reservar las tablas para información
genuinamente tabular: componentes (nombre, responsabilidad, tecnología, dependencias),
requisitos de calidad (categoría, objetivo, cómo se implementa, cómo se verifica),
decisiones (contexto, alternativas, decisión, justificación, estado), riesgos, interesados.

**Explicar el *por qué*, no solo el *qué*.** Listar las tecnologías elegidas sin explicar por
qué se descartaron las alternativas es information, no es arquitectura documentada — la
sección de estrategia de solución y la de decisiones de arquitectura existen específicamente
para capturar el razonamiento, que es lo que se pierde primero cuando las personas que
decidieron ya no están en el proyecto.

**Diagramas: uno por vista, nunca uno que mezcle todo.** Como mínimo: un diagrama de
contexto (el sistema y sus actores/sistemas externos), uno de componentes (bloques de
construcción y sus relaciones), uno de flujo o secuencia del flujo principal (vista de
runtime), y uno de infraestructura/despliegue. Cada uno muestra solo el nivel de detalle que
corresponde a su vista — mezclar niveles de abstracción en un mismo diagrama es la forma más
común de hacerlo ilegible.

## 5. Checklist

- [ ] El documento sigue una plantilla reconocida (arc42 u otra equivalente), no una
      estructura ad hoc inventada para el proyecto.
- [ ] Las vistas de componentes, runtime y despliegue están separadas, cada una en su propio
      diagrama, sin mezclar niveles de abstracción.
- [ ] Toda afirmación se puede rastrear a una fuente verificable (código, configuración,
      una decisión comunicada) — nada se completó por parecer razonable.
- [ ] Cada sección distingue explícitamente situación actual, propuesta, decisiones tomadas,
      decisiones pendientes y supuestos.
- [ ] Las contradicciones entre fuentes están documentadas como tales, no resueltas
      arbitrariamente para que el documento se vea limpio.
- [ ] El documento declara su fecha de última revisión.
- [ ] Existe un proceso (aunque sea informal) que dispara una revisión del documento ante un
      cambio arquitectónico significativo — no se actualiza solo "cuando alguien se acuerda".
- [ ] La sección de pendientes de definición se revisa periódicamente, no solo se le agregan
      entradas nuevas sin nunca resolver ni descartar las viejas.
- [ ] Las secciones explicativas están en prosa; las tablas se usan para información
      genuinamente tabular (componentes, requisitos, decisiones, riesgos).
- [ ] Las decisiones de arquitectura documentan el *por qué* (contexto, alternativas,
      justificación), no solo *qué* se eligió.
