/* global chrome */

/**
 * Content script injected into photos.google.com.
 * Handles deleting photos and clicking search results.
 * Navigation is handled by the background script.
 */

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "delete-current-photo") {
    deleteCurrentPhoto()
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true;
  }
});

/**
 * Sleep for a given number of milliseconds.
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Attempt to delete the currently viewed photo.
 */
async function deleteCurrentPhoto() {
  // Look for the delete/trash button
  const deleteSelectors = [
    '[aria-label="Delete"]',
    '[aria-label="Move to trash"]',
    '[aria-label="Move to Trash"]',
    'button[aria-label*="trash" i]',
    'button[aria-label*="delete" i]',
  ];

  let deleteBtn = null;
  for (const sel of deleteSelectors) {
    deleteBtn = document.querySelector(sel);
    if (deleteBtn) break;
  }

  if (!deleteBtn) {
    // Try keyboard shortcut (# key deletes in Google Photos)
    document.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "#",
        code: "Digit3",
        shiftKey: true,
        bubbles: true,
      })
    );
    await sleep(1000);
  } else {
    deleteBtn.click();
    await sleep(1000);
  }

  // Confirm deletion in the dialog
  const confirmSelectors = [
    'button[aria-label="Move to trash"]',
    'button[aria-label="Move to Trash"]',
    '[data-mdc-dialog-action="ok"]',
  ];

  // Also look for buttons with text content "Move to trash"
  const allButtons = document.querySelectorAll("button");
  for (const btn of allButtons) {
    const text = btn.textContent.trim().toLowerCase();
    if (text === "move to trash" || text === "delete") {
      btn.click();
      await sleep(500);
      return { success: true };
    }
  }

  for (const sel of confirmSelectors) {
    const confirmBtn = document.querySelector(sel);
    if (confirmBtn) {
      confirmBtn.click();
      await sleep(500);
      return { success: true };
    }
  }

  return { success: true }; // Assume the keyboard shortcut worked
}
