# monitor_citas.py
# Monitor automatico de citas para jura de nacionalidad espanola.
# Ejecuta desde GitHub Actions usando repository secrets.

from playwright.sync_api import sync_playwright
from datetime import datetime
from pathlib import Path
from email.message import EmailMessage
import os
import smtplib
import traceback

URL = "https://sede.administracionespublicas.gob.es/icpplustiej/citar?org=JUS-RC&locale=es&appVersion=V+7.44.4"

PROVINCIA_VALUE = "253"
TRAMITE_GRUPO_ID = "tramiteGrupo[2]"
TRAMITE_VALUE = "4071"

HEADLESS = True
SLOW_MO = 0
TIMEOUT_GENERAL = 90000

ENVIAR_CORREO = True
ENVIAR_CORREO_SI_NO_HAY_CITAS = False

SMTP_SERVIDOR = "smtp.gmail.com"
SMTP_PUERTO = 465

ESPERA_INICIAL_MS = 5000
ESPERA_DESPUES_PROVINCIA_MS = 5000
ESPERA_DESPUES_TRAMITE_MS = 3000
ESPERA_DESPUES_ENTRAR_MS = 5000
ESPERA_DESPUES_IDENTIFICACION_MS = 5000
ESPERA_DESPUES_SOLICITAR_MS = 5000

NIE = os.getenv("NIE")
NOMBRE_COMPLETO = os.getenv("NOMBRE_COMPLETO")
EMAIL_ORIGEN = os.getenv("EMAIL_ORIGEN")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

CARPETA_SCRIPT = Path(__file__).resolve().parent
ARCHIVO_LOG = CARPETA_SCRIPT / "monitor_citas.log"
CARPETA_CAPTURAS = CARPETA_SCRIPT / "capturas"
CARPETA_CAPTURAS.mkdir(exist_ok=True)


def ahora_texto():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ahora_archivo():
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def validar_configuracion():
    faltantes = []
    for nombre, valor in {
        "NIE": NIE,
        "NOMBRE_COMPLETO": NOMBRE_COMPLETO,
        "EMAIL_ORIGEN": EMAIL_ORIGEN,
        "EMAIL_DESTINO": EMAIL_DESTINO,
        "EMAIL_PASSWORD": EMAIL_PASSWORD,
    }.items():
        if not valor:
            faltantes.append(nombre)

    if faltantes:
        raise RuntimeError("Faltan secrets: " + ", ".join(faltantes))


def escribir_log(resultado, url="", detalle=""):
    linea = f"{ahora_texto()} | {resultado} | {url}"
    if detalle:
        linea += f" | {detalle}"

    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        f.write(linea + "\n")

    print(linea)


def enviar_correo(asunto, cuerpo, adjunto=None):
    if not ENVIAR_CORREO:
        return

    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_ORIGEN
        msg["To"] = EMAIL_DESTINO
        msg["Subject"] = asunto
        msg.set_content(cuerpo)

        if adjunto is not None and Path(adjunto).exists():
            ruta = Path(adjunto)
            with open(ruta, "rb") as f:
                contenido = f.read()

            msg.add_attachment(
                contenido,
                maintype="image",
                subtype="png",
                filename=ruta.name,
            )

        with smtplib.SMTP_SSL(SMTP_SERVIDOR, SMTP_PUERTO) as smtp:
            smtp.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
            smtp.send_message(msg)

        print("Correo enviado:", asunto)

    except Exception as e:
        escribir_log("ERROR ENVIO CORREO", "", str(e))
        print("No se pudo enviar correo:", e)


def guardar_captura(page, prefijo):
    ruta = CARPETA_CAPTURAS / f"{prefijo}_{ahora_archivo()}.png"
    try:
        page.screenshot(path=str(ruta), full_page=True)
        print("Captura guardada:", ruta)
        return ruta
    except Exception as e:
        print("No se pudo guardar captura:", e)
        return None


def imprimir_contexto():
    print("=" * 60)
    print("Directorio de trabajo:", Path.cwd())
    print("Ruta del script:", Path(__file__).resolve())
    print("Archivo log:", ARCHIVO_LOG)
    print("Carpeta capturas:", CARPETA_CAPTURAS)
    print("=" * 60)


