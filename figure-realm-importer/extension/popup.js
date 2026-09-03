const button = document.querySelector("#capture");
const status = document.querySelector("#status");

button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Starting…";
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.id || !/^https:\/\/(www\.)?figurerealm\.com\//i.test(tab.url || "")) {
    status.textContent = "Open a Figure Realm page first.";
    button.disabled = false;
    return;
  }
  try {
    const response = await chrome.tabs.sendMessage(tab.id, {
      type: "capture-scooby",
      sampleDetails: document.querySelector("#sampleDetails").checked,
    });
    status.textContent = response?.message || "Capture started. Keep the Figure Realm tab open.";
  } catch (error) {
    status.textContent = `Could not start: ${error.message}`;
    button.disabled = false;
  }
});
chrome.runtime.onMessage.addListener((message) => {
  if (message?.type !== "capture-status") return;
  status.textContent = message.message;
  if (message.done || message.error) button.disabled = false;
});
