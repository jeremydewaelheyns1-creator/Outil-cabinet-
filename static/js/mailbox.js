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
    // Un refus (« Message non envoyé : … ») s'affiche dans la fenêtre, pas derrière elle.
    var failed = document.querySelector(".messages .alert-error");
    var form = dialog.querySelector("form");
    var heading = form && form.querySelector("h2");
    if (failed && heading) {
      var notice = document.createElement("p");
      notice.className = "alert alert-error";
      notice.textContent = failed.textContent;
      heading.after(notice);
    }
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  });
})();

// Mise en forme du message (gras, italique, souligné, listes) et choix « Programmer le ».
(function () {
  "use strict";
  function sync(box) {
    var area = box.querySelector(".rt-area");
    box.querySelector("input[name=html]").value = area.innerHTML;
    box.querySelector("textarea").value = area.innerText;
  }
  function refresh(box) {
    box.querySelectorAll("[data-rt-cmd]").forEach(function (button) {
      var on = false;
      try { on = document.queryCommandState(button.getAttribute("data-rt-cmd")); } catch (e) { on = false; }
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  document.querySelectorAll("[data-rt]").forEach(function (box) {
    var area = box.querySelector(".rt-area");
    var textarea = box.querySelector("textarea");
    box.querySelector(".rt-bar").hidden = false;
    area.hidden = false;
    textarea.hidden = true;
    textarea.required = false;
    area.addEventListener("input", function () { sync(box); });
    area.addEventListener("keyup", function () { refresh(box); });
    area.addEventListener("mouseup", function () { refresh(box); });
    box.querySelectorAll("[data-rt-cmd]").forEach(function (button) {
      button.addEventListener("mousedown", function (event) { event.preventDefault(); });
      button.addEventListener("click", function () {
        area.focus();
        document.execCommand(button.getAttribute("data-rt-cmd"), false);
        sync(box);
        refresh(box);
      });
    });
    var form = box.closest("form");
    if (form) {
      // Brouillon gardé le temps de l'envoi : si l'outil refuse (boîte déliée, date passée…),
      // le texte n'est pas perdu. Effacé dès que l'envoi a réussi.
      var key = "brouillon:" + form.getAttribute("action");
      var failed = document.querySelector(".alert-error, .alert-danger");
      try {
        var saved = JSON.parse(sessionStorage.getItem(key) || "null");
        if (saved && failed) {
          area.innerHTML = saved.html || "";
          ["a", "objet", "programmer"].forEach(function (name) {
            if (form.elements[name] && saved[name]) form.elements[name].value = saved[name];
          });
          var later = form.querySelector("input[name=quand][value=plus-tard]");
          if (later && saved.later) { later.checked = true; later.dispatchEvent(new Event("change", { bubbles: true })); }
          sync(box);
        }
        if (!failed) sessionStorage.removeItem(key);
      } catch (e) { /* stockage indisponible : rien à restaurer */ }
      form.addEventListener("submit", function (event) {
        sync(box);
        if (!area.innerText.trim()) {
          event.preventDefault();
          area.classList.add("rt-empty");
          area.focus();
          return;
        }
        try {
          sessionStorage.setItem(key, JSON.stringify({
            html: area.innerHTML,
            a: form.elements.a ? form.elements.a.value : "",
            objet: form.elements.objet ? form.elements.objet.value : "",
            programmer: form.elements.programmer ? form.elements.programmer.value : "",
            later: !!form.querySelector("input[name=quand][value=plus-tard]:checked")
          }));
        } catch (e) { /* pas grave */ }
      });
    }
  });
  document.querySelectorAll("[data-when]").forEach(function (fieldset) {
    var form = fieldset.closest("form");
    var button = form.querySelector("[data-send-label]");
    var picker = fieldset.querySelector("input[type=datetime-local]");
    var normal = button ? button.textContent : "";
    function update() {
      var later = fieldset.querySelector("input[value=plus-tard]").checked;
      picker.required = later;
      if (button) button.textContent = later ? button.getAttribute("data-send-label") : normal;
    }
    fieldset.addEventListener("change", update);
    picker.addEventListener("focus", function () {
      fieldset.querySelector("input[value=plus-tard]").checked = true;
      update();
    });
    update();
  });
})();
