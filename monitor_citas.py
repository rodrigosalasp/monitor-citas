from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
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

URL = (
    "https://sede.administracionespublicas.gob.es/"
    "icpplustiej/citar?org=JUS-RC&locale=es&appVersion=V+7.44.4"
)
PROVINCIA_VALUE = "253"
TRAMITE_GRUPO_ID = "tramiteGrupo[2]"
TRAMITE_VALUE = "4071"
HEADLESS = True
TIMEOUT_NAVEGACION_MS = 90_000
TIMEOUT_SELECTOR_MS = 30_000
TIMEOUT_NAVEGACION_INTERNA_MS = 30_000
INTENTOS_CONEXION = 3
ESPERA_REINTENTO_MIN_SEG = 30
ESPERA_REINTENTO_MAX_SEG = 90
ENVIAR_CORREO = True
ENVIAR_CORREO_SI_NO_HAY_CITAS = False
SMTP_SERVIDOR = "smtp.gmail.com"
SMTP_PUERTO = 465

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

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "monitor_citas.log"
HISTORY_FILE = BASE_DIR / "historial_consultas.csv"
SCREENSHOT_DIR = BASE_DIR / "capturas"
SCREENSHOT_DIR.mkdir(exist_ok=True)

HISTORY_FIELDS = [
    "fecha_hora_utc",
    "fecha_hora_runner",
    "resultado",
    "fase",
    "tipo_error",
    "duracion_segundos",
    "intentos_conexion",
    "duraciones_intentos_segundos",
    "url",
    "correo_enviado",
    "detalle",
    "github_run_number",
    "github_run_id",
    "github_actor",
    "github_run_url",
]


def now_runner() -> str:
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
        raise RuntimeError("Faltan repository secrets: " + ", ".join(missing))


def github_run_url() -> str:
    if GITHUB_SERVER_URL and GITHUB_REPOSITORY and GITHUB_RUN_ID:
        return f"{GITHUB_SERVER_URL}/{GITHUB_REPOSITORY}/actions/runs/{GITHUB_RUN_ID}"
    return ""


def compact_text(value, limit: int = 8000) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " | ")
    while "  " in text:
        text = text.replace("  ", " ")
    return text[:limit]


def write_log(result: str, url: str = "", detail: str = "") -> None:
    line = f"{now_runner()} | {result} | {url}"
    if detail:
        line += f" | {detail}"
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(line + "\n")
    print(line)


def ensure_history_schema() -> None:
    if not HISTORY_FILE.exists() or HISTORY_FILE.stat().st_size == 0:
        return
    with HISTORY_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        current_fields = reader.fieldnames or []
        rows = list(reader)
    if current_fields == HISTORY_FIELDS:
        return
    temporary = HISTORY_FILE.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for old_row in rows:
            writer.writerow({field: old_row.get(field, "") for field in HISTORY_FIELDS})
    temporary.replace(HISTORY_FILE)
    print("Historial migrado al nuevo esquema.")


def write_history(
    *, result: str, phase: str, error_type: str = "", url: str = "",
    duration="", connection_attempts="", attempt_durations=None,
    email_sent: str = "No", detail: str = ""
) -> None:
    ensure_history_schema()
    exists = HISTORY_FILE.exists() and HISTORY_FILE.stat().st_size > 0
    durations_text = ""
    if attempt_durations:
        durations_text = ";".join(f"{value:.1f}" for value in attempt_durations)
    row = {
        "fecha_hora_utc": now_utc(),
        "fecha_hora_runner": now_runner(),
        "resultado": result,
        "fase": phase,
        "tipo_error": error_type,
        "duracion_segundos": duration,
        "intentos_conexion": connection_attempts,
        "duraciones_intentos_segundos": durations_text,
        "url": url,
        "correo_enviado": email_sent,
        "detalle": compact_text(detail),
        "github_run_number": GITHUB_RUN_NUMBER,
        "github_run_id": GITHUB_RUN_ID,
        "github_actor": GITHUB_ACTOR,
        "github_run_url": github_run_url(),
    }
    with HISTORY_FILE.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HISTORY_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def register_result(**kwargs) -> None:
    parts = []
    if kwargs.get("phase"):
        parts.append(f"fase={kwargs['phase']}")
    if kwargs.get("error_type"):
        parts.append(f"tipo_error={kwargs['error_type']}")
    if kwargs.get("duration") != "":
        parts.append(f"duracion={kwargs.get('duration')}s")
    if kwargs.get("connection_attempts") != "":
        parts.append(f"intentos_conexion={kwargs.get('connection_attempts')}")
    if kwargs.get("attempt_durations"):
        parts.append(
            "duraciones_intentos=" + ";".join(
                f"{x:.1f}" for x in kwargs["attempt_durations"]
            )
        )
    if kwargs.get("detail"):
        parts.append(compact_text(kwargs["detail"], 1500))
    write_log(kwargs["result"], kwargs.get("url", ""), "; ".join(parts))
    write_history(**kwargs)


