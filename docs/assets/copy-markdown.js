// Adds a "Copy page as Markdown" button next to Material's built-in
// "Edit this page" button. Fetches the raw Markdown mkdocs-llmstxt
// generates alongside every page's HTML (same URL, index.md instead of
// index.html) and copies it to the clipboard -- useful for pasting a
// page straight into an LLM chat without HTML/nav/chrome noise.
(function () {
  var COPY_ICON =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
    '<path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>' +
    "</svg>";
  var CHECK_ICON =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
    '<path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z"/>' +
    "</svg>";

  function mdUrlForCurrentPage() {
    var path = window.location.pathname;
    if (!path.endsWith("/")) path += "/";
    return path + "index.md";
  }

  function flashSuccess(button) {
    var originalTitle = button.getAttribute("data-original-title");
    button.innerHTML = CHECK_ICON;
    button.classList.add("zeython-copy-md--done");
    button.setAttribute("title", "Copied!");
    setTimeout(function () {
      button.innerHTML = COPY_ICON;
      button.classList.remove("zeython-copy-md--done");
      button.setAttribute("title", originalTitle);
    }, 1500);
  }

  function onCopyClick(event) {
    var button = event.currentTarget;
    fetch(mdUrlForCurrentPage())
      .then(function (response) {
        if (!response.ok) throw new Error("Markdown source not found");
        return response.text();
      })
      .then(function (text) {
        return navigator.clipboard.writeText(text);
      })
      .then(function () {
        flashSuccess(button);
      })
      .catch(function () {
        // Clipboard API unavailable (insecure context, permissions) or the
        // .md file 404s -- fall back to just opening it in a new tab.
        window.open(mdUrlForCurrentPage(), "_blank", "noopener");
      });
  }

  function addButton() {
    var container = document.querySelector(".md-content__inner");
    if (!container || container.querySelector(".zeython-copy-md")) return;

    var button = document.createElement("button");
    button.type = "button";
    button.className = "md-content__button md-icon zeython-copy-md";
    button.setAttribute("title", "Copy page as Markdown");
    button.setAttribute("data-original-title", "Copy page as Markdown");
    button.innerHTML = COPY_ICON;
    button.addEventListener("click", onCopyClick);

    var editButton = container.querySelector(".md-content__button[rel='edit']");
    if (editButton) {
      editButton.insertAdjacentElement("beforebegin", button);
    } else {
      container.insertBefore(button, container.firstChild);
    }
  }

  // document$ is Material's own navigation observable, firing on every
  // instant-navigation page swap (navigation.instant) as well as the
  // initial load -- a plain DOMContentLoaded listener would only fire once.
  if (typeof document$ !== "undefined") {
    document$.subscribe(addButton);
  } else {
    document.addEventListener("DOMContentLoaded", addButton);
  }
})();
