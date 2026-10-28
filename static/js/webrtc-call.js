/* Browser WebRTC video calling with manual (copy/paste) signaling.
 * Camera/microphone access is requested through getUserMedia, which the browser
 * gates behind an explicit permission prompt. No media or signaling data is sent
 * to the server; the two peers exchange the offer/answer out of band. */
(function () {
  var root = document.querySelector('[data-webrtc]');
  if (!root || !window.RTCPeerConnection) return;

  var localVideo = root.querySelector('[data-local-video]');
  var remoteVideo = root.querySelector('[data-remote-video]');
  var status = root.querySelector('[data-call-status]');
  var errorBox = root.querySelector('[data-call-error]');

  var pc = null;
  var localStream = null;

  var ICE_CONFIG = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] };

  function setStatus(text) { if (status) status.textContent = text; }
  function setError(text) { if (errorBox) errorBox.textContent = text || ''; }

  function newConnection() {
    pc = new RTCPeerConnection(ICE_CONFIG);
    if (localStream) {
      localStream.getTracks().forEach(function (track) { pc.addTrack(track, localStream); });
    }
    pc.addEventListener('track', function (event) {
      if (remoteVideo.srcObject !== event.streams[0]) {
        remoteVideo.srcObject = event.streams[0];
        setStatus('Connected');
      }
    });
    pc.addEventListener('iceconnectionstatechange', function () {
      setStatus('ICE: ' + pc.iceConnectionState);
    });
    return pc;
  }

  function waitForIce(pc) {
    return new Promise(function (resolve) {
      if (pc.iceGatheringState === 'complete') return resolve();
      var check = function () {
        if (pc.iceGatheringState === 'complete') {
          pc.removeEventListener('icegatheringstatechange', check);
          resolve();
        }
      };
      pc.addEventListener('icegatheringstatechange', check);
      setTimeout(resolve, 2500);
    });
  }

  root.querySelector('[data-call-start]').addEventListener('click', function () {
    setError('');
    navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      .then(function (stream) {
        localStream = stream;
        localVideo.srcObject = stream;
        setStatus('Camera on');
      })
      .catch(function (err) {
        setError('Camera/microphone permission denied: ' + err.message);
      });
  });

  root.querySelector('[data-call-create-offer]').addEventListener('click', function () {
    if (!localStream) { setError('Start your camera first.'); return; }
    newConnection();
    pc.createOffer()
      .then(function (offer) { return pc.setLocalDescription(offer); })
      .then(function () { return waitForIce(pc); })
      .then(function () {
        root.querySelector('[data-call-offer]').value = JSON.stringify(pc.localDescription);
        setStatus('Offer ready — copy it to your peer');
      })
      .catch(function (e) { setError(e.message); });
  });

  root.querySelector('[data-call-accept-answer]').addEventListener('click', function () {
    var raw = root.querySelector('[data-call-answer-input]').value.trim();
    if (!pc || !raw) { setError('Create an offer first, then paste the answer.'); return; }
    pc.setRemoteDescription(JSON.parse(raw))
      .then(function () { setStatus('Negotiating…'); })
      .catch(function (err) { setError(err.message); });
  });

  root.querySelector('[data-call-create-answer]').addEventListener('click', function () {
    setError('');
    var offerRaw = root.querySelector('[data-call-remote-offer]').value;
    if (!offerRaw) { setError('Paste the caller\'s offer first.'); return; }
    if (!localStream) { setError('Start your camera before answering.'); return; }
    newConnection();
    pc.setRemoteDescription(JSON.parse(offerRaw))
      .then(function () { return pc.createAnswer(); })
      .then(function (answer) { return pc.setLocalDescription(answer); })
      .then(function () { return waitForIce(pc); })
      .then(function () {
        root.querySelector('[data-call-answer-out]').value = JSON.stringify(pc.localDescription);
        setStatus('Answer ready — send it back');
      })
      .catch(function (err) { setError(err.message); });
  });

  root.querySelector('[data-call-hangup]').addEventListener('click', function () {
    if (pc) { pc.close(); pc = null; }
    if (localStream) { localStream.getTracks().forEach(function (t) { t.stop(); }); localStream = null; }
    localVideo.srcObject = null;
    remoteVideo.srcObject = null;
    setStatus('Idle');
  });
})();
