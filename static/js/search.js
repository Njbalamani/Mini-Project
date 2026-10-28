/* NexaMind command palette: Ctrl/Cmd+K unified workspace search. */
(function () {
  "use strict";

  var root, input, results, allLink, backdrop;
  var items = [];
  var active = -1;
  var timer = null;
  var seq = 0;
  var quickHtml = "";

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : s;
    return d.innerHTML;
  }

  function open() {
    if (!root) return;
    root.hidden = false;
    document.body.style.overflow = "hidden";
    setTimeout(function () { input.focus(); input.select(); }, 20);
  }

  function close() {
    if (!root) return;
    root.hidden = true;
    document.body.style.overflow = "";
  }

  function isOpen() { return root && !root.hidden; }

  function setActive(i) {
    var rows = results.querySelectorAll(".cmdk-item");
    if (!rows.length) { active = -1; return; }
    if (i < 0) i = rows.length - 1;
    if (i >= rows.length) i = 0;
    active = i;
    rows.forEach(function (r, idx) { r.classList.toggle("active", idx === i); });
    rows[i].scrollIntoView({ block: "nearest" });
  }

  function render(data, q) {
    items = [];
    if (!q) {
      results.innerHTML = quickHtml || '<div class="cmdk-hint">Type to search across your workspace…</div>';
      active = -1;
      return;
    }
    if (!data || !data.groups || !data.groups.length) {
      results.innerHTML = '<div class="cmdk-hint">No matches for “' + esc(q) + '”.</div>';
      return;
    }
    var html = "";
    data.groups.forEach(function (g) {
      html += '<div class="cmdk-group"><div class="cmdk-group-label">' + esc(g.label) + "</div>";
      g.hits.forEach(function (h) {
        var idx = items.length;
        items.push(h);
        html += '<a class="cmdk-item" data-idx="' + idx + '" href="' + esc(h.url) + '">' +
          '<span class="cmdk-badge">' + esc(g.label) + "</span>" +
          '<span class="cmdk-text"><span class="cmdk-title">' + esc(h.title) + "</span>" +
          (h.subtitle ? '<span class="cmdk-sub">' + esc(h.subtitle) + "</span>" : "") +
          "</span></a>";
      });
      html += "</div>";
    });
    results.innerHTML = html;
    active = -1;
  }

  function doSearch(q) {
    var mySeq = ++seq;
    if (window.nmFetch) {
      window.nmFetch(input.getAttribute("data-url") + "?q=" + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (data) { if (mySeq === seq) render(data, q); })
        .catch(function () { if (mySeq === seq) render(null, q); });
    }
  }

  function onInput() {
    var q = input.value.trim();
    if (allLink) allLink.href = input.getAttribute("data-all-url") + encodeURIComponent(q);
    if (timer) clearTimeout(timer);
    if (!q) { render(null, ""); return; }
    timer = setTimeout(function () { doSearch(q); }, 180);
  }

  function onKey(e) {
    if (e.key === "Escape") { close(); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); return; }
    if (e.key === "Enter") {
      var rows = results.querySelectorAll(".cmdk-item");
      if (active >= 0 && rows[active]) { e.preventDefault(); window.location.href = rows[active].getAttribute("href"); }
      else if (input.value.trim() && allLink) { e.preventDefault(); window.location.href = allLink.href; }
    }
  }

  function init() {
    root = document.getElementById("cmdk");
    if (!root) return;
    input = document.getElementById("cmdk-input");
    results = document.getElementById("cmdk-results");
    allLink = document.getElementById("cmdk-all");
    backdrop = root.querySelector("[data-cmdk-close]");
    quickHtml = results.innerHTML;

    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        isOpen() ? close() : open();
      }
    });

    if (backdrop) backdrop.addEventListener("click", close);
    input.addEventListener("input", onInput);
    input.addEventListener("keydown", onKey);

    /* Clicking the topbar search opens the palette instead of typing inline. */
    var top = document.getElementById("global-search-input");
    if (top) {
      top.setAttribute("readonly", "readonly");
      top.addEventListener("focus", function () { top.blur(); open(); });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
