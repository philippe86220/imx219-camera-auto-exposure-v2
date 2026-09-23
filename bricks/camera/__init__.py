
import json
import urllib.request


class Camera:

    def __init__(
        self,
        host="camera",
        port=9000
    ):
        self.base_url = f"http://{host}:{port}"

    def status(self):
        url = f"{self.base_url}/health"

        with urllib.request.urlopen(
            url,
            timeout=5
        ) as response:
            data = response.read().decode("utf-8")

        return json.loads(data)

    def capture(self):
        url = f"{self.base_url}/capture"

        with urllib.request.urlopen(
            url,
            timeout=60
        ) as response:
            data = response.read().decode("utf-8")

        return json.loads(data)

    def capture_auto(self):
        url = f"{self.base_url}/capture_auto"
        with urllib.request.urlopen(url, timeout=180) as response:
            data = response.read().decode("utf-8")
        return json.loads(data)

    def set_controls(
        self,
        exposure,
        analogue_gain
    ):
        url = (
            f"{self.base_url}/set_controls"
            f"?exposure={exposure}"
            f"&analogue_gain={analogue_gain}"
        )

        with urllib.request.urlopen(
            url,
            timeout=5
        ) as response:
            data = response.read().decode("utf-8")

        return json.loads(data)
