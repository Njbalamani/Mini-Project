/* AI Assistant chat controller: streaming-style send, actions, feedback. */
(function () {
  "use strict";
  var form = document.getElementById("chat-form");
  if (!form) return;

  var input = document.getElementById("chat-input");
  var messagesEl = document.getElementById("chat-messages");
  var sendUrl = form.getAttribute("data-send-url");
  var actionUrl = form.getAttribute("data-action-url");
  var configBtn = document.getElementById("ai-config-btn");

  function esc(s) {
    var div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  function fmtTime(d) { return d; }

  function addMsg(role, content, metaTime) {
    var row = document.createElement("div");
    row.className = "msg " + role;
    row.setAttribute("data-animate", "");
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    if (Array.isArray(content)) {
      var lines = content.map(function (l) { return esc(l); }).join("\n");
      bubble.textContent = content.join("\n");
    } else {
      bubble.textContent = content;
      bubble.style.whiteSpace = "pre-wrap";
    }
    row.appendChild(bubble);
    var meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = metaTime || new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    row.appendChild(meta);
    messagesEl.appendChild(row);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    requestAnimationFrame(function () { row.classList.add("in-view"); });
    return row;
  }

  function addTyping() {
    var row = document.createElement("div");
    row.className = "msg assistant";
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
    row.appendChild(bubble);
    messagesEl.appendChild(row);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return row;
  }

  function addActionChips(msgRow, actions) {
    if (!actions || !actions.length) return;
    var wrap = document.createElement("div");
    wrap.className = "chip-actions";
    actions.forEach(function (action) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      var labels = {
        create_task: "Approve task", create_event: "Approve event",
        create_workflow: "Approve workflow", none: "OK"
      };
      chip.textContent = labels[action.type] || "Approve action";
      chip.addEventListener("click", function () {
        chip.disabled = true;
        chip.style.opacity = ".5";
        nmFetch(actionUrl, {
          method: "POST", body: { action: action }
        }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (res) {
            if (res.ok && res.j.ok) {
              chip.textContent = res.j.label;
              chip.classList.add("ok");
              chip.style.background = "rgba(74,222,128,.2)";
              chip.style.borderColor = "#4ade80";
              chip.style.color = "#4ade80";
              var go = document.createElement("a");
              go.className = "chip";
              go.href = res.j.url;
              go.textContent = "Open";
              chip.parentNode.appendChild(go);
              nmToast(res.j.label, "success");
            } else {
              chip.disabled = false;
              chip.style.opacity = "1";
              nmToast((res.j && res.j.error) || "Action failed", "error");
            }
          });
      });
      wrap.appendChild(chip);
    });
    var bubble = msgRow.querySelector(".bubble");
    bubble.parentNode.insertBefore(wrap, bubble.nextSibling);
  }

  function addLinkChip(msgRow, link) {
    if (!link || !link.url) return;
    var wrap = document.createElement("div");
    wrap.className = "chip-actions";
    var a = document.createElement("a");
    a.className = "chip";
    a.href = link.url;
    a.textContent = link.label || "Open";
    wrap.appendChild(a);
    var bubble = msgRow.querySelector(".bubble");
    bubble.parentNode.insertBefore(wrap, bubble.nextSibling);
  }

  function addFeedback(msgRow, msgId) {
    var wrap = document.createElement("div");
    wrap.className = "chip-actions";
    wrap.style.paddingLeft = "0";
    ["Helpful", "Not helpful"].forEach(function (label, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = label;
      b.addEventListener("click", function () {
        nmFetch("/assistant/m/" + msgId + "/feedback/", {
          method: "POST", body: new URLSearchParams({ rating: i === 0 ? "1" : "-1" })
        });
        wrap.remove();
        nmToast(i === 0 ? "Thanks — the model learns from this." : "Noted — the model will adapt.", "info");
      });
      wrap.appendChild(b);
    });
    var teach = document.createElement("button");
    teach.type = "button";
    teach.className = "chip";
    teach.textContent = "Teach";
    teach.addEventListener("click", function () {
      var intent = window.prompt("What should I have understood? (e.g. create_task, create_event, list_tasks, list_events, summarize, find, keywords, sentiment, group, greeting, thanks, help, smalltalk)");
      if (!intent) return;
      nmFetch("/assistant/m/" + msgId + "/correction/", {
        method: "POST", body: new URLSearchParams({ intent: intent.trim() })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j && j.ok) {
          nmToast("Learned: “" + j.intent + "”.", "success");
        } else {
          nmToast((j && j.error) || "Could not learn that.", "error");
        }
      });
    });
    wrap.appendChild(teach);
    var bubble = msgRow.querySelector(".bubble");
    bubble.parentNode.insertBefore(wrap, bubble.nextSibling);
  }

  /* ---- SSE streaming for assistant replies ---- */
  function streamSupported() {
    return "ReadableStream" in window && "TextDecoder" in window && window.nmFetch;
  }

  function makeAssistantRow(metaTime) {
    var row = document.createElement("div");
    row.className = "msg assistant";
    row.setAttribute("data-animate", "");
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.style.whiteSpace = "pre-wrap";
    row.appendChild(bubble);
    var meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = metaTime || new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    row.appendChild(meta);
    messagesEl.appendChild(row);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    requestAnimationFrame(function () { row.classList.add("in-view"); });
    return row;
  }

  function postNonStreaming(text, typing, payload) {
    nmFetch(sendUrl, { method: "POST", body: payload })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (res) {
        if (res.assistant_message) {
          typing.remove();
          var row = makeAssistantRow(res.assistant_message.created_at);
          row.querySelector(".bubble").textContent = res.assistant_message.content;
          addActionChips(row, res.assistant_message.actions);
          addLinkChip(row, res.assistant_message.link);
          addFeedback(row, res.assistant_message.id);
          if (res.action_errors && res.action_errors.length) {
            nmToast("Some proposed actions were not valid: " + res.action_errors.join("; "), "warning");
          }
        } else if (res.configured === false) {
          typing.remove();
          addMsg("assistant", "NexaMind is not connected to an AI provider yet.\n\n" + (res.error || "") + "\n\nYou can enable the offline demo or add your API key in environment settings -> AI preferences.");
          if (configBtn) configBtn.style.display = "inline-flex";
        } else {
          typing.remove();
          addMsg("assistant", "The AI provider could not complete your request.\n\n" + (res.error || "Unknown error"));
        }
      })
      .catch(function () {
        typing.remove();
        addMsg("assistant", "Unable to reach the server. Please try again.");
      });
  }

  function streamTurn(text, typing, payload) {
    var resp;
    nmFetch(sendUrl, {
      method: "POST",
      headers: { "Accept": "text/event-stream" },
      body: payload
    }).then(function (r) {
      resp = r;
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (j) { throw new Error(j.error || ("HTTP " + r.status)); });
      }
      var ctype = (r.headers.get("content-type") || "");
      if (ctype.indexOf("text/event-stream") === -1) {
        return r.json().catch(function () { return {}; }).then(function (j) { postNonStreaming(text, typing, payload); return null; });
      }
      typing.remove();
      var reader = r.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var buffer = "";
      var row = null;
      var bubble = null;
      var msgId = null;
      var actions = [];
      var done = false;
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) {
            if (!done && row === null) { addMsg("assistant", "(no content returned)"); }
            return;
          }
          buffer += decoder.decode(res.value, { stream: true });
          var events = buffer.split("\n\n");
          buffer = events.pop();
          events.forEach(function (evt) {
            if (evt.indexOf("data:") !== 0) return;
            var data;
            try { data = JSON.parse(evt.slice(5).trim()); } catch (e) { return; }
            if (data.type === "delta") {
              if (!row) { row = makeAssistantRow(); bubble = row.querySelector(".bubble"); }
              bubble.textContent += data.content || "";
              messagesEl.scrollTop = messagesEl.scrollHeight;
            } else if (data.type === "error") {
              done = true;
              if (data.configured === false) {
                addMsg("assistant", "NexaMind is not connected to an AI provider yet.\n\n" + (data.message || "") + "\n\nYou can enable the offline demo or add your API key in environment settings -> AI preferences.");
                if (configBtn) configBtn.style.display = "inline-flex";
              } else {
                addMsg("assistant", "The AI provider could not complete your request.\n\n" + (data.message || "Unknown error"));
              }
            } else if (data.type === "done") {
              done = true;
              msgId = data.assistant_message && data.assistant_message.id;
              actions = (data.assistant_message && data.assistant_message.actions) || [];
              if (!row) { row = makeAssistantRow(data.assistant_message ? data.assistant_message.created_at : null); bubble = row.querySelector(".bubble"); }
              if (data.assistant_message && data.assistant_message.content) { bubble.textContent = data.assistant_message.content; }
              messagesEl.scrollTop = messagesEl.scrollHeight;
              addActionChips(row, actions);
              addLinkChip(row, data.assistant_message && data.assistant_message.link);
              if (msgId) addFeedback(row, msgId);
              if (data.action_errors && data.action_errors.length) {
                nmToast("Some proposed actions were not valid: " + data.action_errors.join("; "), "warning");
              }
            }
          });
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      typing.remove();
      addMsg("assistant", "Unable to reach the server. Please try again.\n\n" + (err.message || ""));
    });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    if (input.hasAttribute("disabled")) return;

    addMsg("user", text);
    input.value = "";
    input.setAttribute("disabled", "disabled");
    var typing = addTyping();
    var payload = new URLSearchParams({ message: text, stream: "1" });

    function restore() { input.removeAttribute("disabled"); input.focus(); }

    if (streamSupported()) {
      streamTurn(text, typing, payload).then(restore, restore);
    } else {
      postNonStreaming(text, typing, payload);
      setTimeout(restore, 100);
    }
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
})();