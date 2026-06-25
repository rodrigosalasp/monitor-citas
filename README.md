# Monitor citas jura

Monitor automatizado para consultar disponibilidad de cita de jura de nacionalidad española.

## Archivos

- `monitor_citas.py`: script principal.
- `requirements.txt`: dependencias.
- `.github/workflows/monitor_citas.yml`: workflow de GitHub Actions.
- `.gitignore`: excluye credenciales y archivos generados.

## Secrets requeridos

Crear en `Settings -> Secrets and variables -> Actions -> Repository secrets`:

- `NIE`
- `NOMBRE_COMPLETO`
- `EMAIL_ORIGEN`
- `EMAIL_DESTINO`
- `EMAIL_PASSWORD`

`EMAIL_PASSWORD` debe ser una contraseña de aplicación de Gmail, no la contraseña normal.

## Ejecución

Desde GitHub: pestaña `Actions`, seleccionar `Monitor citas jura` y pulsar `Run workflow`.

También queda programado para ejecutarse una vez por hora.