def classify_error(error: BaseException, phase: str) -> str:
    text = f"{type(error).__name__}: {error}".upper()
    if "ERR_CONNECTION_RESET" in text:
        return "ERR_CONNECTION_RESET"
    if "ERR_NAME_NOT_RESOLVED" in text:
        return "ERR_NAME_NOT_RESOLVED"
    if "ERR_TIMED_OUT" in text:
        return "ERR_TIMED_OUT"
    if "ERR_CONNECTION_REFUSED" in text:
        return "ERR_CONNECTION_REFUSED"
    if "CHROME-ERROR://" in text or "PÁGINA INTERNA DE ERROR" in text:
        return "CHROME_ERROR_PAGE"
    if isinstance(error, PlaywrightTimeoutError):
        if phase == "ABRIR_WEB":
            return "TIMEOUT_GOTO"
        return "TIMEOUT_SELECTOR"
    if isinstance(error, PlaywrightError):
        return "PLAYWRIGHT_ERROR"
    if isinstance(error, RuntimeError):
        return "RUNTIME_ERROR"
    return "UNKNOWN_ERROR"


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
            path = Path(attachment)
            with path.open("rb") as file:
                content = file.read()
            message.add_attachment(content, maintype="image", subtype="png", filename=path.name)
        with smtplib.SMTP_SSL(SMTP_SERVIDOR, SMTP_PUERTO) as smtp:
            smtp.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
            smtp.send_message(message)
        print("Correo enviado:", subject)
        return True
    except Exception as error:
        write_log("ERROR ENVIO CORREO", detail=compact_text(error))
        return False


def open_form_with_retries(browser):
    attempt_durations = []
    diagnoses = []
    for attempt in range(1, INTENTOS_CONEXION + 1):
        page = browser.new_page()
        started = time.monotonic()
        phase = "ABRIR_WEB"
        try:
            print(f"Intento de conexión {attempt}/{INTENTOS_CONEXION}")
            page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT_NAVEGACION_MS)
            if page.url.startswith("chrome-error://"):
                raise RuntimeError("Chromium mostró una página interna de error")
            phase = "CARGAR_PROVINCIA"
            page.wait_for_selector("#provincia", state="visible", timeout=TIMEOUT_SELECTOR_MS)
            page.locator("#provincia").select_option(value=PROVINCIA_VALUE)
            phase = "CARGAR_TRAMITE"
            page.wait_for_selector(
                f"select[id='{TRAMITE_GRUPO_ID}']",
                state="visible",
                timeout=TIMEOUT_SELECTOR_MS,
            )
            elapsed = round(time.monotonic() - started, 1)
            attempt_durations.append(elapsed)
            return page, attempt, attempt_durations, diagnoses
        except Exception as error:
            elapsed = round(time.monotonic() - started, 1)
            attempt_durations.append(elapsed)
            error_type = classify_error(error, phase)
            diagnosis = (
                f"Intento {attempt}; fase={phase}; tipo_error={error_type}; "
                f"duracion={elapsed}s; {type(error).__name__}: {error}"
            )
            diagnoses.append(diagnosis)
            print(compact_text(diagnosis, 4000))
            save_screenshot(page, f"error_conexion_{attempt}_{phase.lower()}")
            try:
                page.close()
            except Exception:
                pass
            if attempt < INTENTOS_CONEXION:
                wait_seconds = random.randint(
                    ESPERA_REINTENTO_MIN_SEG,
                    ESPERA_REINTENTO_MAX_SEG,
                )
                time.sleep(wait_seconds)
    final_error = RuntimeError(
        "No fue posible cargar correctamente la sede después de 3 intentos. | "
        + " || ".join(compact_text(x) for x in diagnoses)
    )
    final_error.attempt_durations = attempt_durations
    final_error.diagnoses = diagnoses
    raise final_error


