# Monitor citas jura

Monitor automático para consultar disponibilidad de cita de jura de nacionalidad española.

## Funciones principales

- Ejecución horaria desde GitHub Actions.
- Espera aleatoria antes de cada consulta.
- Tres intentos ante fallos transitorios de conexión.
- Correo ante posible disponibilidad o error final.
- Historial acumulado en `historial_consultas.csv`.
- Capturas ante posible cita o error.
- Artefactos de cada ejecución conservados durante 30 días.

## Secrets requeridos

En `Settings → Secrets and variables → Actions`:

- `NIE`
- `NOMBRE_COMPLETO`
- `EMAIL_ORIGEN`
- `EMAIL_DESTINO`
- `EMAIL_PASSWORD`

`EMAIL_PASSWORD` debe ser una contraseña de aplicación de Gmail.
