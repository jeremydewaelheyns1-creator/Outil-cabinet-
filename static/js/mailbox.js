// « Ma boîte mail » : clic droit (ou bouton ⋯) sur un e-mail = menu d'actions ; les fenêtres
// (échéance, reclasser, privé, nouveau message) s'ouvrent quand l'adresse le demande.
(function () {
  "use strict";
  function closeMenus() {
    document.querySelectorAll(".mb-menu").forEach(function (menu) { menu.hidden = true; });
  }
  function openMenu(item, x, y) {
    closeMenus();
    var menu = item.querySelector(".mb-menu");
    if (!menu) return;
    var box = item.getBoundingClientRect();
    menu.style.left = Math.max(8, x - box.left) + "px";
    menu.style.top = Math.max(8, y - box.top) + "px";
    menu.hidden = false;
    var first = menu.querySelector("a");
    if (first) first.focus();
  }
  document.addEventListener("contextmenu", function (event) {
    var item = event.target.closest && event.target.closest("[data-mb-item]");
    if (!item) return;
    event.preventDefault();
    openMenu(item, event.clientX, event.clientY);
  });
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest && event.target.closest("[data-mb-toggle]");
    if (toggle) {
      var item = toggle.closest("[data-mb-item]");
      var rect = toggle.getBoundingClientRect();
      var menu = item.querySelector(".mb-menu");
      if (menu && !menu.hidden) { closeMenus(); return; }
      openMenu(item, rect.left - 180, rect.bottom);
      return;
    }
    if (!(event.target.closest && event.target.closest(".mb-menu"))) closeMenus();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeMenus();
  });
  document.querySelectorAll("dialog[data-open]").forEach(function (dialog) {
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  });
})();
