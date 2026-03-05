/* global chrome */

const fileInput = document.getElementById("file-input");
const fileName = document.getElementById("file-name");
const summarySection = document.getElementById("summary-section");
const loadSection = document.getElementById("load-section");
const progressSection = document.getElementById("progress-section");
const logSection = document.getElementById("log-section");
const progressBar = document.getElementById("progress-bar");
const progressText = document.getElementById("progress-text");
const logEl = document.getElementById("log");
const startBtn = document.getElementById("start-btn");
const pauseBtn = document.getElementById("pause-btn");
const resumeBtn = document.getElementById("resume-btn");
const stopBtn = document.getElementById("stop-btn");
const delayInput = document.getElementById("delay-input");
const notOnPhotos = document.getElementById("not-on-photos");
const mainContent = document.getElementById("main-content");

let duplicatesData = null;
let deleteQueue = [];

// Check if we're on photos.google.com
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const tab = tabs[0];
  if (!tab || !tab.url || !tab.url.startsWith("https://photos.google.com")) {
    notOnPhotos.style.display = "block";
    mainContent.style.display = "none";
  }
});

// Restore state from storage
chrome.storage.local.get(["deletionState"], (result) => {
  if (result.deletionState) {
    const state = result.deletionState;
    if (state.status === "paused" || state.status === "running") {
      showProgress(state);
    }
  }
});

// Listen for progress updates from background
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "deletion-progress") {
    updateProgress(msg);
  } else if (msg.type === "deletion-complete") {
    onComplete(msg);
  } else if (msg.type === "deletion-log") {
    appendLog(msg.text, msg.level);
  }
});

fileInput.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;

  fileName.textContent = file.name;

  const reader = new FileReader();
  reader.onload = (ev) => {
    try {
      duplicatesData = JSON.parse(ev.target.result);
      showSummary(duplicatesData);
    } catch (err) {
      appendLog(`Error parsing JSON: ${err.message}`, "error");
      logSection.style.display = "block";
    }
  };
  reader.readAsText(file);
});

function showSummary(data) {
  const stats = data.stats || {};
  document.getElementById("stat-groups").textContent = stats.duplicate_groups || 0;
  document.getElementById("stat-delete").textContent = stats.duplicates_to_delete || 0;
  document.getElementById("stat-space").textContent = stats.space_recoverable_mb || 0;
  summarySection.style.display = "block";

  // Build flat delete queue
  deleteQueue = [];
  for (const group of data.groups || []) {
    for (const photo of group.delete || []) {
      deleteQueue.push({
        filename: photo.filename,
        date: photo.date,
        groupId: group.id,
        url: photo.url || null,
      });
    }
  }
}

startBtn.addEventListener("click", () => {
  if (!duplicatesData || deleteQueue.length === 0) return;

  const delay = parseFloat(delayInput.value) || 3;

  chrome.runtime.sendMessage({
    type: "start-deletion",
    queue: deleteQueue,
    delay: delay * 1000,
  });

  startBtn.style.display = "none";
  pauseBtn.style.display = "inline-block";
  stopBtn.style.display = "inline-block";
  progressSection.style.display = "block";
  logSection.style.display = "block";
  delayInput.disabled = true;

  appendLog(`Starting deletion of ${deleteQueue.length} photos (delay: ${delay}s)...`, "info");
});

pauseBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "pause-deletion" });
  pauseBtn.style.display = "none";
  resumeBtn.style.display = "inline-block";
  appendLog("Paused.", "info");
});

resumeBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "resume-deletion" });
  resumeBtn.style.display = "none";
  pauseBtn.style.display = "inline-block";
  appendLog("Resumed.", "info");
});

stopBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "stop-deletion" });
  resetControls();
  appendLog("Stopped by user.", "info");
});

function showProgress(state) {
  progressSection.style.display = "block";
  logSection.style.display = "block";
  startBtn.style.display = "none";
  if (state.status === "paused") {
    pauseBtn.style.display = "none";
    resumeBtn.style.display = "inline-block";
  } else {
    pauseBtn.style.display = "inline-block";
    resumeBtn.style.display = "none";
  }
  stopBtn.style.display = "inline-block";
  updateProgress(state);
}

function updateProgress(state) {
  const total = state.total || 1;
  const done = state.completed || 0;
  const pct = Math.round((done / total) * 100);
  progressBar.style.width = pct + "%";
  progressText.textContent = `${done} / ${total} (${pct}%)`;
}

function onComplete(msg) {
  resetControls();
  const { completed, failed, total } = msg;
  appendLog(`Done! ${completed} deleted, ${failed} failed out of ${total}.`, "success");
  progressBar.style.width = "100%";
}

function resetControls() {
  startBtn.style.display = "inline-block";
  pauseBtn.style.display = "none";
  resumeBtn.style.display = "none";
  stopBtn.style.display = "none";
  delayInput.disabled = false;
}

function appendLog(text, level = "info") {
  const line = document.createElement("div");
  line.className = level;
  line.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}
