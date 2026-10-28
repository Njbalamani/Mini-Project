/* Dashboard charts (Chart.js). Everything is rendered from server data. */
(function () {
  "use strict";
  function safeChart(ctx, cfg) {
    if (!window.Chart) return;
    try { return new Chart(ctx, cfg); } catch (err) { console.error("Chart error:", err); }
  }

  function fmt(n) {
    var v = Number(n) || 0;
    return v.toLocaleString();
  }

  function sparkOptions() {
    return {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "rgba(18,18,38,.96)", borderColor: "rgba(212,175,55,.3)",
          borderWidth: 1, titleColor: "#f2efe6", bodyColor: "#a7a3bd"
        }
      },
      scales: {
        x: { grid: { color: "rgba(255,255,255,.04)" }, ticks: { color: "#7d7a97", maxTicksLimit: 8 } },
        y: { beginAtZero: true, grid: { color: "rgba(255,255,255,.04)" }, ticks: { color: "#7d7a97", precision: 0 } }
      }
    };
  }

  function initProductivity() {
    var el = document.getElementById("chart-trend");
    if (!el) return;
    var data = JSON.parse(el.getAttribute("data-chart") || "{}");
    safeChart(ctxOf(el), {
      type: "line",
      data: {
        labels: data.labels || [],
        datasets: [
          {
            label: "Created", data: data.created || [],
            borderColor: "#8b7bff", backgroundColor: "rgba(139,123,255,.18)",
            fill: true, tension: 0.42, borderWidth: 2, pointRadius: 0, pointHoverRadius: 5,
            pointBackgroundColor: "#8b7bff"
          },
          {
            label: "Completed", data: data.completed || [],
            borderColor: "#d4af37", backgroundColor: "rgba(212,175,55,.12)",
            fill: true, tension: 0.42, borderWidth: 2, pointRadius: 0, pointHoverRadius: 5,
            pointBackgroundColor: "#d4af37"
          }
        ]
      },
      options: Object.assign(sparkOptions(), {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { labels: { color: "#a7a3bd", boxWidth: 10 } } }
      })
    });
  }

  function initStatusDonut() {
    var el = document.getElementById("chart-status");
    if (!el) return;
    var data = JSON.parse(el.getAttribute("data-chart") || "{}");
    var labels = { done: "Completed", in_progress: "In progress", blocked: "Blocked", todo: "To do" };
    var colors = { done: "#4ade80", in_progress: "#8b7bff", blocked: "#f87171", todo: "#60a5fa" };
    var ds = Object.keys(data).filter(function (k) { return data[k] > 0; });
    safeChart(ctxOf(el), {
      type: "doughnut",
      data: {
        labels: ds.map(function (k) { return labels[k] || k; }),
        datasets: [{
          data: ds.map(function (k) { return data[k]; }),
          backgroundColor: ds.map(function (k) { return colors[k] || "#d4af37"; }),
          borderWidth: 0, hoverOffset: 6
        }]
      },
      options: {
        responsive: true, cutout: "68%",
        plugins: { legend: { position: "bottom", labels: { color: "#a7a3bd", boxWidth: 10, usePointStyle: true } } }
      }
    });
  }

  function ctxOf(el) {
    if (el.tagName.toLowerCase() !== "canvas") {
      var c = document.createElement("canvas");
      el.appendChild(c);
      return c.getContext("2d");
    }
    return el.getContext("2d");
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!window.Chart) return;
    initProductivity();
    initStatusDonut();
  });
})();