const ui = new WebUI();

ui.on_connect(onUIConnected);


const bouton = document.getElementById(
  "boutonPhoto"
);

const boutonAuto = document.getElementById("boutonPhotoAuto");
const mesureAuto = document.getElementById("mesureAuto");
let captureDemandee = "manuel";

function captureBusy(busy) {
  bouton.disabled = busy;
  boutonAuto.disabled = busy;
}

const etat = document.getElementById(
  "etat"
);

const photo = document.getElementById(
  "photo"
);

const exposure = document.getElementById(
  "exposure"
);

const gain = document.getElementById(
  "gain"
);

const exposureValue = document.getElementById(
  "exposureValue"
);

const gainValue = document.getElementById(
  "gainValue"
);

const appliquerReglages = document.getElementById(
  "appliquerReglages"
);


function onUIConnected() {
  console.log(
    "WebUI connectee"
  );

  etat.textContent = "Initialisation...";

  ui.send_message(
    "get_camera_defaults",
    {}
  );
}


exposure.addEventListener(
  "input",
  function () {
    exposureValue.textContent = exposure.value;
  }
);


gain.addEventListener(
  "input",
  function () {
    gainValue.textContent = gain.value;
  }
);


appliquerReglages.addEventListener(
  "click",
  function () {
    etat.textContent = "Application des reglages...";

    ui.send_message(
      "regler_camera",
      {
        exposure: Number(
          exposure.value
        ),
        analogue_gain: Number(
          gain.value
        )
      }
    );
  }
);


bouton.addEventListener(
  "click",
  function () {
    captureDemandee = "manuel";
    captureBusy(true);

    etat.textContent = "Capture en cours...";

    ui.send_message(
      "prendre_photo",
      {}
    );
  }
);

boutonAuto.addEventListener("click", function () {
  captureDemandee = "automatique";
  captureBusy(true);
  etat.textContent = "Mesure et exposition automatique en cours...";
  mesureAuto.textContent = "Mesures RAW en attente...";
  ui.send_message("prendre_photo_auto", {});
});


ui.on_message(
  "camera_settings_update",
  function (data) {
    if (data.ok) {
      etat.textContent = "Reglages appliques";
    } else {
      etat.textContent =
        "Erreur reglages : " + data.error;
    }
  }
);


ui.on_message(
  "camera_defaults",
  function (data) {
    exposure.value = data.exposure;
    gain.value = data.analogue_gain;

    exposureValue.textContent = data.exposure;
    gainValue.textContent = data.analogue_gain;

    etat.textContent = "Pret";
  }
);


ui.on_message(
  "photo_update",
  function (data) {
    captureBusy(false);

    if (data.ok) {
      etat.textContent = "Photo capturee";

      photo.src =
        "data:image/jpeg;base64,"
        + data.image;

      if (data.settings && data.statistics) {
        const stats = data.statistics;
        exposure.value = data.settings.exposure;
        gain.value = data.settings.analogue_gain;
        exposureValue.textContent = data.settings.exposure;
        gainValue.textContent = data.settings.analogue_gain;
        mesureAuto.textContent =
          "RAW : noir=" + stats.black_level +
          ", mediane verte=" + stats.median_green.toFixed(3) +
          ", P99=" + stats.p99_green.toFixed(3) +
          ", centre=" + (typeof stats.center_median === "number"
            ? stats.center_median.toFixed(3) : "indisponible") +
          ", centre P95=" + (typeof stats.center_p95 === "number"
            ? stats.center_p95.toFixed(3) : "indisponible") +
          ", captures=" + (data.history ? data.history.length : "?");
      } else if (captureDemandee === "automatique") {
        mesureAuto.textContent =
          "Mesures RAW absentes de la reponse : verifier python/main.py";
      } else {
        mesureAuto.textContent = "";
      }
    } else {
      mesureAuto.textContent = "";
      etat.textContent =
        "Erreur : " + data.erreur;
    }
  }
);
