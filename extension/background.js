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

/**
 * Navigate a tab to a URL and wait for it to finish loading.
 */
function navigateTab(tabId, url) {
  return new Promise((resolve) => {
    function onUpdated(updatedTabId, changeInfo) {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        chrome.tabs.onUpdated.removeListener(onUpdated);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.update(tabId, { url: url });
  });
}

/**
 * Send a message to a tab's content script, retrying a few times
 * to handle the case where the content script hasn't fully initialized yet.
 */
async function sendTabMessage(tabId, message, retries = 3) {
  for (let i = 0; i < retries; i++) {
    try {
      const response = await chrome.tabs.sendMessage(tabId, message);
      return response;
    } catch (err) {
      if (i < retries - 1) {
        // Wait a bit for the content script to initialize
        await new Promise((r) => setTimeout(r, 1000));
      } else {
        throw err;
      }
    }
  }
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
    if (!item.url) {
      throw new Error("No Google Photos URL available (missing metadata)");
    }

    // Navigate directly to the photo URL
    await navigateTab(tab.id, item.url);
    // Give the page a moment to render the photo viewer
    await new Promise((r) => setTimeout(r, 2000));

    const deleteResult = await sendTabMessage(tab.id, {
      type: "delete-current-photo",
    });

    if (deleteResult && deleteResult.success) {
      deletionState.completed++;
      broadcastToPopup({
        type: "deletion-log",
        text: `Deleted: ${item.filename}`,
        level: "success",
      });
    } else {
      deletionState.failed++;
      const reason = (deleteResult && deleteResult.error) || "Unknown error";
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
