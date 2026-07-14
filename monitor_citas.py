# monitor_citas.py
# Monitor de citas para jura de nacionalidad española.
# Diseñado para GitHub Actions con:
# - secrets de GitHub;
# - historial CSV acumulado;
# - reintentos ante fallos transitorios de conexión;
# - capturas solo ante posible cita o error.

from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
import csv
import os
import random
import smtplib
import time
import traceback


# ==================================================
# CONFIGURACIÓN
# ==================================================

URL = (
    "https://sede.administracionespublicas.gob.es/"
    "icpplustiej/citar?org=JUS-RC&locale=es&appVersion=V+7.44.4"
)

PROVINCIA_VALUE = "253"              # Zaragoza
TRAMITE_GRUPO_ID = "tramiteGrupo[2]"
TRAMITE_VALUE = "4071"               # Jura de nacionalidad española

HEADLESS = True
TIMEOUT_NAVEGACION_MS = 90000
TIMEOUT_SELECTOR_MS = 30000

INTENTOS_CONEXION = 3
ESPERA_REINTENTO_MIN = 30
ESPERA_REINTENTO_MAX = 90

ENVIAR_CORREO = True
ENVIAR_CORREO_SI_NO_HAY_CITAS = False

SMTP_SERVIDOR = "smtp.gmail.com"
SMTP_PUERTO = 465


# ==================================================
# SECRETS / VARIABLES DE ENTORNO
# ==================================================

NIE = os.getenv("NIE")
NOMBRE_COMPLETO = os.getenv("NOMBRE_COMPLETO")
EMAIL_ORIGEN = os.getenv("EMAIL_ORIGEN")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

GITHUB_RUN_ID = os.getenv("GITHUB_RUN_ID", "")
GITHUB_RUN_NUMBER = os.getenv("GITHUB_RUN_NUMBER", "")
GITHUB_ACTOR = os.getenv("GITHUB_ACTOR", "")
GITHUB_SERVER_URL = os.getenv("GITHUB_SERVER_URL", "")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")


# ==================================================
# RUTAS
# ==================================================

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "monitor_citas.log"
HISTORY_FILE = BASE_DIR / "historial_consultas.csv"
SCREENSHOT_DIR = BASE_DIR / "capturas"
SCREENSHOT_DIR.mkdir(exist_ok=True)


# ==================================================
# FUNCIONES AUXILIARES
# ==================================================

def now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_file() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def validate_configuration() -> None:
    values = {
        "NIE": NIE,
        "NOMBRE_COMPLETO": NOMBRE_COMPLETO,
        "EMAIL_ORIGEN": EMAIL_ORIGEN,
        "EMAIL_DESTINO": EMAIL_DESTINO,
        "EMAIL_PASSWORD": EMAIL_PASSWORD,
    }
    missing = [name for name, value in values.items() if not value]

    if missing:
        raise RuntimeError("Faltan secrets de GitHub: " + ", ".join(missing))


def write_log(result: str, url: str = "", detail: str = "") -> None:
    line = f"{now_local()} | {result} | {url}"
    if detail:
        line += f" | {detail}"

    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(line + "\n")

    print(line)


def write_history(
    result: str,
    url: str = "",
    duration: str | float = "",
    email_sent: str = "No",
    detail: str = "",
    connection_attempts: int | str = "",
) -> None:
    exists = HISTORY_FILE.exists()

    run_url = ""
    if GITHUB_SERVER_URL and GITHUB_REPOSITORY and GITHUB_RUN_ID:
        run_url = (
            f"{GITHUB_SERVER_URL}/{GITHUB_REPOSITORY}/"
            f"actions/runs/{GITHUB_RUN_ID}"
        )

    fieldnames = [
        "fecha_hora_utc",
        "fecha_hora_runner",
        "resultado",
        "duracion_segundos",
        "intentos_conexion",
        "url",
        "correo_enviado",
        "detalle",
        "github_run_number",
        "github_run_id",
        "github_actor",
        "github_run_url",
    ]

    row = {
        "fecha_hora_utc": now_utc(),
        "fecha_hora_runner": now_local(),
        "resultado": result,
        "duracion_segundos": duration,
        "intentos_conexion": connection_attempts,
        "url": url,
        "correo_enviado": email_sent,
        "detalle": detail,
        "github_run_number": GITHUB_RUN_NUMBER,
        "github_run_id": GITHUB_RUN_ID,
        "github_actor": GITHUB_ACTOR,
        "github_run_url": run_url,
    }

    with HISTORY_FILE.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def save_screenshot(page, prefix: str):
    path = SCREENSHOT_DIR / f"{prefix}_{timestamp_file()}.png"

    try:
        page.screenshot(path=str(path), full_page=True)
        print("Captura guardada:", path)
        return path
    except Exception as error:
        print("No se pudo guardar captura:", error)
        return None


