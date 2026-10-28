/* Analytics charts (Chart.js) rendered from the server-side report. */
(function () {
  "use strict";
  function ctxOf(id) {
    var el = document.getElementById(id);
    return el ? el.getContext("2d") : null;
  }

  function opts() {
    return {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#a7a3bd", boxWidth: 10, usePointStyle: true } },
        tooltip: { backgroundColor: "rgba(18,18,38,.96)", borderColor: "rgba(212,175,55,.3)", borderWidth: 1, titleColor: "#f2efe6", bodyColor: "#a7a3bd" }
      },
      scales: {
        x: { grid: { color: "rgba(255,255,255,.04)" }, ticks: { color: "#7d7a97", maxTicksLimit: 10 } },
        y: { beginAtZero: true, grid: { color: "rgba(255,255,255,.04)" }, ticks: { color: "#7d7a97", precision: 0 } }
      }
    };
  }

  function build(id, type, labels, main, second) {
    var ctx = ctxOf(id);
    if (!ctx) return;
    new Chart(ctx, {
      type: type,
      data: {
        labels: labels,
        datasets: [
          {
            label: main.label, data: main.data,
            backgroundColor: main.color + "55", borderColor: main.color,
            borderWidth: 2, tension: 0.4, fill: true, pointRadius: 0
          },
          {
            label: second.label, data: second.data,
            backgroundColor: second.color + "22", borderColor: second.color,
            borderWidth: 2, tension: 0.4, pointRadius: 0
          }
        ]
      },
      options: Object.assign(opts(), {
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#a7a3bd", boxWidth: 10, usePointStyle: true } }
        }
      })
    });
  }

  function donut(id, labels, data, colors) {
    var ctx = ctxOf(id);
    if (!ctx) return;
    new Chart(ctx, {
      type: "doughnut",
      data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderWidth: 0, hoverOffset: 6 }] },
      options: { responsive: true, cutout: "66%", plugins: { legend: { position: "bottom", labels: { color: "#a7a3bd", boxWidth: 10, usePointStyle: true } } } }
    });
  }

  function init() {
    var wrapper = document.getElementById("analytics-root");
    if (!wrapper || !window.Chart) return;

    var trend = JSON.parse(wrapper.getAttribute("data-trend") || "{}");
    build("chart-tasks", "line", trend.labels || [],
      { label: "Created", data: trend.created || [], color: "#8b7bff" },
      { label: "Completed", data: trend.completed || [], color: "#d4af37" });

    var wf = JSON.parse(wrapper.getAttribute("data-workflows") || "{}");
    donut("chart-workflows",
      ["Succeeded", "Failed"],
      [wf.succeeded || 0, wf.failed || 0],
      ["#4ade80", "#f87171"]);

    var pieces = JSON.parse(wrapper.getAttribute("data-status") || "{}");
    var labels = { done: "Completed", in_progress: "In progress", blocked: "Blocked", todo: "To do" };
    var colors = { done: "#4ade80", in_progress: "#8b7bff", blocked: "#f87171", todo: "#60a5fa" };
    donut("chart-status",
      Object.keys(pieces).map(function (k) { return labels[k] || k; }),
      Object.values(pieces),
      Object.keys(pieces).map(function (k) { return colors[k] || "#d4af37"; }));
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (window.Chart) init();
  });
})();