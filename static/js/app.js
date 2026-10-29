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

// Champ montré seulement pour un choix précis d'une liste : data-show-if="nom-de-la-liste=valeur"
// (ex. la question à poser, seulement si le trou est « à demander »). Sans JavaScript : visible.
(function () {
  function sync() {
    document.querySelectorAll("[data-show-if]").forEach(function (field) {
      var parts = field.getAttribute("data-show-if").split("=");
      var select = document.querySelector('[name="' + parts[0] + '"]');
      if (select) field.hidden = select.value !== parts[1];
    });
  }
  document.addEventListener("change", sync);
  document.addEventListener("DOMContentLoaded", sync);
})();

// Liste de dossiers « à taper » : on écrit quelques lettres, l'outil propose les dossiers qui
// correspondent (sans tenir compte des accents). La vraie liste reste dans la page (sans
// JavaScript, elle s'affiche telle quelle).
(function () {
  function plain(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }
  var counter = 0;
  document.querySelectorAll("select[data-searchable]").forEach(function (select) {
    counter += 1;
    var listId = "choix-" + counter;
    var box = document.createElement("div");
    box.className = "combo";
    var input = document.createElement("input");
    input.type = "text";
    input.autocomplete = "off";
    input.placeholder = "Tapez un nom…";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", listId);
    if (select.id) {
      input.id = select.id;
      select.id = select.id + "-liste";
    }
    var list = document.createElement("ul");
    list.className = "combo-list";
    list.id = listId;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    select.parentNode.insertBefore(box, select);
    box.appendChild(input);
    box.appendChild(list);
    box.appendChild(select);
    select.hidden = true;
    select.tabIndex = -1;
    var options = Array.prototype.filter.call(select.options, function (o) { return o.value; });
    var current = select.options[select.selectedIndex];
    if (current && current.value) input.value = current.textContent.trim();
    var active = -1;
    function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; }
    function choose(option) {
      select.value = option.value;
      input.value = option.textContent.trim();
      input.setCustomValidity("");
      close();
    }
    function show() {
      var words = plain(input.value).split(/\s+/).filter(Boolean);
      var found = options.filter(function (o) {
        var label = plain(o.textContent);
        return words.every(function (w) { return label.indexOf(w) !== -1; });
      }).slice(0, 8);
      list.innerHTML = "";
      found.forEach(function (o, i) {
        var item = document.createElement("li");
        item.setAttribute("role", "option");
        item.id = listId + "-" + i;
        item.textContent = o.textContent.trim();
        item.addEventListener("mousedown", function (e) { e.preventDefault(); choose(o); });
        list.appendChild(item);
      });
      if (!found.length) {
        var none = document.createElement("li");
        none.className = "combo-none";
        none.textContent = "Aucun dossier ne correspond";
        list.appendChild(none);
      }
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      active = -1;
      return found;
    }
    var shown = [];
    input.addEventListener("focus", function () { shown = show(); });
    input.addEventListener("input", function () {
      select.value = "";
      shown = show();
    });
    input.addEventListener("blur", function () {
      close();
      if (!select.value) input.value = "";
      if (select.required && !select.value) input.setCustomValidity("Choisissez un dossier dans la liste.");
    });
    input.addEventListener("keydown", function (e) {
      var items = list.querySelectorAll("[role=option]");
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (list.hidden) shown = show();
        active = Math.max(0, Math.min(items.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
        items.forEach(function (it, i) { it.classList.toggle("is-active", i === active); });
        if (items[active]) input.setAttribute("aria-activedescendant", items[active].id);
      } else if (e.key === "Enter" && !list.hidden && shown.length) {
        e.preventDefault();
        choose(shown[Math.max(0, active)]);
      } else if (e.key === "Escape") {
        close();
      }
    });
    if (select.required) {
      input.required = true;
      var form = select.form;
      if (form) form.addEventListener("submit", function (e) {
        if (!select.value) { e.preventDefault(); input.setCustomValidity("Choisissez un dossier dans la liste."); input.reportValidity(); }
      });
    }
  });
})();