def send_email(subject: str, body: str, attachment=None) -> bool:
    if not ENVIAR_CORREO:
        return False

    try:
        message = EmailMessage()
        message["From"] = EMAIL_ORIGEN
        message["To"] = EMAIL_DESTINO
        message["Subject"] = subject
        message.set_content(body)

        if attachment is not None and Path(attachment).exists():
            attachment_path = Path(attachment)
            with attachment_path.open("rb") as file:
                content = file.read()

            message.add_attachment(
                content,
                maintype="image",
                subtype="png",
                filename=attachment_path.name,
            )

        with smtplib.SMTP_SSL(SMTP_SERVIDOR, SMTP_PUERTO) as smtp:
            smtp.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
            smtp.send_message(message)

        print("Correo enviado:", subject)
        return True

    except Exception as error:
        write_log("ERROR ENVIO CORREO", detail=str(error))
        print("No se pudo enviar el correo:", error)
        return False


def register_result(
    result: str,
    url: str = "",
    duration: str | float = "",
    email_sent: str = "No",
    detail: str = "",
    connection_attempts: int | str = "",
) -> None:
    log_detail = detail
    if duration != "":
        log_detail = f"duracion={duration}s"
        if detail:
            log_detail += f"; {detail}"

    write_log(result, url, log_detail)
    write_history(
        result=result,
        url=url,
        duration=duration,
        email_sent=email_sent,
        detail=detail,
        connection_attempts=connection_attempts,
    )


def open_form_with_retries(browser):
    """
    Abre la sede, confirma que cargó el selector de provincia,
    selecciona Zaragoza y espera el selector del trámite.

    Devuelve: (page, numero_de_intento_utilizado)
    """
    errors = []

    for attempt in range(1, INTENTOS_CONEXION + 1):
        page = browser.new_page()

        try:
            print(f"Intento de conexión {attempt}/{INTENTOS_CONEXION}")

            page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=TIMEOUT_NAVEGACION_MS,
            )

            if page.url.startswith("chrome-error://"):
                raise RuntimeError(
                    "Chromium mostró una página interna de error"
                )

            page.wait_for_selector(
                "#provincia",
                state="visible",
                timeout=TIMEOUT_SELECTOR_MS,
            )

            page.locator("#provincia").select_option(value=PROVINCIA_VALUE)

            page.wait_for_selector(
                f"select[id='{TRAMITE_GRUPO_ID}']",
                state="visible",
                timeout=TIMEOUT_SELECTOR_MS,
            )

            print(f"Conexión completada en el intento {attempt}.")
            return page, attempt

        except Exception as error:
            error_text = f"Intento {attempt}: {type(error).__name__}: {error}"
            errors.append(error_text)
            print(error_text)

            save_screenshot(page, f"error_conexion_intento_{attempt}")

            try:
                page.close()
            except Exception:
                pass

            if attempt < INTENTOS_CONEXION:
                wait_seconds = random.randint(
                    ESPERA_REINTENTO_MIN,
                    ESPERA_REINTENTO_MAX,
                )
                print(
                    f"Nuevo intento de conexión en "
                    f"{wait_seconds} segundos..."
                )
                time.sleep(wait_seconds)

    raise RuntimeError(
        "No fue posible cargar correctamente la sede después de "
        f"{INTENTOS_CONEXION} intentos.\n" + "\n".join(errors)
    )


# ==================================================
# FLUJO PRINCIPAL
# ==================================================

