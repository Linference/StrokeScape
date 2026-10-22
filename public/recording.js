/* Record the shared Canvas directly. No desktop capture and no screenshots. */
(function (root) {
  'use strict';
  root.startStrokeRecording = function (work, fps) {
    const state = root.recordingState = { status: 'starting', elapsedMs: 0, frames: 0 };
    const canvas = document.getElementById('c');
    const padded = { ...work, width: work.width + work.width % 2, height: work.height + work.height % 2 };
    const renderer = new StrokeRenderer(canvas, padded, { cacheLimit: 0 });
    renderer.render(0);
    const candidates = ['video/mp4;codecs=avc1', 'video/webm;codecs=vp8'];
    const mime = candidates.find(type => MediaRecorder.isTypeSupported(type));
    if (!mime || !canvas.captureStream) throw new Error('当前浏览器不支持画布视频录制，请选择逐帧导出。');
    // Request capture after each render to avoid aliasing two independent clocks.
    const stream = canvas.captureStream(0);
    const track = stream.getVideoTracks()[0];
    if (typeof track.requestFrame !== 'function') {
      stream.getTracks().forEach(item => item.stop());
      renderer.dispose();
      throw new Error('当前浏览器不支持画布帧捕获，请选择逐帧导出。');
    }
    const recorder = new MediaRecorder(stream, { mimeType: mime,
      videoBitsPerSecond: Math.max(4000000, Math.min(40000000, padded.width * padded.height * fps * 0.16)) });
    state.mime = mime;
    let uploads = Promise.resolve(), pendingBytes = 0, cancelled = false, animation = 0, stopTimer = 0;
    let uploadError = null, recorderError = null, previousFrame = -1, started = 0;
    const cleanup = () => {
      cancelAnimationFrame(animation); clearTimeout(stopTimer);
      stream.getTracks().forEach(track => track.stop());
      renderer.dispose();
    };
    const stop = () => { if (recorder.state !== 'inactive') recorder.stop(); };
    root.cancelStrokeRecording = () => { cancelled = true; cancelAnimationFrame(animation); clearTimeout(stopTimer); stop(); };
    recorder.ondataavailable = event => {
      if (!event.data.size || cancelled || uploadError) return;
      pendingBytes += event.data.size;
      if (pendingBytes > 64 * 1024 * 1024) {
        uploadError = new Error('本机视频写入跟不上录制速度，请降低帧率或分辨率。'); stop(); return;
      }
      uploads = uploads.then(async () => {
        if (cancelled || uploadError) return;
        try {
          const response = await fetch('chunk', { method: 'POST', body: event.data });
          if (!response.ok) throw new Error('视频数据写入失败：' + response.status);
        } finally { pendingBytes -= event.data.size; }
      }).catch(error => { uploadError = error; stop(); });
    };
    recorder.onerror = event => { recorderError = event.error || new Error('浏览器视频编码失败'); stop(); };
    recorder.onstop = async () => {
      state.status = 'flushing';
      try {
        await uploads;
        if (cancelled) state.status = 'cancelled';
        else if (uploadError || recorderError) throw uploadError || recorderError;
        else state.status = 'done';
      } catch (error) { state.status = 'failed'; state.error = String(error.message || error); }
      finally { cleanup(); }
    };
    recorder.onstart = () => {
      if (cancelled) { stop(); return; }
      state.status = 'recording';
      const tick = now => {
        if (cancelled || uploadError || recorderError || recorder.state === 'inactive') return;
        const elapsed = Math.min(work.durationMs, now - started);
        const frame = Math.floor(elapsed * fps / 1000);
        if (frame !== previousFrame || elapsed >= work.durationMs) {
          renderer.render(elapsed); track.requestFrame(); previousFrame = frame; state.frames++;
        }
        state.elapsedMs = elapsed;
        if (elapsed >= work.durationMs) {
          // Let the capture track encode the completed painting before stopping.
          stopTimer = setTimeout(stop, Math.max(120, 2000 / fps));
        } else animation = requestAnimationFrame(tick);
      };
      renderer.render(0); track.requestFrame();
      animation = requestAnimationFrame(tick);
    };
    try { started = performance.now(); recorder.start(1000); }
    catch (error) { cleanup(); throw error; }
    return { mime, width: padded.width, height: padded.height };
  };
})(window);
