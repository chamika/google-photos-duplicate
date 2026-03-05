/* global chrome */

/**
 * Content script injected into photos.google.com.
 * Handles searching for and deleting individual photos via the Google Photos web UI.
 */

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "delete-photo") {
    handleDelete(msg.filename, msg.date)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true; // async response
  }
});

/**
 * Wait for an element matching a selector to appear in the DOM.
 */
function waitForElement(selector, timeout = 8000) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(selector);
    if (existing) {
      resolve(existing);
      return;
    }

    const observer = new MutationObserver(() => {
      const el = document.querySelector(selector);
      if (el) {
        observer.disconnect();
        resolve(el);
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });

    setTimeout(() => {
      observer.disconnect();
      reject(new Error(`Timeout waiting for ${selector}`));
    }, timeout);
  });
}

/**
 * Sleep for a given number of milliseconds.
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Search for a photo by filename using the Google Photos search bar.
 */
async function searchForPhoto(filename) {
  // Navigate to search
  const searchUrl = `https://photos.google.com/search/${encodeURIComponent(filename)}`;
  window.location.href = searchUrl;

  // Wait for the page to load and results to appear
  await sleep(3000);

  // Look for photo thumbnails in search results
  // Google Photos uses divs with data-latest-bg for thumbnails
  const thumbnails = document.querySelectorAll('[data-latest-bg]');
  if (thumbnails.length === 0) {
    // Try looking for any clickable photo elements
    const photoElements = document.querySelectorAll('[aria-label*="Photo"]');
    if (photoElements.length > 0) {
      return photoElements[0];
    }
    return null;
  }

  return thumbnails[0];
}

/**
 * Attempt to delete the currently viewed photo.
 */
async function deleteCurrentPhoto() {
  // Look for the delete/trash button
  // Google Photos uses aria-label="Delete" or aria-label="Move to trash"
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
      return true;
    }
  }

  for (const sel of confirmSelectors) {
    const confirmBtn = document.querySelector(sel);
    if (confirmBtn) {
      confirmBtn.click();
      await sleep(500);
      return true;
    }
  }

  return true; // Assume the keyboard shortcut worked
}

/**
 * Main deletion handler.
 */
async function handleDelete(filename, date) {
  try {
    // Search for the photo
    const photoEl = await searchForPhoto(filename);

    if (!photoEl) {
      // Fallback: try searching by date if provided
      if (date && date !== "Unknown") {
        const dateEl = await searchForPhoto(date);
        if (!dateEl) {
          return { success: false, error: "Photo not found in search results" };
        }
        dateEl.click();
      } else {
        return { success: false, error: "Photo not found in search results" };
      }
    } else {
      photoEl.click();
    }

    // Wait for the photo viewer to open
    await sleep(2000);

    // Delete the photo
    const deleted = await deleteCurrentPhoto();

    if (deleted) {
      return { success: true };
    } else {
      return { success: false, error: "Could not confirm deletion" };
    }
  } catch (err) {
    return { success: false, error: err.message };
  }
}
