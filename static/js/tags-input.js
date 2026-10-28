/* Tag autocomplete: shows clickable suggestions under a comma-separated input.
 * The input carries a JSON array in its data-suggestions attribute. */
(function () {
  document.querySelectorAll('input[data-suggestions]').forEach(function (input) {
    var suggestions;
    try { suggestions = JSON.parse(input.dataset.suggestions || '[]'); } catch (e) { return; }
    if (!suggestions.length) return;

    var box = document.createElement('div');
    box.className = 'tag-suggest';
    input.insertAdjacentElement('afterend', box);

    function current() {
      return input.value.split(',').map(function (s) { return s.trim().toLowerCase(); }).filter(Boolean);
    }

    function render() {
      var used = current();
      box.innerHTML = '';
      var shown = 0;
      suggestions.forEach(function (name) {
        if (used.indexOf(name.toLowerCase()) !== -1) return;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'tag-suggest-chip';
        btn.textContent = name;
        btn.addEventListener('click', function () { add(name); });
        box.appendChild(btn);
        shown += 1;
      });
      box.style.display = shown ? 'flex' : 'none';
    }

    function add(name) {
      var parts = input.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      if (parts.map(function (s) { return s.toLowerCase(); }).indexOf(name.toLowerCase()) === -1) {
        parts.push(name);
      }
      input.value = parts.join(', ');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    }

    input.addEventListener('input', render);
    render();
  });
})();
