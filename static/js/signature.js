// Cadre de signature de la page publique (D-048) : doigt, stylet ou souris.
(function () {
  var form = document.querySelector("[data-sign-form]");
  if (!form) return;
  var canvas = form.querySelector("[data-sign-pad]");
  var value = form.querySelector("[data-sign-value]");
  var ctx = canvas.getContext("2d");
  var drawing = false, inked = 0, last = null;

  function resize() {
    var ratio = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.lineWidth = 2.4; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#14243b";
    inked = 0;
  }
  function point(e) {
    var rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }
  canvas.addEventListener("pointerdown", function (e) {
    drawing = true; last = point(e); canvas.setPointerCapture(e.pointerId); e.preventDefault();
  });
  canvas.addEventListener("pointermove", function (e) {
    if (!drawing) return;
    var p = point(e);
    ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke();
    inked += Math.abs(p.x - last.x) + Math.abs(p.y - last.y);
    last = p; e.preventDefault();
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach(function (type) {
    canvas.addEventListener(type, function () { drawing = false; });
  });
  form.querySelector("[data-sign-clear]").addEventListener("click", function () {
    ctx.clearRect(0, 0, canvas.width, canvas.height); inked = 0;
  });
  form.addEventListener("submit", function (e) {
    if (inked < 30) {
      e.preventDefault();
      alert("Dessinez votre signature dans le cadre avant de signer.");
      return;
    }
    value.value = canvas.toDataURL("image/png");
  });
  window.addEventListener("resize", resize);
  resize();
})();