// Dépôt depuis n'importe quelle page (D-093) : on glisse des fichiers n'importe où (sauf sur un
// champ de fichier, qui garde son rôle), un voile dit « Lâchez pour déposer », puis un panneau
// suit la lecture, fichier par fichier, sans quitter l'écran. Le bouton du haut ouvre le même
// panneau. Les XML partent d'abord (un PDF rejoint alors son XML).
(function () {
  var panel = document.querySelector("[data-depot-panel]");
  var veil = document.querySelector("[data-depot-veil]");
  if (!panel || !veil) return;
  var lines = panel.querySelector("[data-depot-lines]");
  var input = panel.querySelector("[data-depot-input]");
  var token = panel.querySelector("input[name=csrfmiddlewaretoken]");
  var MAX = 50;
  var hideTimer = null;
  var running = 0;
  var counts = { ok: 0, doubt: 0, inbox: 0, duplicate: 0, error: 0 };

  function hasFiles(event) {
    var types = event.dataTransfer && event.dataTransfer.types;
    return types && Array.prototype.indexOf.call(types, "Files") !== -1;
  }
  function ownZone(target) {
    return target && target.closest && target.closest("input[type=file], .depot-zone, [data-own-drop]");
  }
  function showVeil() {
    veil.hidden = false;
    clearTimeout(hideTimer);
    hideTimer = setTimeout(function () { veil.hidden = true; }, 180);
  }
  document.addEventListener("dragover", function (event) {
    if (!hasFiles(event)) return;
    if (ownZone(event.target)) { veil.hidden = true; return; }
    event.preventDefault();
    showVeil();
  });
  document.addEventListener("drop", function (event) {
    if (!hasFiles(event) || ownZone(event.target)) return;
    event.preventDefault();
    veil.hidden = true;
    send(event.dataTransfer.files);
  });
  document.addEventListener("click", function (event) {
    var opener = event.target.closest && event.target.closest("[data-depot-open]");
    if (opener) { event.preventDefault(); input.click(); return; }
    if (event.target.closest && event.target.closest("[data-depot-close]")) {
      panel.hidden = true;
      if (!running) reset();
    }
  });
  input.addEventListener("change", function () { send(input.files); input.value = ""; });

  function reset() {
    lines.innerHTML = "";
    counts = { ok: 0, doubt: 0, inbox: 0, duplicate: 0, error: 0 };
    panel.querySelector("[data-depot-done]").hidden = true;
  }
  function pendingLine(file) {
    var li = document.createElement("li");
    li.className = "depot-line is-pending";
    var icon = document.createElement("span");
    icon.className = "depot-line-icon";
    icon.setAttribute("aria-hidden", "true");
    var text = document.createElement("div");
    text.className = "depot-line-text";
    var name = document.createElement("strong");
    name.textContent = file.name;
    var sub = document.createElement("div");
    sub.className = "small";
    sub.textContent = "Lecture…";
    text.appendChild(name);
    text.appendChild(sub);
    li.appendChild(icon);
    li.appendChild(text);
    lines.appendChild(li);
    return li;
  }
  function plural(n, one, many) { return n + " " + (n > 1 ? many : one); }
  function summary() {
    var parts = [];
    if (counts.ok) parts.push(plural(counts.ok, "rangé", "rangés"));
    if (counts.doubt) parts.push(plural(counts.doubt, "à vérifier", "à vérifier"));
    if (counts.inbox) parts.push(plural(counts.inbox, "à classer", "à classer"));
    if (counts.duplicate) parts.push(plural(counts.duplicate, "doublon à comparer", "doublons à comparer"));
    if (counts.error) parts.push(plural(counts.error, "refusé", "refusés"));
    var done = panel.querySelector("[data-depot-done]");
    done.querySelector("[data-depot-summary]").textContent = (counts.doubt || counts.inbox || counts.duplicate || counts.error ? "" : "✓ ") + parts.join(" · ");
    done.className = "depot-panel-done" + (counts.doubt || counts.inbox || counts.duplicate || counts.error ? " has-todo" : "");
    done.hidden = false;
    panel.querySelector("[data-depot-sub]").textContent = "Tout est lu. Cliquez sur une ligne pour l'ouvrir.";
  }
  function send(fileList) {
    var files = Array.prototype.slice.call(fileList || [], 0, MAX);
    if (!files.length) return;
    if (!running) reset();
    files.sort(function (a, b) { return (/\.xml$/i.test(b.name) ? 1 : 0) - (/\.xml$/i.test(a.name) ? 1 : 0); });
    panel.hidden = false;
    panel.querySelector("[data-depot-title]").textContent = plural(lines.children.length + files.length, "document déposé", "documents déposés");
    panel.querySelector("[data-depot-sub]").textContent = "Vous pouvez continuer à travailler pendant la lecture.";
    panel.querySelector("[data-depot-done]").hidden = true;
    var queue = files.map(function (file) { return { file: file, line: pendingLine(file) }; });
    running += queue.length;
    (function next() {
      var job = queue.shift();
      if (!job) return;
      var data = new FormData();
      data.append("files", job.file);
      fetch(panel.dataset.url, {
        method: "POST", body: data, credentials: "same-origin",
        headers: { "X-CSRFToken": token ? token.value : "", "X-Requested-With": "fetch" },
      }).then(function (response) {
        if (!response.ok) throw new Error("http");
        return response.text();
      }).then(function (html) {
        var box = document.createElement("ul");
        box.innerHTML = html;
        var result = box.querySelector(".depot-line");
        if (!result) throw new Error("vide");
        counts[result.dataset.level] = (counts[result.dataset.level] || 0) + 1;
        job.line.replaceWith(result);
      }).catch(function () {
        counts.error += 1;
        job.line.className = "depot-line is-error";
        job.line.querySelector(".small").textContent = "Pas pu être déposé : réessayez, ou utilisez la page « Déposer des documents ».";
      }).then(function () {
        running -= 1;
        if (!running) summary();
        next();
      });
    })();
  }
})();
