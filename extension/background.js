/* global chrome */

let deletionState = {
  status: "idle", // idle, running, paused, stopped
  queue: [],
  currentIndex: 0,
  completed: 0,
  failed: 0,
  total: 0,
  delay: 3000,
};

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case "start-deletion":
      startDeletion(msg.queue, msg.delay);
      break;
    case "pause-deletion":
      deletionState.status = "paused";
      saveState();
      break;
    case "resume-deletion":
      deletionState.status = "running";
      saveState();
      processNext();
      break;
    case "stop-deletion":
      deletionState.status = "stopped";
      saveState();
      break;
    case "get-state":
      sendResponse(deletionState);
      break;
  }
  return true;
});

function startDeletion(queue, delay) {
  deletionState = {
    status: "running",
    queue: queue,
    currentIndex: 0,
    completed: 0,
    failed: 0,
    total: queue.length,
    delay: delay,
  };
  saveState();
  processNext();
}

async function processNext() {
  if (deletionState.status !== "running") return;
  if (deletionState.currentIndex >= deletionState.queue.length) {
    // All done
    deletionState.status = "idle";
    saveState();
    broadcastToPopup({
      type: "deletion-complete",
      completed: deletionState.completed,
      failed: deletionState.failed,
      total: deletionState.total,
    });
    return;
  }

  const item = deletionState.queue[deletionState.currentIndex];

  // Send delete command to content script
  try {
    const tabs = await chrome.tabs.query({
      active: true,
      currentWindow: true,
      url: "https://photos.google.com/*",
    });

    if (tabs.length === 0) {
      broadcastToPopup({
        type: "deletion-log",
        text: "No Google Photos tab found. Please open photos.google.com.",
        level: "error",
      });
      deletionState.status = "paused";
      saveState();
      return;
    }

    const tab = tabs[0];

    const response = await chrome.tabs.sendMessage(tab.id, {
      type: "delete-photo",
      filename: item.filename,
      date: item.date,
    });

    if (response && response.success) {
      deletionState.completed++;
      broadcastToPopup({
        type: "deletion-log",
        text: `Deleted: ${item.filename}`,
        level: "success",
      });
    } else {
      deletionState.failed++;
      const reason = (response && response.error) || "Unknown error";
      broadcastToPopup({
        type: "deletion-log",
        text: `Failed: ${item.filename} — ${reason}`,
        level: "error",
      });
    }
  } catch (err) {
    deletionState.failed++;
    broadcastToPopup({
      type: "deletion-log",
      text: `Error: ${item.filename} — ${err.message}`,
      level: "error",
    });
  }

  deletionState.currentIndex++;

  // Broadcast progress
  broadcastToPopup({
    type: "deletion-progress",
    completed: deletionState.completed + deletionState.failed,
    total: deletionState.total,
  });

  saveState();

  // Wait before processing next
  if (deletionState.status === "running") {
    setTimeout(() => processNext(), deletionState.delay);
  }
}

function saveState() {
  chrome.storage.local.set({
    deletionState: {
      status: deletionState.status,
      currentIndex: deletionState.currentIndex,
      completed: deletionState.completed,
      failed: deletionState.failed,
      total: deletionState.total,
    },
  });
}

function broadcastToPopup(msg) {
  chrome.runtime.sendMessage(msg).catch(() => {
    // Popup might be closed, that's fine
  });
}
