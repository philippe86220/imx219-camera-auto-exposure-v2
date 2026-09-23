import base64
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


HOST = "0.0.0.0"
PORT = 9000

WIDTH = 3280
HEIGHT = 2464

RAW_FILE = Path("/tmp/image.raw")
JPG_FILE = Path("/tmp/image.jpg")
camera_lock = threading.Lock()
current_controls = {"exposure": None, "analogue_gain": None}

# Valeur provisoire pour le RAW 8 bits : à vérifier sur des captures
# dans le noir avant de considérer la luminosité comme calibrée.
RAW_BLACK_LEVEL = 16
TARGET_GREEN = 0.35


def run(command):
    subprocess.run(
        command,
        shell=True,
        check=True
    )


def configure_pipeline():
    pipeline = [
        '"msm_csiphy0":0',
        '"msm_csiphy0":1',
        '"msm_csid0":0',
        '"msm_csid0":1',
        '"msm_vfe0_rdi0":0',
        '"msm_vfe0_rdi0":1',
    ]

    for element in pipeline:
        run(
            f"media-ctl -d /dev/media0 "
            f"-V '{element} [fmt:SRGGB8_1X8/{WIDTH}x{HEIGHT}]'"
        )


def set_sensor_controls(
    exposure=None,
    analogue_gain=None
):
    controls = []

    applied_exposure = None
    applied_analogue_gain = None

    if exposure is not None:
        applied_exposure = int(exposure)

        if applied_exposure < 4:
            applied_exposure = 4

        if applied_exposure > 3522:
            applied_exposure = 3522

        controls.append(
            f"exposure={applied_exposure}"
        )

    if analogue_gain is not None:
        applied_analogue_gain = int(
            analogue_gain
        )

        if applied_analogue_gain < 0:
            applied_analogue_gain = 0

        if applied_analogue_gain > 232:
            applied_analogue_gain = 232

        controls.append(
            f"analogue_gain="
            f"{applied_analogue_gain}"
        )

    if controls:
        run(
            "v4l2-ctl -d /dev/v4l-subdev12 "
            f"--set-ctrl={','.join(controls)}"
        )

    if applied_exposure is not None:
        current_controls["exposure"] = applied_exposure
    if applied_analogue_gain is not None:
        current_controls["analogue_gain"] = applied_analogue_gain

    return {
        "exposure": applied_exposure,
        "analogue_gain": applied_analogue_gain
    }


def capture_raw():
    RAW_FILE.unlink(
        missing_ok=True
    )

    run(
        "v4l2-ctl -d /dev/video0 "
        f"--set-fmt-video="
        f"width={WIDTH},"
        f"height={HEIGHT},"
        f"pixelformat=RGGB"
    )

    run(
        "v4l2-ctl -d /dev/video0 "
        "--stream-mmap=4 "
        "--stream-count=1 "
        f"--stream-to={RAW_FILE}"
    )

    expected = WIDTH * HEIGHT
    actual = RAW_FILE.stat().st_size

    if actual != expected:
        raise RuntimeError(
            f"Taille RAW incorrecte : "
            f"{actual}, attendu {expected}"
        )


