// Petite liste de documents (onglet Documents) : se ferme quand on clique ailleurs.
document.addEventListener("click", function (event) {
  document.querySelectorAll("details.doc-peek[open]").forEach(function (menu) {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
});

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
