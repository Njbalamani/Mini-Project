/* Tasks: kanban drag & drop status updates. */
(function () {
  "use strict";
  var cards = document.querySelectorAll(".kanban-card[data-task-id]");
  var cols = document.querySelectorAll(".kanban-col[data-status]");
  var dragging = null;

  cards.forEach(function (card) {
    card.setAttribute("draggable", "true");
    card.addEventListener("dragstart", function () {
      dragging = card;
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", function () {
      card.classList.remove("dragging");
      dragging = null;
    });
  });

  cols.forEach(function (col) {
    col.addEventListener("dragover", function (e) { e.preventDefault(); });
    col.addEventListener("drop", function () {
      if (!dragging) return;
      var taskId = dragging.getAttribute("data-task-id");
      var boardId = col.getAttribute("data-board-id");
      var nextStatus = col.getAttribute("data-status");
      var target = col.querySelector(".kanban-cards");
      target.appendChild(dragging);
      dragging.classList.remove("dragging");

      var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
      var fd = new FormData();
      fd.append("status", nextStatus);
      fd.append("next", window.location.pathname + window.location.search);
      fetch("/tasks/" + taskId + "/status/", {
        method: "POST", headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
        body: fd
      }).then(function (r) { return r.json(); }).then(function (res) {
        if (res.ok) { nmToast("Task moved to " + nextStatus.replace("_", " "), "success"); }
        else { nmToast(res.error || "Update failed", "error"); window.location.reload(); }
      }).catch(function () { window.location.reload(); });
    });
  });

  /* Bulk selection toolbar (list & board views). */
  var bulkForm = document.getElementById("bulk-form");
  var checks = document.querySelectorAll(".bulk-check");
  if (!bulkForm || !checks.length) return;

  var bar = bulkForm;
  var countEl = document.getElementById("bulk-count");
  var idsHolder = document.getElementById("bulk-ids");
  var selectAll = document.getElementById("bulk-select-all");
  var actionSel = document.getElementById("bulk-action");
  var prioritySel = document.getElementById("bulk-priority");
  var dueInput = document.getElementById("bulk-due");

  function selected() {
    return Array.prototype.filter.call(checks, function (c) { return c.checked; });
  }

  function refresh() {
    var n = selected().length;
    if (countEl) countEl.textContent = n;
    bar.hidden = n === 0;
    if (selectAll) {
      selectAll.checked = n > 0 && n === checks.length;
      selectAll.indeterminate = n > 0 && n < checks.length;
    }
  }

  checks.forEach(function (c) { c.addEventListener("change", refresh); });
  if (selectAll) {
    selectAll.addEventListener("change", function () {
      checks.forEach(function (c) { c.checked = selectAll.checked; });
      refresh();
    });
  }
  if (actionSel) {
    actionSel.addEventListener("change", function () {
      var v = actionSel.value;
      if (prioritySel) prioritySel.hidden = v !== "priority";
      if (dueInput) dueInput.hidden = actionSel.value !== "reschedule";
    });
  }
  var clearBtn = document.getElementById("bulk-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      checks.forEach(function (c) { c.checked = false; });
      refresh();
    });
  }

  bulkForm.addEventListener("submit", function () {
    var action = actionSel ? actionSel.value : "";
    if (action === "delete") {
      var n = selected().length;
      if (!window.confirm("Delete " + n + " task(s)? This cannot be undone.")) {
        event.preventDefault();
        return;
      }
    }
    idsHolder.innerHTML = "";
    selected().forEach(function (c) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = "ids";
      input.value = c.value;
      idsHolder.appendChild(input);
    });
  });
})();