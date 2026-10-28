/* NexaMind core UI behaviour: nav, dropdowns, modals, toasts, reveal, counters. */
(function () {
  "use strict";

  function csrfToken() {
    var el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute("content") : "";
  }

  /* ---- CSRF-safe fetch helper ---- */
  window.nmFetch = function (url, options) {
    options = options || {};
    options.headers = options.headers || {};
    options.headers["X-CSRFToken"] = csrfToken();
    options.headers["X-Requested-With"] = "XMLHttpRequest";
    if (options.body && typeof options.body !== "string") {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    } else if (csrfToken()) {
      options.headers["X-CSRFToken"] = csrfToken();
    }
    return fetch(url, options);
  };

  /* ---- Toasts ---- */
  function toast(message, type) {
    type = type || "info";
    var wrap = document.querySelector(".toast-wrap");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.className = "toast-wrap";
      document.body.appendChild(wrap);
    }
    var t = document.createElement("div");
    t.className = "toast " + type;
    t.textContent = message;
    wrap.appendChild(t);
    setTimeout(function () { t.classList.add("hide"); }, 4200);
    setTimeout(function () { t.remove(); }, 4600);
  }
  window.nmToast = toast;

  /* ---- Reveal-on-scroll ---- */
  function observeReveal() {
    var items = document.querySelectorAll("[data-animate]:not(.in-view)");
    if (!("IntersectionObserver" in window)) {
      items.forEach(function (el) { el.classList.add("in-view"); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    items.forEach(function (el) { io.observe(el); });
  }

  /* ---- Count-up animation ---- */
  function runCounters() {
    document.querySelectorAll("[data-count]").forEach(function (el) {
      var target = parseFloat(el.getAttribute("data-count"));
      var suffix = el.getAttribute("data-suffix") || "";
      var duration = 1100;
      var start = null;
      function step(ts) {
        if (!start) start = ts;
        var p = Math.min((ts - start) / duration, 1);
        var eased = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.round(target * eased) + suffix;
        if (p < 1) requestAnimationFrame(step);
        else el.textContent = target + suffix;
      }
      requestAnimationFrame(step);
    });
  }

  function renderProgress() {
    document.querySelectorAll(".progress[data-pct]").forEach(function (bar) {
      var pct = parseInt(bar.getAttribute("data-pct"), 10) || 0;
      requestAnimationFrame(function () {
        var fill = bar.querySelector("span");
        if (fill) fill.style.width = Math.min(pct, 100) + "%";
      });
    });
  }

  /* ---- Dropdowns ---- */
  function closeAllDropdowns(except) {
    document.querySelectorAll(".dropdown.open").forEach(function (d) {
      if (d !== except) d.classList.remove("open");
    });
  }
  document.addEventListener("click", function (e) {
    var trigger = e.target.closest("[data-dropdown-toggle]");
    if (trigger) {
      e.preventDefault();
      e.stopPropagation();
      var wrap = trigger.closest(".dropdown");
      var open = wrap.classList.toggle("open");
      if (!open) closeAllDropdowns();
      if (open) closeAllDropdowns(wrap);
      return;
    }
    closeAllDropdowns();
  });

  /* ---- Mobile nav ---- */
  var menuBtn = document.querySelector(".menu-btn");
  var sidebar = document.querySelector(".sidebar");
  if (menuBtn && sidebar) {
    menuBtn.addEventListener("click", function () { sidebar.classList.toggle("open"); });
    document.addEventListener("click", function (e) {
      if (sidebar.classList.contains("open") && !sidebar.contains(e.target) && !menuBtn.contains(e.target)) {
        sidebar.classList.remove("open");
      }
    });
  }

  /* ---- Modal helpers ---- */
  window.nmOpenModal = function (id) {
    var m = document.getElementById(id);
    if (m) m.classList.add("open");
  };
  window.nmCloseModal = function (id) {
    var m = document.getElementById(id);
    if (m) m.classList.remove("open");
  };
  document.querySelectorAll(".modal-backdrop").forEach(function (m) {
    m.addEventListener("click", function (e) { if (e.target === m) m.classList.remove("open"); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAllDropdowns();
  });

  /* ---- Confirmation dialog ---- */
  window.nmConfirm = function (message, form) {
    if (window.confirm(message)) {
      if (form) { form.submit(); }
      return true;
    }
    return false;
  };

  /* ---- Inline confirm on forms with data-confirm ---- */
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var msg = form.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) {
      e.preventDefault();
      return;
    }
  });

  /* ---- Dynamic status color helpers (used by templates) ---- */
  window.nmStatusMap = {
    done: ["green", "Completed"], in_progress: ["blue", "In progress"],
    blocked: ["red", "Blocked"], todo: ["violet", "To do"]
  };
  window.nmPriMap = {
    low: ["green", "Low"], medium: ["blue", "Medium"],
    high: ["amber", "High"], urgent: ["red", "Urgent"]
  };

  /* ---- Theme toggle (light / dark) ---- */
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  }
  function applyTheme(theme) {
    var t = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("nm-theme", t); } catch (e) {}
  }
  window.nmTheme = { get: currentTheme, set: applyTheme };

  function initThemeToggle() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var next = currentTheme() === "light" ? "dark" : "light";
      applyTheme(next);
      var url = btn.getAttribute("data-theme-url");
      if (url && window.nmFetch) {
        window.nmFetch(url, {
          method: "POST",
          body: new URLSearchParams({ theme: next === "light" ? "light" : "royal" }).toString(),
          headers: { "Content-Type": "application/x-www-form-urlencoded" }
        }).catch(function () {});
      }
    });
  }

  /* ---- Keyboard shortcuts overlay + quick navigation ---- */
  function isTyping(el) {
    if (!el) return false;
    var tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
  }

  function initShortcuts() {
    var help = document.getElementById("kbd-help");
    if (!help) return;
    var nav = {
      d: help.getAttribute("data-dashboard"),
      t: help.getAttribute("data-tasks"),
      c: help.getAttribute("data-calendar"),
      a: help.getAttribute("data-assistant"),
      n: help.getAttribute("data-new-task")
    };
    var pendingG = false;
    var timer = null;

    function show(on) { help.hidden = !on; }

    help.querySelectorAll("[data-kbd-close]").forEach(function (el) {
      el.addEventListener("click", function () { show(false); });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !help.hidden) { show(false); return; }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTyping(e.target)) return;
      var cmdk = document.getElementById("cmdk");
      if (cmdk && !cmdk.hidden) return;

      if (e.key === "?") { e.preventDefault(); show(help.hidden); return; }
      if (!help.hidden) return;

      if (pendingG) {
        pendingG = false;
        var dest = nav[e.key.toLowerCase()];
        if (dest) { e.preventDefault(); window.location.href = dest; }
        return;
      }
      if (e.key === "g") {
        pendingG = true;
        clearTimeout(timer);
        timer = setTimeout(function () { pendingG = false; }, 900);
        return;
      }
      if (e.key === "n" && nav.n) { e.preventDefault(); window.location.href = nav.n; return; }
      if (e.key === "t") {
        var next = currentTheme() === "light" ? "dark" : "light";
        applyTheme(next);
        var btn = document.getElementById("theme-toggle");
        var url = btn && btn.getAttribute("data-theme-url");
        if (url && window.nmFetch) {
          window.nmFetch(url, {
            method: "POST",
            body: new URLSearchParams({ theme: next === "light" ? "light" : "royal" }).toString(),
            headers: { "Content-Type": "application/x-www-form-urlencoded" }
          }).catch(function () {});
        }
      }
    });
  }

  /* ---- Init ---- */
  document.addEventListener("DOMContentLoaded", function () {
    observeReveal();
    renderProgress();
    runCounters();
    initThemeToggle();
    initShortcuts();
    /* global search go */
    var gs = document.getElementById("global-search-input");
    if (gs) {
      gs.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && gs.value.trim()) {
          window.location.href = gs.getAttribute("data-base") + encodeURIComponent(gs.value.trim());
        }
      });
    }
  });
})();