def raw_statistics():
    # Un pixel vert sur quatre, échantillonné pour limiter la mémoire.
    raw = np.memmap(RAW_FILE, dtype=np.uint8, mode="r",
                    shape=(HEIGHT, WIDTH))
    green = raw[0::8, 1::8].astype(np.float32)
    corrected = np.maximum(green - RAW_BLACK_LEVEL, 0) / (255 - RAW_BLACK_LEVEL)
    # Zone centrale : priorité au sujet, plutôt qu'aux murs sombres.
    h, w = corrected.shape
    center = corrected[h // 5:4 * h // 5, w // 3:2 * w // 3]
    return {
        "black_level": RAW_BLACK_LEVEL,
        "median_green": float(np.median(corrected)),
        "p99_green": float(np.percentile(corrected, 99)),
        "center_median": float(np.median(center)),
        "center_p95": float(np.percentile(center, 95)),
    }


def gain_multiplier(register):
    return 256.0 / (256 - register)


def gain_register(multiplier):
    return max(0, min(232, round(256 - 256 / multiplier)))


def capture_auto():
    if any(value is None for value in current_controls.values()):
        raise RuntimeError("Réglages initiaux de la caméra indisponibles")

    configure_pipeline()
    history = []
    for attempt in range(6):
        capture_raw()
        stats = raw_statistics()
        history.append({**current_controls, **stats})
        median = stats["center_median"]
        highlight = stats["center_p95"]
        # Les valeurs saturées ne révèlent pas de combien elles dépassent
        # la limite : réduire franchement jusqu'à voir du détail revenir.
        if highlight >= 0.98:
            factor = 0.5
        elif highlight > 0.85:
            factor = min(1.0, 0.80 / highlight)
        elif median < 0.01:
            factor = 2.0
        else:
            factor = TARGET_GREEN / median

        if (0.90 <= factor <= 1.10 and highlight <= 0.85) or attempt == 5:
            break
        factor = max(0.5, min(2.0, factor))
        exposure = current_controls["exposure"]
        gain = current_controls["analogue_gain"]
        if factor < 1.0:
            # Quand la scène est trop claire, supprimer d'abord le gain
            # pour limiter le bruit, puis réduire l'exposition si nécessaire.
            next_gain = gain_register(max(1.0, gain_multiplier(gain) * factor))
            remaining = factor * gain_multiplier(gain) / gain_multiplier(next_gain)
            next_exposure = max(4, min(3522, round(exposure * remaining)))
        else:
            next_exposure = max(4, min(3522, round(exposure * factor)))
            remaining = factor * exposure / next_exposure
            next_gain = gain_register(gain_multiplier(gain) * remaining)

        if next_exposure == exposure and next_gain == gain:
            break
        set_sensor_controls(next_exposure, next_gain)

    # Le dernier RAW correspond exactement aux statistiques et réglages renvoyés.
    raw_to_jpeg()
    with open(JPG_FILE, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("utf-8")
    return {"image": encoded, "settings": dict(current_controls),
            "statistics": history[-1], "history": history}


def raw_to_jpeg():
    raw = np.fromfile(
        RAW_FILE,
        dtype=np.uint8
    ).reshape(
        (HEIGHT, WIDTH)
    ).astype(
        np.float32
    )

    # Ajout d'une bordure pour éviter les effets
    # de bord pendant l'interpolation.
    p = np.pad(
        raw,
        1,
        mode="edge"
    )

    up = p[0:-2, 1:-1]
    down = p[2:, 1:-1]
    left = p[1:-1, 0:-2]
    right = p[1:-1, 2:]

    ul = p[0:-2, 0:-2]
    ur = p[0:-2, 2:]
    dl = p[2:, 0:-2]
    dr = p[2:, 2:]

    r = np.zeros_like(raw)
    g = np.zeros_like(raw)
    b = np.zeros_like(raw)

    # Bayer RGGB
    #
    # R G R G ...
    # G B G B ...

    # Rouge connu
    r[0::2, 0::2] = (
        raw[0::2, 0::2]
    )

    # Rouge sur pixels verts
    r[0::2, 1::2] = (
        left[0::2, 1::2]
        + right[0::2, 1::2]
    ) / 2.0

    r[1::2, 0::2] = (
        up[1::2, 0::2]
        + down[1::2, 0::2]
    ) / 2.0

    # Rouge sur pixels bleus
    r[1::2, 1::2] = (
        ul[1::2, 1::2]
        + ur[1::2, 1::2]
        + dl[1::2, 1::2]
        + dr[1::2, 1::2]
    ) / 4.0

    # Vert connu
    g[0::2, 1::2] = (
        raw[0::2, 1::2]
    )

    g[1::2, 0::2] = (
        raw[1::2, 0::2]
    )

    # Vert sur pixels rouges
    g[0::2, 0::2] = (
        up[0::2, 0::2]
        + down[0::2, 0::2]
        + left[0::2, 0::2]
        + right[0::2, 0::2]
    ) / 4.0

    # Vert sur pixels bleus
    g[1::2, 1::2] = (
        up[1::2, 1::2]
        + down[1::2, 1::2]
        + left[1::2, 1::2]
        + right[1::2, 1::2]
    ) / 4.0

    # Bleu connu
    b[1::2, 1::2] = (
        raw[1::2, 1::2]
    )

    # Bleu sur pixels verts
    b[1::2, 0::2] = (
        left[1::2, 0::2]
        + right[1::2, 0::2]
    ) / 2.0

    b[0::2, 1::2] = (
        up[0::2, 1::2]
        + down[0::2, 1::2]
    ) / 2.0

    # Bleu sur pixels rouges
    b[0::2, 0::2] = (
        ul[0::2, 0::2]
        + ur[0::2, 0::2]
        + dl[0::2, 0::2]
        + dr[0::2, 0::2]
    ) / 4.0

    # Balance des blancs Gray World
    mean_r = np.mean(r)
    mean_g = np.mean(g)
    mean_b = np.mean(b)

    target = (
        mean_r
        + mean_g
        + mean_b
    ) / 3.0

    coef_r = target / mean_r
    coef_g = target / mean_g
    coef_b = target / mean_b

    print(
        f">>> Gray World : "
        f"R={mean_r:.2f} "
        f"G={mean_g:.2f} "
        f"B={mean_b:.2f}"
    )

    print(
        f">>> Coefficients : "
        f"R={coef_r:.3f} "
        f"G={coef_g:.3f} "
        f"B={coef_b:.3f}",
        flush=True
    )

    r *= coef_r
    g *= coef_g
    b *= coef_b

    rgb = np.stack(
        (r, g, b),
        axis=2
    )

    rgb = np.clip(
        rgb,
        0,
        255
    ).astype(
        np.uint8
    )

    img = Image.fromarray(
        rgb,
        "RGB"
    )

    # Éclaircissement des ombres
    # sans modifier le noir absolu
    # et avec protection des hautes lumières.
    table = []

    for i in range(256):
        x = i / 255.0

        correction = (
            0.90
            * x
            * (1.0 - x) ** 2
        )

        y = x + correction

        y = min(
            y,
            1.0
        )

        table.append(
            int(
                255 * y
            )
        )

    img = img.point(
        table * 3
    )

    # Léger renforcement du contraste.
    img = ImageEnhance.Contrast(
        img
    ).enhance(
        1.10
    )

    # Renforcement léger de la netteté.
    img = img.filter(
        ImageFilter.UnsharpMask(
            radius=1.2,
            percent=120,
            threshold=3
        )
    )

    img.save(
        JPG_FILE,
        quality=92
    )


def capture_jpeg():
    configure_pipeline()
    capture_raw()
    raw_to_jpeg()

    with open(JPG_FILE, "rb") as f:
        return base64.b64encode(
            f.read()
        ).decode("utf-8")


class CameraHandler(
    BaseHTTPRequestHandler
):

    def send_json(
        self,
        status,
        payload
    ):
        data = json.dumps(
            payload
        ).encode("utf-8")

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json"
        )

        self.send_header(
            "Content-Length",
            str(len(data))
        )

        self.end_headers()

        self.wfile.write(
            data
        )

    def do_GET(self):

        if self.path == "/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "service": "camera"
                }
            )

            return

        if self.path.startswith(
            "/set_controls?"
        ):
            try:
                query = parse_qs(
                    urlparse(
                        self.path
                    ).query
                )

                exposure = query.get(
                    "exposure",
                    [None]
                )[0]

                analogue_gain = query.get(
                    "analogue_gain",
                    [None]
                )[0]

                with camera_lock:
                    applied = set_sensor_controls(
                        exposure=exposure,
                        analogue_gain=analogue_gain
                    )

                self.send_json(
                    200,
                    {
                        "ok": True,
                        "exposure":
                            applied["exposure"],
                        "analogue_gain":
                            applied["analogue_gain"]
                    }
                )

            except Exception as e:
                self.send_json(
                    500,
                    {
                        "ok": False,
                        "error": str(e)
                    }
                )

            return

        if self.path == "/capture":
            try:
                with camera_lock:
                    image_b64 = capture_jpeg()

                self.send_json(
                    200,
                    {
                        "ok": True,
                        "image": image_b64
                    }
                )

            except Exception as e:
                print(
                    "Erreur capture :",
                    e,
                    flush=True
                )

                self.send_json(
                    500,
                    {
                        "ok": False,
                        "error": str(e)
                    }
                )

            return

        if self.path == "/capture_auto":
            try:
                with camera_lock:
                    result = capture_auto()
                self.send_json(200, {"ok": True, **result})
            except Exception as e:
                print("Erreur exposition automatique :", e, flush=True)
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        self.send_json(
            404,
            {
                "ok": False,
                "error": "Not found"
            }
        )


print(
    f"Camera service listening "
    f"on port {PORT}",
    flush=True
)

server = ThreadingHTTPServer(
    (HOST, PORT),
    CameraHandler
)

server.serve_forever()
