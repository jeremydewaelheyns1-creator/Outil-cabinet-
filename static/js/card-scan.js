// Scan de la carte d'identité par la caméra du téléphone du client (D-083).
//
// 1. La caméra s'ouvre, avec un cadre à la taille d'une carte (85,6 × 54 mm).
// 2. Recto : la photo se prend toute seule quand l'image est nette, bien éclairée et stable.
// 3. Verso : les 3 lignes codées du bas sont lues ICI, dans le téléphone (Tesseract compilé en
//    WebAssembly, servi par l'outil lui-même : aucun service extérieur). La photo se prend
//    quand les chiffres de contrôle de la carte tombent juste.
// 4. Les deux photos (seulement elles) partent par le formulaire habituel : le serveur relit
//    la carte, la range et note sa date d'expiration, comme pour une photo déposée.
// Sans caméra (ou refusée) : le formulaire de dépôt reste là, rien ne change.
(function () {
  "use strict";

  var box = document.querySelector("[data-card-scan]");
  var form = document.querySelector("[data-upload-form]");
  if (!box || !form || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
  if (typeof DataTransfer === "undefined") return; // très vieux navigateur : dépôt classique
  box.hidden = false;

  var CARD_RATIO = 85.6 / 54;
  var video = box.querySelector("[data-scan-video]");
  var frame = box.querySelector("[data-scan-frame]");
  var hint = box.querySelector("[data-scan-hint]");
  var step = box.querySelector("[data-scan-step]");
  var manual = box.querySelector("[data-scan-manual]");
  var live = box.querySelector("[data-scan-live]");
  var stream = null;
  var shots = [];
  var phase = "recto";
  var stopped = false;
  var worker = null;
  var phaseStart = 0;

  function say(text, level) {
    hint.textContent = text;
    hint.dataset.level = level || "";
    frame.dataset.level = level || "";
  }

  // --- Géométrie : le cadre affiché → la zone correspondante dans l'image de la caméra --------
  function cardRect() {
    var vw = video.videoWidth, vh = video.videoHeight;
    var box_ = video.getBoundingClientRect(), f = frame.getBoundingClientRect();
    var scale = Math.max(box_.width / vw, box_.height / vh); // object-fit: cover
    var offX = (vw * scale - box_.width) / 2, offY = (vh * scale - box_.height) / 2;
    return {
      x: Math.max(0, (f.left - box_.left + offX) / scale),
      y: Math.max(0, (f.top - box_.top + offY) / scale),
      w: Math.min(vw, f.width / scale),
      h: Math.min(vh, f.height / scale),
    };
  }

  function withMargin(rect, ratio) {
    var mx = rect.w * ratio, my = rect.h * ratio;
    var x = Math.max(0, rect.x - mx), y = Math.max(0, rect.y - my);
    return {
      x: x, y: y,
      w: Math.min(video.videoWidth - x, rect.w + 2 * mx),
      h: Math.min(video.videoHeight - y, rect.h + 2 * my),
    };
  }

  function grab(rect, width, part) {
    // part : fraction basse de la carte à garder (verso : les lignes codées), 1 = toute la carte
    var top = rect.y + rect.h * (1 - part), height = rect.h * part;
    var canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = Math.round(width * height / rect.w);
    canvas.getContext("2d").drawImage(video, rect.x, top, rect.w, height, 0, 0, canvas.width, canvas.height);
    return canvas;
  }

  // --- Recto : netteté, lumière, stabilité ---------------------------------------------------
  var previous = null, goodFrames = 0;
  function measure(canvas) {
    var ctx = canvas.getContext("2d");
    var data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    var w = canvas.width, h = canvas.height, gray = new Float32Array(w * h), sum = 0;
    for (var i = 0; i < w * h; i++) {
      gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
      sum += gray[i];
    }
    var edges = 0;
    for (var y = 1; y < h; y++) {
      for (var x = 1; x < w; x++) {
        edges += Math.abs(gray[y * w + x] - gray[y * w + x - 1]) + Math.abs(gray[y * w + x] - gray[(y - 1) * w + x]);
      }
    }
    var moved = 0;
    if (previous && previous.length === gray.length) {
      for (var j = 0; j < gray.length; j += 7) moved += Math.abs(gray[j] - previous[j]);
      moved /= gray.length / 7;
    } else {
      moved = 99;
    }
    previous = gray;
    return { light: sum / (w * h), sharp: edges / (w * h), moved: moved };
  }

  function checkRecto() {
    var m = measure(grab(cardRect(), 240, 1));
    if (m.light < 55) return say("Plus de lumière, s'il vous plaît", "warn");
    if (m.light > 235) return say("Évitez le reflet (inclinez un peu la carte)", "warn");
    if (m.sharp < 9) { goodFrames = 0; return say("Rapprochez la carte du cadre", "warn"); }
    if (m.moved > 9) { goodFrames = 0; return say("Ne bougez plus…", "warn"); }
    goodFrames += 1;
    say("Parfait, ne bougez plus…", "ok");
    if (goodFrames >= 3) take();
  }

  // --- Verso : lecture des 3 lignes codées et chiffres de contrôle ----------------------------
  var WEIGHTS = [7, 3, 1];
  function value(c) {
    if (c >= "0" && c <= "9") return c.charCodeAt(0) - 48;
    if (c === "<") return 0;
    return c.charCodeAt(0) - 55;
  }
  function check(data) {
    var total = 0;
    for (var i = 0; i < data.length; i++) total += value(data[i]) * WEIGHTS[i % 3];
    return String(total % 10);
  }
  var DIGITS = { O: "0", Q: "0", D: "0", I: "1", L: "1", Z: "2", S: "5", B: "8", G: "6" };
  function digits(text) {
    return text.replace(/[OQDILZSBG]/g, function (c) { return DIGITS[c]; });
  }
  var LOOKALIKE = { "0": "68", "6": "085", "8": "0636", "1": "7", "7": "1", "3": "8", "5": "6" };
  function compositeOk(l1, l2) {
    var composite = l1.slice(5, 30) + l2.slice(0, 7) + l2.slice(8, 15) + l2.slice(18, 29);
    return check(composite) === l2[29];
  }
  function validLines(text) {
    var rows = text.toUpperCase().split(/\n/).map(function (row) {
      return row.replace(/\s/g, "").replace(/[^A-Z0-9<]/g, "");
    }).filter(function (row) { return row.length >= 28; });
    for (var i = 0; i + 2 < rows.length; i++) {
      var l1 = rows[i].slice(0, 30), l2 = rows[i + 1], l3 = rows[i + 2];
      if (!l2 || !l3 || l1.length !== 30 || l2.length < 30) continue;
      l2 = l2.slice(0, 30);
      l2 = digits(l2.slice(0, 7)) + l2[7] + digits(l2.slice(8, 15)) + l2.slice(15, 29) + digits(l2[29]);
      if (check(l2.slice(0, 6)) !== l2[6] || check(l2.slice(8, 14)) !== l2[14]) continue;
      if (compositeOk(l1, l2)) return true;
      // Un seul chiffre mal lu parmi ceux qui se ressemblent (0/6/8, 1/7, 3/8, 5/6) dans les
      // données facultatives : la photo est assez nette, le serveur relira tout de toute façon.
      for (var p = 18; p < 29; p++) {
        var alts = LOOKALIKE[l2[p]] || "";
        for (var a = 0; a < alts.length; a++) {
          if (compositeOk(l1, l2.slice(0, p) + alts[a] + l2.slice(p + 1))) return true;
        }
      }
    }
    return false;
  }

  function prepareForReading(canvas) {
    var ctx = canvas.getContext("2d");
    var img = ctx.getImageData(0, 0, canvas.width, canvas.height), d = img.data;
    var lo = 255, hi = 0, i, g;
    for (i = 0; i < d.length; i += 4) {
      g = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
      d[i] = d[i + 1] = d[i + 2] = g;
      if (g < lo) lo = g;
      if (g > hi) hi = g;
    }
    var span = Math.max(1, hi - lo);
    for (i = 0; i < d.length; i += 4) d[i] = d[i + 1] = d[i + 2] = ((d[i] - lo) * 255) / span;
    ctx.putImageData(img, 0, 0);
    return canvas;
  }

  var reading = false;
  function checkVerso() {
    if (reading || !worker) return;
    reading = true;
    var band = prepareForReading(grab(cardRect(), 1100, 0.42));
    worker.recognize(band).then(function (result) {
      reading = false;
      if (stopped || phase !== "verso") return;
      if (validLines(result.data.text || "")) {
        say("Lu ✓", "ok");
        take();
      } else {
        say("Lecture… tenez la carte bien droite, les 3 lignes du bas dans le cadre", "warn");
      }
    }, function () { reading = false; });
  }

  // --- Photos et envoi -----------------------------------------------------------------------
  function take() {
    var current = phase;
    if (current !== "recto" && current !== "verso") return;
    phase = "transition"; // pas de seconde photo pendant l'enregistrement de celle-ci
    var rect = withMargin(cardRect(), 0.06); // un peu de marge si la carte dépasse du cadre
    var canvas = grab(rect, Math.min(2000, Math.round(rect.w)), 1);
    canvas.toBlob(function (blob) {
      if (!blob) { phase = current; return; }
      shots.push(new File([blob], current + ".jpg", { type: "image/jpeg" }));
      if (current === "recto") {
        phase = "verso";
        phaseStart = Date.now();
        manual.hidden = true;
        goodFrames = 0;
        step.textContent = "Verso (2/2)";
        say("Retournez la carte : le verso, avec les 3 lignes du bas", "");
      } else {
        finish();
      }
    }, "image/jpeg", 0.92);
  }

  function finish() {
    stopped = true;
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    if (worker) worker.terminate();
    live.hidden = true;
    box.querySelector("[data-scan-done]").hidden = false;
    var input = form.querySelector("input[type=file]");
    var transfer = new DataTransfer();
    shots.forEach(function (file) { transfer.items.add(file); });
    input.files = transfer.files;
    form.submit();
  }

  function loop() {
    if (stopped) return;
    if (video.readyState >= 2) {
      var waited = (Date.now() - phaseStart) / 1000;
      if (phase === "recto") checkRecto();
      if (phase === "verso") checkVerso();
      if ((phase === "recto" && waited > 8) || (phase === "verso" && waited > 25)) manual.hidden = false;
    }
    setTimeout(loop, phase === "verso" ? 250 : 350);
  }

  manual.addEventListener("click", take);

  box.querySelector("[data-scan-start]").addEventListener("click", function () {
    var button = this;
    button.disabled = true;
    navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } },
    }).then(function (s) {
      stream = s;
      video.srcObject = s;
      return video.play();
    }).then(function () {
      button.hidden = true;
      box.querySelector(".card-scan-intro").hidden = true;
      live.hidden = false;
      phaseStart = Date.now();
      loop();
      // Le lecteur se prépare pendant que le client cadre le recto.
      if (window.Tesseract) {
        window.Tesseract.createWorker("eng", 1, {
          workerPath: box.dataset.worker,
          corePath: box.dataset.core,
          langPath: box.dataset.lang,
          workerBlobURL: false,
          gzip: true,
        }).then(function (w) {
          worker = w;
          return w.setParameters({
            tessedit_char_whitelist: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<",
            tessedit_pageseg_mode: "6",
          });
        }).catch(function () {
          worker = null; // lecteur indisponible : le client prend la photo lui-même
          manual.hidden = false;
        });
      }
    }).catch(function () {
      button.disabled = false;
      say("Caméra indisponible ou refusée : déposez des photos ci-dessous.", "warn");
      live.hidden = false;
      box.querySelector(".card-scan-view").hidden = true;
    });
  });
})();
