import time

from arduino.app_utils import *
from arduino.app_bricks.web_ui import WebUI

from camera import Camera

DEFAULT_EXPOSURE = 2200 
DEFAULT_ANALOGUE_GAIN = 98

ui = WebUI()
camera = Camera()

def attendre_camera():
    for _ in range(180):

        try:
            status = camera.status()

            if status.get("ok"):
                return True

        except Exception:
            pass

        time.sleep(1)

    return False

 
def envoyer_reglages_initiaux(
    _sid,
    _data
):
    try:
        result = camera.set_controls(
            DEFAULT_EXPOSURE,
            DEFAULT_ANALOGUE_GAIN
        )

        ui.send_message(
            "camera_defaults",
            {
                "exposure":
                    result["exposure"],

                "analogue_gain":
                    result["analogue_gain"]
            }
        )

        print(
            f">>> Caméra et WebUI synchronisées : "
            f"exposure={result['exposure']}, "
            f"gain={result['analogue_gain']}",
            flush=True
        )

    except Exception as e:
        print(
            ">>> ERREUR synchronisation :",
            e,
            flush=True
        )

 
def initialiser_camera():

    print(
        ">>> Attente du service caméra...",
        flush=True
    )

    if not attendre_camera():
        raise RuntimeError(
            "Le service caméra "
            "n'est pas devenu disponible."
        )

    camera.set_controls(
        DEFAULT_EXPOSURE,
        DEFAULT_ANALOGUE_GAIN
    )

    print(
        f">>> Réglages caméra initiaux : "
        f"exposure={DEFAULT_EXPOSURE}, "
        f"gain={DEFAULT_ANALOGUE_GAIN}",
        flush=True
    )

    


def regler_camera(
    _sid,
    data
):
    print(
        ">>> Réglage caméra reçu :",
        data
    )

    try:
        exposure = int(
            data.get(
                "exposure",
                DEFAULT_EXPOSURE
            )
        )

        analogue_gain = int(
            data.get(
                "analogue_gain",
                DEFAULT_ANALOGUE_GAIN
            )
        )

        result = (
            camera.set_controls(
                exposure,
                analogue_gain
            )
        )

        ui.send_message(
            "camera_settings_update",
            result
        )

        print(
            ">>> Réglages appliqués"
        )

    except Exception as e:

        print(
            ">>> ERREUR réglages :",
            e
        )

        ui.send_message(
            "camera_settings_update",
            {
                "ok": False,
                "error": str(e)
            }
        )


def prendre_photo(
    _sid,
    _data
):
    print(
        ">>> Demande de photo reçue"
    )

    try:
        if not attendre_camera():

            raise RuntimeError(
                "Le service caméra "
                "n'est pas devenu disponible."
            )

        result = (
            camera.capture()
        )

        if not result.get("ok"):

            raise RuntimeError(
                result.get(
                    "error",
                    "Erreur inconnue "
                    "de la caméra"
                )
            )

        ui.send_message(
            "photo_update",
            {
                "ok": True,
                "image": result["image"]
            }
        )

        print(
            ">>> Photo envoyée "
            "à la WebUI"
        )

    except Exception as e:

        print(
            ">>> ERREUR photo :",
            e
        )

        ui.send_message(
            "photo_update",
            {
                "ok": False,
                "erreur": str(e)
            }
        )


def prendre_photo_auto(_sid, _data):
    try:
        result = camera.capture_auto()
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Erreur exposition automatique"))
        ui.send_message("photo_update", {
            "ok": True,
            "image": result["image"],
            "settings": result["settings"],
            "statistics": result["statistics"],
            "history": result["history"],
        })
    except Exception as e:
        print(">>> ERREUR photo automatique :", e, flush=True)
        ui.send_message("photo_update", {"ok": False, "erreur": str(e)})



ui.on_message(
    "regler_camera",
    regler_camera
)

ui.on_message(
    "prendre_photo",
    prendre_photo
)

ui.on_message("prendre_photo_auto", prendre_photo_auto)

ui.on_message(
    "get_camera_defaults",
    envoyer_reglages_initiaux
)


initialiser_camera()

App.run()
