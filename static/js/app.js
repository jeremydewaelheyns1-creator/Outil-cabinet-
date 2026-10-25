// Visualiseur de documents (D-036) : fenêtre au-dessus de la page.
(function () {
  function viewer() { return document.getElementById("doc-viewer"); }
  document.addEventListener("htmx:afterSwap", function (event) {
    var dialog = viewer();
    if (dialog && event.detail.target.id === "doc-viewer-content" && !dialog.open) {
      dialog.showModal();
    }
  });
  document.addEventListener("click", function (event) {
    var dialog = viewer();
    var target = event.target.closest ? event.target : null;
    if (!target) return;
    if (target.closest("[data-viewer-close]")) {
      if (dialog && dialog.open) dialog.close(); else history.back();
      return;
    }
    if (dialog && event.target === dialog) { dialog.close(); return; } // clic à côté
    var tab = target.closest("[data-viewer-tab]");
    if (tab) {
      var box = tab.closest(".viewer");
      box.querySelectorAll("[data-viewer-tab]").forEach(function (t) {
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
      });
      box.querySelectorAll("[data-viewer-panel]").forEach(function (panel) {
        panel.hidden = panel.dataset.viewerPanel !== tab.dataset.viewerTab;
      });
      return;
    }
    if (target.closest("[data-viewer-print]")) {
      document.body.classList.add("printing-document");
      window.print();
      document.body.classList.remove("printing-document");
    }
  });
  var changed = false;
  document.body && document.body.addEventListener("documents-changed", function () { changed = true; });
  document.addEventListener("documents-changed", function () { changed = true; });
  document.addEventListener("close", function (event) {
    if (event.target.id !== "doc-viewer") return;
    document.getElementById("doc-viewer-content").innerHTML = "";
    if (changed) window.location.reload(); // un document a été généré, validé ou envoyé
  }, true);
})();

// Bouton « copier » (numéros, e-mails) : fonctionne sur toutes les pages.
document.addEventListener("click", function (event) {
  var button = event.target.closest && event.target.closest("button.copy[data-copy]");
  if (!button || !navigator.clipboard) return;
  navigator.clipboard.writeText(button.dataset.copy).then(function () {
    button.classList.add("copied");
    button.textContent = "✓";
    setTimeout(function () { button.classList.remove("copied"); button.textContent = "⧉"; }, 1200);
  });
});

// Comportements de l'interface (sans dépendance). HTMX gère les échanges avec le serveur.
(function () {
  "use strict";

  const switcher = document.getElementById("switcher");
  if (!switcher) return;
  const input = document.getElementById("switcher-q");
  const results = document.getElementById("switcher-results");

  function open() {
    switcher.open = true;
    input.focus();
    input.select();
  }

  function items() {
    return Array.from(results.querySelectorAll("a.switcher-item"));
  }

  // Ctrl+K (ou Cmd+K) ouvre le sélecteur de client depuis n'importe quel écran.
  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      open();
    } else if (event.key === "Escape" && switcher.open) {
      switcher.open = false;
    }
  });

  switcher.addEventListener("toggle", function () {
    if (switcher.open) input.focus();
  });

  // Clic en dehors : on referme.
  document.addEventListener("click", function (event) {
    if (switcher.open && !switcher.contains(event.target)) switcher.open = false;
  });

  // Flèches haut/bas pour parcourir les résultats, Entrée pour ouvrir le premier.
  switcher.addEventListener("keydown", function (event) {
    const list = items();
    if (!list.length) return;
    const index = list.indexOf(document.activeElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      list[Math.min(index + 1, list.length - 1)].focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (index <= 0) input.focus();
      else list[index - 1].focus();
    } else if (event.key === "Enter" && document.activeElement === input) {
      event.preventDefault();
      list[0].click();
    }
  });
})();

// Grille TVA : un seul menu de case ouvert à la fois ; clic ailleurs ou Échap → fermé.
(function () {
  function closeMenus(except) {
    document.querySelectorAll("details.vat-menu[open]").forEach(function (menu) {
      if (menu !== except) menu.removeAttribute("open");
    });
  }
  document.addEventListener("toggle", function (event) {
    var menu = event.target;
    if (menu.classList && menu.classList.contains("vat-menu") && menu.open) closeMenus(menu);
  }, true);
  document.addEventListener("click", function (event) {
    if (!event.target.closest || !event.target.closest("details.vat-menu")) closeMenus(null);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeMenus(null);
  });
})();

// Dépôt unique : noms des fichiers choisis et zone qui s'éclaire quand on glisse dessus.
(function () {
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches(".depot-zone input[type=file]")) return;
    var out = input.closest(".depot-zone").querySelector("[data-depot-chosen]");
    var names = Array.prototype.map.call(input.files, function (f) { return f.name; });
    if (out) out.textContent = names.length ? names.length + " fichier(s) : " + names.join(", ") : "";
  });
  ["dragenter", "dragover"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      var zone = event.target.closest && event.target.closest(".depot-zone");
      if (zone) zone.classList.add("is-over");
    });
  });
  ["dragleave", "drop"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      var zone = event.target.closest && event.target.closest(".depot-zone");
      if (zone) zone.classList.remove("is-over");
    });
  });
})();

// Case « tout cocher » (tableau de conformité).
document.addEventListener("change", function (event) {
  var box = event.target;
  if (!box.matches || !box.matches("[data-check-all]")) return;
  var form = box.closest("form");
  if (!form) return;
  form.querySelectorAll('input[type=checkbox][name="' + box.dataset.checkAll + '"]').forEach(function (other) {
    other.checked = box.checked;
  });
});

// Messages de confirmation (« … réussie », « … ajoutée ») : ils s'effacent après 5 secondes.
// Les erreurs et avertissements restent affichés, pour être lus.
(function () {
  function fade() {
    document.querySelectorAll(".messages .alert-success, .messages .alert-info").forEach(function (item) {
      if (item.dataset.fading) return;
      item.dataset.fading = "1";
      setTimeout(function () {
        item.classList.add("is-leaving");
        setTimeout(function () {
          var list = item.parentNode;
          item.remove();
          if (list && !list.children.length) list.remove();
        }, 450);
      }, 5000);
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fade);
  else fade();
  document.addEventListener("htmx:afterSwap", fade);
})();

// Listes déroulantes qui relancent le filtre dès qu'on change la valeur (sans script en ligne,
// pour la politique de sécurité du contenu).
document.addEventListener("change", function (event) {
  var field = event.target;
  if (field.matches && field.matches("[data-autosubmit]") && field.form) field.form.submit();
});
