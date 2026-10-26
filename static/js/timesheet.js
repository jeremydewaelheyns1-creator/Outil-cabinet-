// Feuille de temps : un clic dans une journée vide pré-remplit le formulaire (jour, heure de
// début arrondie au quart d'heure, fin une heure plus tard) et place le curseur sur le dossier.
(function () {
  "use strict";
  var FIRST_HOUR = 7;
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  document.addEventListener("click", function (event) {
    var day = event.target.closest && event.target.closest("[data-ts-day]");
    if (!day || event.target.closest(".ts-block")) return;
    var form = document.querySelector(".ts-form");
    if (!form) return;
    var hour = parseFloat(getComputedStyle(day.closest(".ts-grid")).getPropertyValue("--hour")) || 48;
    var y = event.clientY - day.getBoundingClientRect().top;
    var minutes = Math.max(0, Math.round((y / hour) * 4) * 15) + FIRST_HOUR * 60;
    var end = Math.min(minutes + 60, 23 * 60 + 45);
    form.querySelector("[name=day]").value = day.dataset.tsDay;
    form.querySelector("[name=start]").value = pad(Math.floor(minutes / 60)) + ":" + pad(minutes % 60);
    form.querySelector("[name=end]").value = pad(Math.floor(end / 60)) + ":" + pad(end % 60);
    var entry = form.querySelector("[name=entry]");
    if (entry) entry.remove();
    var client = form.querySelector("[name=client]");
    form.scrollIntoView({ behavior: "smooth", block: "nearest" });
    var combo = client && client.closest(".combo");
    var target = combo ? combo.querySelector("input[role=combobox]") : client;
    if (target) target.focus();
  });
})();
