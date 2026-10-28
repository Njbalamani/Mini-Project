/* Drag-and-drop rescheduling for the calendar month grid.
 * Events carry data-move-url; day cells carry data-drop-date. Dropping an
 * event on another day POSTs the new date and moves the chip optimistically. */
(function () {
  function getCookie(name) {
    var match = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return match ? decodeURIComponent(match.pop()) : '';
  }

  var dragged = null;
  var origin = null;

  document.querySelectorAll('.cal-event[draggable="true"]').forEach(function (chip) {
    chip.addEventListener('dragstart', function (e) {
      dragged = chip;
      origin = chip.closest('.cal-cell');
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', chip.dataset.eventId); } catch (err) {}
      chip.classList.add('dragging');
    });
    chip.addEventListener('dragend', function () {
      chip.classList.remove('dragging');
      document.querySelectorAll('.cal-cell.drop-target').forEach(function (cell) {
        cell.classList.remove('drop-target');
      });
      dragged = null;
    });
  });

  document.querySelectorAll('.cal-cell[data-drop-date]').forEach(function (cell) {
    cell.addEventListener('dragover', function (e) {
      if (!dragged) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      cell.classList.add('drop-target');
    });
    cell.addEventListener('dragleave', function () {
      cell.classList.remove('drop-target');
    });
    cell.addEventListener('drop', function (e) {
      e.preventDefault();
      cell.classList.remove('drop-target');
      if (!dragged || cell === origin) return;
      var chip = dragged;
      var moveUrl = chip.dataset.moveUrl;
      var newDate = cell.dataset.dropDate;

      var body = new URLSearchParams();
      body.append('date', newDate);

      fetch(moveUrl, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCookie('csrftoken'),
          'X-Requested-With': 'XMLHttpRequest',
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: body.toString(),
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.data.ok) {
            throw new Error(res.data.error || 'Move failed');
          }
          var target = cell.querySelector('.cal-events');
          if (target) target.appendChild(chip);
        })
        .catch(function () {
          window.location.reload();
        });
    });
  });
})();
