(function () {
  "use strict";

  var DISMISS_MS = 10000;

  function hideMessageItem(item) {
    if (item.dataset.dismissed === "1") {
      return;
    }
    item.dataset.dismissed = "1";
    if (item._autoDismissTimer) {
      window.clearTimeout(item._autoDismissTimer);
    }
    item.classList.add("is-dismissing");
    window.setTimeout(function () {
      item.remove();
      var wrap = document.querySelector(".admin-messages-wrap");
      if (wrap && !wrap.querySelector(".messagelist li")) {
        wrap.remove();
      }
    }, 450);
  }

  function enhanceMessageItem(item) {
    if (item.dataset.autoDismissInit === "1") {
      return;
    }
    item.dataset.autoDismissInit = "1";

    var text = document.createElement("span");
    text.className = "admin-message-text";
    while (item.firstChild) {
      text.appendChild(item.firstChild);
    }

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "admin-message-close";
    closeBtn.setAttribute("aria-label", "Close");
    closeBtn.innerHTML = '<i class="bi bi-x" aria-hidden="true"></i>';
    closeBtn.addEventListener("click", function () {
      hideMessageItem(item);
    });

    item.appendChild(text);
    item.appendChild(closeBtn);

    item._autoDismissTimer = window.setTimeout(function () {
      hideMessageItem(item);
    }, DISMISS_MS);
  }

  function initAutoDismiss() {
    document
      .querySelectorAll(".admin-messages-wrap .messagelist li")
      .forEach(enhanceMessageItem);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAutoDismiss);
  } else {
    initAutoDismiss();
  }
})();