def run_monitor() -> None:
    start = time.monotonic()
    browser = None
    page = None
    current_phase = "INICIALIZACION"
    connection_attempts = 0
    attempt_durations = []
    validate_configuration()
    ensure_history_schema()

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=HEADLESS)
            current_phase = "ABRIR_WEB"
            page, connection_attempts, attempt_durations, _ = open_form_with_retries(browser)

            current_phase = "SELECCIONAR_TRAMITE"
            page.evaluate(
                f"""
                () => {{
                    const sel = document.getElementById("{TRAMITE_GRUPO_ID}");
                    if (!sel) throw new Error("No existe el selector del trámite");
                    sel.value = "{TRAMITE_VALUE}";
                    eliminarSeleccionOtrosGrupos(2);
                    cargaMensajesTramite();
                    sel.dispatchEvent(new Event("change", {{ bubbles: true }}));
                    sel.dispatchEvent(new Event("input", {{ bubbles: true }}));
                }}
                """
            )
            page.wait_for_timeout(3000)
            selected_value = page.evaluate(
                f"() => document.getElementById('{TRAMITE_GRUPO_ID}').value"
            )
            if selected_value != TRAMITE_VALUE:
                raise RuntimeError("No se pudo seleccionar el trámite de Jura.")

            current_phase = "ACEPTAR_TRAMITE"
            page.locator("#btnAceptar").click()
            page.wait_for_timeout(10_000)

            current_phase = "ENTRAR"
            enter_button = page.locator("input[value='Entrar'], button:has-text('Entrar')")
            if enter_button.count() == 0:
                raise RuntimeError("No se encontró el botón Entrar.")
            enter_button.first.click()
            page.wait_for_timeout(10_000)

            current_phase = "IDENTIFICACION"
            page.locator("label[for='rdbTipoDocNie']").click()
            page.wait_for_timeout(1000)
            text_inputs = page.locator("input[type='text']")
            if text_inputs.count() < 2:
                raise RuntimeError("No se encontraron los dos campos de identificación.")
            text_inputs.nth(0).fill(NIE)
            text_inputs.nth(1).fill(NOMBRE_COMPLETO)
            with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=TIMEOUT_NAVEGACION_INTERNA_MS,
            ):
                page.locator("input[value='Aceptar']").first.click()
            page.wait_for_timeout(5000)

            current_phase = "SOLICITAR_CITA"
            if page.locator("#btnEnviar").count() == 0:
                raise RuntimeError("No se encontró el botón Solicitar Cita.")
            page.evaluate("enviar('solicitud')")
            page.wait_for_timeout(5000)

            current_phase = "LEER_RESULTADO"
            page_text = page.inner_text("body")
            duration = round(time.monotonic() - start, 1)

            if "no hay citas disponibles" in page_text.lower():
                email_ok = False
                if ENVIAR_CORREO_SI_NO_HAY_CITAS:
                    email_ok = send_email(
                        "Monitor jura: no hay citas",
                        f"Resultado: NO HAY CITAS DISPONIBLES\nFecha: {now_runner()}\nURL: {page.url}",
                    )
                register_result(
                    result="NO HAY CITAS DISPONIBLES",
                    phase="RESULTADO",
                    url=page.url,
                    duration=duration,
                    connection_attempts=connection_attempts,
                    attempt_durations=attempt_durations,
                    email_sent="Si" if email_ok else "No",
                )
            else:
                screenshot = save_screenshot(page, "posible_cita")
                email_ok = send_email(
                    "URGENTE: posible cita disponible para jura",
                    (
                        f"Resultado: POSIBLE CITA DISPONIBLE\nFecha: {now_runner()}\n"
                        f"URL: {page.url}\n\nTexto detectado:\n{page_text[:5000]}"
                    ),
                    screenshot,
                )
                register_result(
                    result="POSIBLE CITA DISPONIBLE",
                    phase="RESULTADO",
                    url=page.url,
                    duration=duration,
                    connection_attempts=connection_attempts,
                    attempt_durations=attempt_durations,
                    email_sent="Si" if email_ok else "No",
                    detail=page_text[:3000],
                )

        except Exception as error:
            duration = round(time.monotonic() - start, 1)
            if hasattr(error, "attempt_durations"):
                attempt_durations = list(error.attempt_durations)
            current_url = ""
            if page is not None:
                try:
                    current_url = page.url
                except Exception:
                    pass
            result = "ERROR DE CONEXION" if connection_attempts == 0 else "ERROR GENERAL"
            error_type = classify_error(error, current_phase)
            screenshot = None
            if page is not None:
                screenshot = save_screenshot(page, f"error_final_{current_phase.lower()}")
            displayed_attempts = connection_attempts or INTENTOS_CONEXION
            email_ok = send_email(
                f"{result}: monitor cita jura",
                (
                    f"Resultado: {result}\nFecha: {now_runner()}\nFase: {current_phase}\n"
                    f"Tipo de error: {error_type}\nURL: {current_url}\n"
                    f"Duración total: {duration}s\nIntentos: {displayed_attempts}\n"
                    f"Duraciones: {attempt_durations}\n\n{traceback.format_exc()}"
                ),
                screenshot,
            )
            register_result(
                result=result,
                phase=current_phase,
                error_type=error_type,
                url=current_url,
                duration=duration,
                connection_attempts=displayed_attempts,
                attempt_durations=attempt_durations,
                email_sent="Si" if email_ok else "No",
                detail=str(error),
            )
            print(traceback.format_exc())
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


if __name__ == "__main__":
    run_monitor()