def ejecutar_monitor():
    inicio = datetime.now()
    browser = None

    imprimir_contexto()
    validar_configuracion()

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
            page = browser.new_page()

            page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT_GENERAL)
            page.wait_for_timeout(ESPERA_INICIAL_MS)

            # PASO 1: SELECCIONAR ZARAGOZA
            page.locator("#provincia").select_option(value=PROVINCIA_VALUE)
            page.wait_for_timeout(ESPERA_DESPUES_PROVINCIA_MS)

            # PASO 2: SELECCIONAR JURA DE NACIONALIDAD
            page.wait_for_selector(f"select[id='{TRAMITE_GRUPO_ID}']", timeout=30000)

            page.evaluate(
                f"""
                () => {{
                    const sel = document.getElementById("{TRAMITE_GRUPO_ID}");
                    sel.value = "{TRAMITE_VALUE}";

                    eliminarSeleccionOtrosGrupos(2);
                    cargaMensajesTramite();

                    sel.dispatchEvent(new Event("change", {{ bubbles: true }}));
                    sel.dispatchEvent(new Event("input", {{ bubbles: true }}));
                }}
                """
            )

            page.wait_for_timeout(ESPERA_DESPUES_TRAMITE_MS)

            valor = page.evaluate(
                f"""() => document.getElementById("{TRAMITE_GRUPO_ID}").value"""
            )

            print("Valor seleccionado en nacionalidad:", valor)

            if valor != TRAMITE_VALUE:
                resultado = "ERROR: No se pudo seleccionar Jura"
                escribir_log(resultado, page.url)
                captura = guardar_captura(page, "error_tramite")
                enviar_correo("Error monitor cita jura", f"{resultado}\n\nURL: {page.url}", captura)
                return

            # PASO 3: ACEPTAR TRAMITE
            page.locator("#btnAceptar").click()
            page.wait_for_timeout(10000)

            print("Despues de aceptar tramite:")
            print("URL:", page.url)

            # PASO 4: PULSAR ENTRAR
            boton_entrar = page.locator("input[value='Entrar'], button:has-text('Entrar')")

            if boton_entrar.count() > 0:
                print("Boton Entrar encontrado. Pulsando...")
                boton_entrar.first.click()
                page.wait_for_timeout(10000)
            else:
                resultado = "ERROR: No se encontro boton Entrar"
                texto = page.inner_text("body")[:5000]
                escribir_log(resultado, page.url)
                captura = guardar_captura(page, "error_entrar")
                enviar_correo("Error monitor cita jura", f"{resultado}\n\nURL: {page.url}\n\nTexto:\n{texto}", captura)
                return

            print("Despues de pulsar Entrar:")
            print("URL:", page.url)

            # PASO 5: IDENTIFICACION
            page.wait_for_timeout(ESPERA_DESPUES_ENTRAR_MS)

            try:
                page.locator("label[for='rdbTipoDocNie']").click()
                page.wait_for_timeout(1000)
                print("N.I.E. seleccionado.")
            except Exception as e:
                print("No se pudo seleccionar N.I.E.")
                print(e)

            inputs_texto = page.locator("input[type='text']")
            print("Campos de texto encontrados:", inputs_texto.count())

            inputs_texto.nth(0).fill(NIE)
            page.wait_for_timeout(1000)

            inputs_texto.nth(1).fill(NOMBRE_COMPLETO)
            page.wait_for_timeout(1000)

            print("Datos de identificacion introducidos.")

            # PASO 6: ACEPTAR IDENTIFICACION
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                page.locator("input[value='Aceptar']").first.click()

            page.wait_for_timeout(ESPERA_DESPUES_IDENTIFICACION_MS)

            print("Despues de aceptar identificacion:")
            print("URL:", page.url)
            print(page.inner_text("body")[:5000])

            # PASO 7: SOLICITAR CITA
            page.wait_for_timeout(3000)

            print("Buscando boton Solicitar Cita...")

            n_botones = page.locator("#btnEnviar").count()
            print("Botones encontrados:", n_botones)

            if n_botones == 0:
                resultado = "ERROR: No se encontro el boton Solicitar Cita"
                texto = page.inner_text("body")[:5000]
                escribir_log(resultado, page.url)
                captura = guardar_captura(page, "error_solicitar")
                enviar_correo("Error monitor cita jura", f"{resultado}\n\nURL: {page.url}\n\nTexto:\n{texto}", captura)
                return

            page.evaluate("enviar('solicitud')")

            page.wait_for_timeout(ESPERA_DESPUES_SOLICITAR_MS)

            print("Despues de solicitar cita:")
            print("URL:", page.url)

            texto = page.inner_text("body")
            print(texto[:5000])

            duracion = round((datetime.now() - inicio).total_seconds(), 1)

            if "no hay citas disponibles" in texto.lower():
                resultado = "NO HAY CITAS DISPONIBLES"
                escribir_log(resultado, page.url, f"duracion={duracion}s")

                print("\n========================================")
                print("RESULTADO:", resultado)
                print("========================================")

                if ENVIAR_CORREO_SI_NO_HAY_CITAS:
                    enviar_correo(
                        "Monitor jura: no hay citas",
                        f"Resultado: {resultado}\nFecha y hora: {ahora_texto()}\nDuracion: {duracion}s\nURL: {page.url}\n\nTexto detectado:\n{texto[:5000]}",
                    )
            else:
                resultado = "POSIBLE CITA DISPONIBLE"
                escribir_log(resultado, page.url, f"duracion={duracion}s")
                captura = guardar_captura(page, "posible_cita")

                print("\n========================================")
                print("POSIBLE CITA DISPONIBLE")
                print("Revisar la pantalla.")
                print("========================================")

                enviar_correo(
                    "URGENTE: posible cita disponible para jura",
                    f"Resultado: {resultado}\nFecha y hora: {ahora_texto()}\nDuracion: {duracion}s\nURL: {page.url}\n\nTexto detectado:\n{texto[:5000]}",
                    captura,
                )

        except Exception as e:
            resultado = "ERROR GENERAL"
            detalle_error = traceback.format_exc()
            url_actual = ""

            try:
                url_actual = page.url
            except Exception:
                url_actual = ""

            escribir_log(resultado, url_actual, str(e))

            captura = None
            try:
                captura = guardar_captura(page, "error_general")
            except Exception:
                pass

            enviar_correo(
                "Error general monitor cita jura",
                f"Resultado: {resultado}\nFecha y hora: {ahora_texto()}\nURL: {url_actual}\n\nError:\n{detalle_error}",
                captura,
            )

            print(detalle_error)

        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


if __name__ == "__main__":
    ejecutar_monitor()
