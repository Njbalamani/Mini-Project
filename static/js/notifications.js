/* Notifications: auto-dismiss, mark read. */
(function () {
  "use strict";
  document.querySelectorAll(".notif-item form.js-mark-read").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var item = form.closest(".notif-item");
      var url = form.getAttribute("action");
      var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
      fetch(url, {
        method: "POST", headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" }
      }).then(function (r) { return r.json(); }).then(function (res) {
        item.classList.remove("unread");
        var dot = item.querySelector(".n-dot");
        if (dot) dot.style.background = "transparent";
        var count = document.querySelectorAll("[data-notif-count]");
        count.forEach(function (el) { el.textContent = res.unread || 0; if (el.classList.contains("badge")) el.style.display = res.unread ? "" : "none"; });
        var url2 = item.getAttribute("data-url");
        if (url2) window.location.href = url2;
        else if (res.unread === 0) window.location.reload();
      });
    });
  });

  document.querySelectorAll(".bell-item[data-url]").forEach(function (item) {
    item.addEventListener("click", function (e) {
      e.preventDefault();
      var url = item.getAttribute("data-url");
      var markUrl = item.getAttribute("data-mark");
      if (markUrl) {
        var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
        document.querySelectorAll(".dropdown").forEach(function (d) { d.classList.remove("open"); });
        fetch(markUrl, {
          method: "POST", headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" }
        }).finally(function () { window.location.href = url; });
      } else {
        window.location.href = url;
      }
    });
  });

  /* ---- Live notifications over WebSocket ---- */
  function bumpCount() {
    var count = document.querySelectorAll("[data-notif-count]");
    count.forEach(function (el) {
      var current = parseInt(el.textContent || "0", 10) || 0;
      el.textContent = current + 1;
      if (el.classList.contains("badge")) el.style.display = "";
    });
    var bell = document.querySelector(".topbar-actions .icon-btn .dot");
    if (bell) bell.style.display = "";
  }

  function prependBellItem(data) {
    var list = document.querySelector(".topbar-actions .dropdown-menu .dropdown-head + .bell-item") ||
               document.querySelector(".topbar-actions .dropdown-menu .dropdown-head");
    var target = document.querySelector(".topbar-actions .dropdown-menu");
    if (!target || !list) return;
    var isEmpty = target.querySelector(".center.small.muted");
    if (isEmpty) isEmpty.remove();
    var a = document.createElement("a");
    a.className = "bell-item";
    a.href = data.url || "";
    var label = data.type ? data.type.replace(/_/g, " ") : "notification";
    a.innerHTML =
      '<span class="small gold">' + label + ':</span> ' +
      '<span class="n-title"></span>';
    a.querySelector(".n-title").textContent = data.title || data.message || "";
    var insertBefore = target.querySelector(".dropdown-head .bell-item") || target.querySelector(".bell-item");
    target.insertBefore(a, insertBefore ? insertBefore.nextSibling : (target.querySelector(".dropdown-divider") || null));
    a.addEventListener("click", function (e) {
      e.preventDefault();
      if (!data.url) return;
      document.querySelectorAll(".dropdown").forEach(function (d) { d.classList.remove("open"); });
      window.location.href = data.url;
    });
  }

  window.nmNotifications = {
    push: function (data) {
      bumpCount();
      prependBellItem(data);
      if (window.nmToast) {
        var text = (data.title || "") + (data.message && data.message !== data.title ? " — " + data.message : "");
        window.nmToast(text || "New notification", data.level || "info");
      }
    }
  };

  (function connectLive() {
    if (!document.body || !document.querySelector(".topbar-actions")) return;
    if (window.WebSocket) {
      var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      var ws = new WebSocket(proto + "//" + window.location.host + "/ws/notifications/");
      ws.onmessage = function (evt) {
        var data;
        try { data = JSON.parse(evt.data); } catch (e) { return; }
        if (!data || data.key !== "nm-notif") return;
        if (window.nmNotifications) window.nmNotifications.push(data);
      };
      ws.onclose = function () { setTimeout(connectLive, 4000); };
    }
  })();
})();