# Monitor citas jura

Monitor automático para consultar disponibilidad de cita de jura de nacionalidad española.

## Frecuencia

El workflow se activa tres veces por hora, aproximadamente en los minutos 07, 27 y 47. Antes de cada consulta introduce una espera aleatoria de hasta ocho minutos.

## Funciones principales

- Tres activaciones por hora desde GitHub Actions.
- Tres reintentos ante fallos transitorios de conexión.
- Clasificación de la fase y del tipo de error.
- Registro de la duración individual de cada intento.
- Historial acumulado en `historial_consultas.csv`.
- Migración automática del CSV antiguo al nuevo esquema.
- Correo ante posible disponibilidad o error final.
- Capturas ante posible cita o error.
- Artefactos de cada ejecución conservados durante 30 días.

## Nuevas columnas del historial

- `fase`
- `tipo_error`
- `duraciones_intentos_segundos`