def run_monitor() -> None:
    start = datetime.now()
    browser = None
    page = None
    connection_attempts = 0

    validate_configuration()

    print("=" * 60)
    print("Directorio del script:", BASE_DIR)
    print("Archivo log:", LOG_FILE)
    print("Archivo historial:", HISTORY_FILE)
    print("Carpeta capturas:", SCREENSHOT_DIR)
    print("=" * 60)

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=HEADLESS)

            # PASOS 1 Y 2: CONEXIÓN, PROVINCIA Y CARGA DEL TRÁMITE
            page, connection_attempts = open_form_with_retries(browser)

            # PASO 3: SELECCIONAR JURA
            page.evaluate(
                f"""
                () => {{
                    const sel = document.getElementById(
                        "{TRAMITE_GRUPO_ID}"
                    );
                    sel.value = "{TRAMITE_VALUE}";

                    eliminarSeleccionOtrosGrupos(2);
                    cargaMensajesTramite();

                    sel.dispatchEvent(
                        new Event("change", {{ bubbles: true }})
                    );
                    sel.dispatchEvent(
                        new Event("input", {{ bubbles: true }})
                    );
                }}
                """
            )

            page.wait_for_timeout(3000)

            selected_value = page.evaluate(
                f"""
                () => document.getElementById(
                    "{TRAMITE_GRUPO_ID}"
                ).value
                """
            )

            print("Valor seleccionado en nacionalidad:", selected_value)

            if selected_value != TRAMITE_VALUE:
                raise RuntimeError(
                    "No se pudo seleccionar el trámite de Jura."
                )

            # PASO 4: ACEPTAR TRÁMITE
            page.locator("#btnAceptar").click()
            page.wait_for_timeout(10000)

            print("Después de aceptar trámite:", page.url)

            # PASO 5: ENTRAR
            enter_button = page.locator(
                "input[value='Entrar'], button:has-text('Entrar')"
            )

            if enter_button.count() == 0:
                raise RuntimeError("No se encontró el botón Entrar.")

            enter_button.first.click()
            page.wait_for_timeout(10000)

            print("Después de pulsar Entrar:", page.url)

            # PASO 6: IDENTIFICACIÓN
            page.locator("label[for='rdbTipoDocNie']").click()
            page.wait_for_timeout(1000)

            text_inputs = page.locator("input[type='text']")

            if text_inputs.count() < 2:
                raise RuntimeError(
                    "No se encontraron los dos campos de identificación."
                )

            text_inputs.nth(0).fill(NIE)
            text_inputs.nth(1).fill(NOMBRE_COMPLETO)

            with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=30000,
            ):
                page.locator("input[value='Aceptar']").first.click()

            page.wait_for_timeout(5000)

            print("Después de aceptar identificación:", page.url)

            # PASO 7: SOLICITAR CITA
            request_button = page.locator("#btnEnviar")

            if request_button.count() == 0:
                raise RuntimeError(
                    "No se encontró el botón Solicitar Cita."
                )

            page.evaluate("enviar('solicitud')")
            page.wait_for_timeout(5000)

            page_text = page.inner_text("body")
            duration = round(
                (datetime.now() - start).total_seconds(),
                1,
            )

            print("Después de solicitar cita:", page.url)
            print(page_text[:5000])

            if "no hay citas disponibles" in page_text.lower():
                result = "NO HAY CITAS DISPONIBLES"
                email_ok = False

                if ENVIAR_CORREO_SI_NO_HAY_CITAS:
                    email_ok = send_email(
                        "Monitor jura: no hay citas",
                        (
                            f"Resultado: {result}\n"
                            f"Fecha y hora: {now_local()}\n"
                            f"Duración: {duration}s\n"
                            f"URL: {page.url}"
                        ),
                    )

                register_result(
                    result=result,
                    url=page.url,
                    duration=duration,
                    email_sent="Si" if email_ok else "No",
                    connection_attempts=connection_attempts,
                )

            else:
                result = "POSIBLE CITA DISPONIBLE"
                screenshot = save_screenshot(page, "posible_cita")

                email_ok = send_email(
                    "URGENTE: posible cita disponible para jura",
                    (
                        f"Resultado: {result}\n"
                        f"Fecha y hora: {now_local()}\n"
                        f"Duración: {duration}s\n"
                        f"URL: {page.url}\n\n"
                        f"Texto detectado:\n{page_text[:5000]}"
                    ),
                    screenshot,
                )

                register_result(
                    result=result,
                    url=page.url,
                    duration=duration,
                    email_sent="Si" if email_ok else "No",
                    connection_attempts=connection_attempts,
                )

        except Exception as error:
            duration = round(
                (datetime.now() - start).total_seconds(),
                1,
            )
            error_trace = traceback.format_exc()

            current_url = ""
            if page is not None:
                try:
                    current_url = page.url
                except Exception:
                    pass

            if connection_attempts == 0:
                result = "ERROR DE CONEXION"
            else:
                result = "ERROR GENERAL"

            screenshot = None
            if page is not None:
                screenshot = save_screenshot(page, "error_final")

            email_ok = send_email(
                f"{result}: monitor cita jura",
                (
                    f"Resultado: {result}\n"
                    f"Fecha y hora: {now_local()}\n"
                    f"URL: {current_url}\n"
                    f"Intentos de conexión: "
                    f"{connection_attempts or INTENTOS_CONEXION}\n\n"
                    f"Error:\n{error_trace}"
                ),
                screenshot,
            )

            register_result(
                result=result,
                url=current_url,
                duration=duration,
                email_sent="Si" if email_ok else "No",
                detail=str(error).replace("\n", " | "),
                connection_attempts=(
                    connection_attempts or INTENTOS_CONEXION
                ),
            )

            print(error_trace)

        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


if __name__ == "__main__":
    run_monitor()
