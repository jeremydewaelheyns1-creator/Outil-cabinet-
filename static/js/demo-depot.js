// Démo en ligne seulement (chargé par la page exportée, jamais par l'outil installé) :
// « Déposer des documents » fonctionne dans le navigateur, avec les dossiers fictifs.
// Un XML d'Intervat est lu ici même et rangé (en apparence) sur la bonne ligne ; rien n'est
// enregistré ni envoyé nulle part.
(function () {
  var base = window.DEMO_BASE || "/";
  var form = document.querySelector(".depot-drop form");
  if (!form) return;

  var hint = document.createElement("p");
  hint.className = "alert alert-info small";
  hint.innerHTML = "Démo : essayez avec <a href=\"" + base + "deposer/exemple-declaration-tva.xml\" " +
    "download>une déclaration TVA fictive</a> (téléchargez-la, puis déposez-la ici). " +
    "Rien n'est enregistré.";
  form.parentNode.insertBefore(hint, form);

  var results = document.createElement("section");
  results.className = "card";
  results.hidden = true;
  results.innerHTML = "<h2>Résultat du dépôt</h2><ul class=\"depot-results\"></ul>";
  form.closest(".depot-drop").after(results);

  function money(value) {
    return Number(value).toLocaleString("fr-BE", { minimumFractionDigits: 2 }) + " €";
  }
  function local(node, name) {
    return Array.prototype.filter.call(node.getElementsByTagName("*"), function (e) {
      return e.localName === name;
    });
  }
  function text(node, name) {
    var found = local(node, name);
    return found.length ? found[0].textContent.trim() : "";
  }
  function digits(value) {
    var only = value.split("").filter(function (c) { return c >= "0" && c <= "9"; }).join("");
    return only.length === 9 ? "0" + only : only;
  }
  function line(html) {
    var li = document.createElement("li");
    li.innerHTML = html;
    results.querySelector("ul").appendChild(li);
    results.hidden = false;
  }
  function escape(value) {
    var span = document.createElement("span");
    span.textContent = value;
    return span.innerHTML;
  }

  function readXml(file, content, clients) {
    var xml = new DOMParser().parseFromString(content, "application/xml");
    var root = xml.documentElement ? xml.documentElement.localName : "";
    var item = root === "VATConsignment" ? "VATDeclaration" : root === "IntraConsignment" ? "IntraListing" : "";
    var declaration = item ? local(xml, item)[0] : null;
    if (!declaration) {
      line("⏳ <strong>" + escape(file.name) + "</strong> : pas un fichier Intervat → « À classer ».");
      return;
    }
    var declarant = local(declaration, "Declarant")[0];
    var number = declarant ? digits(text(declarant, "VATNumber")) : "";
    var client = clients.filter(function (c) { return c.number === number; })[0];
    if (!client) {
      line("⏳ <strong>" + escape(file.name) + "</strong> : aucun dossier fictif ne porte ce numéro → « À classer ».");
      return;
    }
    var quarter = text(declaration, "Quarter"), month = text(declaration, "Month");
    var period = (quarter ? "T" + quarter : month + "/") + " " + text(declaration, "Year");
    var amount = "";
    local(declaration, "Amount").forEach(function (a) {
      var grid = a.getAttribute("GridNumber");
      if (grid === "71") amount = money(a.textContent) + " à payer (grille 71)";
      if (grid === "72" && !amount) amount = money(a.textContent) + " à récupérer (grille 72)";
    });
    line("✓ <strong>" + escape(file.name) + "</strong> : " +
      (item === "IntraListing" ? "listing intracommunautaire " : "déclaration TVA ") + escape(period) +
      " classée → <a href=\"" + client.url + "\">" + escape(client.name) + "</a>" +
      (amount ? ", " + amount : "") + ", case « Déposée » cochée. <span class=\"muted\">(Démo : rien n'est enregistré.)</span>");
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    event.stopImmediatePropagation();
    var files = Array.prototype.slice.call(form.querySelector("input[type=file]").files);
    if (!files.length) return;
    results.querySelector("ul").innerHTML = "";
    fetch(base + "deposer/demo-clients.json").then(function (r) { return r.json(); }).then(function (clients) {
      files.forEach(function (file) {
        if (file.name.toLowerCase().endsWith(".xml")) {
          file.text().then(function (content) { readXml(file, content, clients); });
        } else {
          line("⏳ <strong>" + escape(file.name) + "</strong> : dans l'outil installé, les PDF d'Intervat et les cartes " +
            "d'identité sont lus et classés seuls. Dans la démo, ils vont dans « À classer ».");
        }
      });
    });
  }, true);
})();
