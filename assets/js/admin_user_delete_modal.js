(function () {
  "use strict";

  function initUserDeleteModal() {
    var modal = document.getElementById("admin-user-delete-modal");
    var form = document.getElementById("admin-user-delete-form");
    if (!modal || !form) {
      return;
    }

    var backdrop = modal.querySelector(".admin-delete-modal__backdrop");
    var closeBtn = modal.querySelector(".admin-delete-modal__close");
    var cancelBtn = modal.querySelector("[data-admin-delete-cancel]");
    var confirmBtn = modal.querySelector("[data-admin-delete-confirm]");
    var usernameEl = modal.querySelector("[data-admin-delete-username]");
    var defaultUsername = modal.getAttribute("data-default-username") || "";

    var lastFocus = null;

    function openModal(deleteUrl, username) {
      lastFocus = document.activeElement;
      form.setAttribute("action", deleteUrl);
      if (usernameEl) {
        usernameEl.textContent = username || defaultUsername;
      }
      modal.hidden = false;
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("admin-delete-modal-open");
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.focus();
      }
    }

    function closeModal() {
      modal.hidden = true;
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("admin-delete-modal-open");
      if (lastFocus && typeof lastFocus.focus === "function") {
        lastFocus.focus();
      }
    }

    function resolveUsername(link) {
      var fromLink = link.getAttribute("data-username");
      if (fromLink) {
        return fromLink;
      }
      var title = document.querySelector(".change-form-object-title");
      if (title && title.textContent) {
        return title.textContent.trim();
      }
      return defaultUsername;
    }

    function isUserDeleteLink(link) {
      if (!(link instanceof HTMLAnchorElement)) {
        return false;
      }
      if (!link.classList.contains("deletelink")) {
        return false;
      }
      return /\/admin\/auth\/user\/\d+\/delete\/?$/.test(link.pathname);
    }

    document.addEventListener("click", function (event) {
      var link = event.target.closest("a.deletelink");
      if (!link || !isUserDeleteLink(link)) {
        return;
      }
      event.preventDefault();
      openModal(link.href, resolveUsername(link));
    });

    function onCancel(event) {
      event.preventDefault();
      closeModal();
    }

    if (backdrop) {
      backdrop.addEventListener("click", onCancel);
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", onCancel);
    }
    if (cancelBtn) {
      cancelBtn.addEventListener("click", onCancel);
    }

    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        confirmBtn.disabled = true;
        form.submit();
      });
    }

    document.addEventListener("keydown", function (event) {
      if (modal.hidden) {
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeModal();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initUserDeleteModal);
  } else {
    initUserDeleteModal();
  }
})();
