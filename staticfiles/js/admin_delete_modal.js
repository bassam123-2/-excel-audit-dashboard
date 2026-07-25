(function () {
  "use strict";

  var DELETE_URL_PATTERN = /\/admin\/[^/]+\/[^/]+\/\d+\/delete\/?$/;
  var USER_DELETE_PATTERN = /\/admin\/auth\/user\/\d+\/delete\/?$/;
  var DELETE_ACTIONS = { delete_selected: true, delete: true };

  function initAdminDeleteModal() {
    var modal = document.getElementById("admin-delete-modal");
    var postForm = document.getElementById("admin-delete-form");
    if (!modal || !postForm) {
      return;
    }

    var backdrop = modal.querySelector(".admin-delete-modal__backdrop");
    var closeBtn = modal.querySelector(".admin-delete-modal__close");
    var cancelBtns = modal.querySelectorAll("[data-admin-delete-cancel]");
    var confirmBtn = modal.querySelector("[data-admin-delete-confirm]");
    var titleEl = modal.querySelector("[data-admin-delete-title]");
    var leadEl = modal.querySelector("[data-admin-delete-lead]");
    var notesEl = modal.querySelector("[data-admin-delete-notes]");
    var itemsLabelEl = modal.querySelector("[data-admin-delete-items-label]");
    var itemsEl = modal.querySelector("[data-admin-delete-items]");
    var iconEl = modal.querySelector("[data-admin-delete-icon]");
    var confirmLabelEl = modal.querySelector("[data-admin-delete-confirm-label]");

    var lastFocus = null;
    var pendingConfirm = null;

    function copy(key) {
      return modal.getAttribute("data-copy-" + key) || "";
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function formatLead(template, objectName) {
      var nameHtml =
        '<span class="admin-delete-modal__object-name">' +
        escapeHtml(objectName || "") +
        "</span>";
      return template.split("__OBJECT__").join(nameHtml);
    }

    function setNotes(items) {
      notesEl.innerHTML = "";
      if (!items || !items.length) {
        notesEl.hidden = true;
        return;
      }
      items.forEach(function (text) {
        var li = document.createElement("li");
        li.textContent = text;
        notesEl.appendChild(li);
      });
      notesEl.hidden = false;
    }

    function setItems(items) {
      itemsEl.innerHTML = "";
      if (!items || !items.length) {
        itemsEl.hidden = true;
        itemsLabelEl.hidden = true;
        return;
      }
      itemsLabelEl.textContent = copy("items-label");
      itemsLabelEl.hidden = false;
      items.forEach(function (text) {
        var li = document.createElement("li");
        li.textContent = text;
        itemsEl.appendChild(li);
      });
      itemsEl.hidden = false;
    }

    function setIcon(mode) {
      if (!iconEl) {
        return;
      }
      iconEl.innerHTML =
        mode === "user"
          ? '<i class="bi bi-person-x-fill"></i>'
          : '<i class="bi bi-trash3-fill"></i>';
    }

    function openModal(config) {
      pendingConfirm = config.onConfirm || null;
      lastFocus = document.activeElement;

      var mode = config.mode || "generic";
      setIcon(mode === "user" || mode === "user-bulk" ? "user" : "generic");

      if (mode === "user") {
        titleEl.textContent = copy("title-user");
        leadEl.innerHTML = formatLead(copy("lead-user"), config.objectName);
        confirmLabelEl.textContent = copy("confirm-user");
        setNotes([copy("note-user-1"), copy("note-user-2")]);
        setItems(null);
      } else if (mode === "user-bulk") {
        titleEl.textContent = copy("title-user-bulk");
        leadEl.textContent = copy("lead-bulk");
        confirmLabelEl.textContent = copy("confirm-user-bulk");
        setNotes([copy("note-user-1"), copy("note-user-2")]);
        setItems(config.items || []);
      } else if (mode === "bulk") {
        titleEl.textContent = copy("title-bulk");
        leadEl.textContent = copy("lead-bulk");
        confirmLabelEl.textContent = copy("confirm-bulk");
        setNotes([copy("note-generic-1"), copy("note-generic-2")]);
        setItems(config.items || []);
      } else {
        titleEl.textContent = copy("title-generic");
        leadEl.innerHTML = formatLead(copy("lead-generic"), config.objectName);
        confirmLabelEl.textContent = copy("confirm-generic");
        setNotes([copy("note-generic-1"), copy("note-generic-2")]);
        setItems(null);
      }

      if (config.deleteUrl) {
        postForm.setAttribute("action", config.deleteUrl);
      } else {
        postForm.removeAttribute("action");
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

    function closeModal(options) {
      options = options || {};
      modal.hidden = true;
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("admin-delete-modal-open");
      pendingConfirm = null;
      if (confirmBtn) {
        confirmBtn.disabled = false;
      }
      if (!options.skipFocusRestore && lastFocus && typeof lastFocus.focus === "function") {
        lastFocus.focus();
      }
      if (options.redirectOnCancel) {
        window.location.href = options.redirectOnCancel;
      }
    }

    function resolveObjectName(link) {
      var fromLink = link.getAttribute("data-object-name");
      if (fromLink) {
        return fromLink.trim();
      }
      var selectors = [
        ".change-form-object-title",
        ".admin-cl-v2-form__title",
        "#content-main .admin-cl-v2__title",
        ".breadcrumbs .current",
      ];
      for (var i = 0; i < selectors.length; i += 1) {
        var node = document.querySelector(selectors[i]);
        if (node && node.textContent) {
          return node.textContent.trim();
        }
      }
      return "";
    }

    function isAdminDeleteLink(link) {
      if (!(link instanceof HTMLAnchorElement)) {
        return false;
      }
      if (!link.classList.contains("deletelink")) {
        return false;
      }
      return DELETE_URL_PATTERN.test(link.pathname);
    }

    function isUserDeleteUrl(url) {
      return USER_DELETE_PATTERN.test(url);
    }

    function isDeleteAction(action) {
      return Boolean(action && DELETE_ACTIONS[action]);
    }

    function bindCancelHandlers() {
      cancelBtns.forEach(function (btn) {
        btn.addEventListener("click", function (event) {
          event.preventDefault();
          var redirect = btn.getAttribute("data-cancel-redirect");
          closeModal({ redirectOnCancel: redirect || "" });
        });
      });
    }

    document.addEventListener("click", function (event) {
      var link = event.target.closest("a.deletelink");
      if (!link || !isAdminDeleteLink(link)) {
        return;
      }
      event.preventDefault();
      openModal({
        mode: isUserDeleteUrl(link.pathname) ? "user" : "generic",
        objectName: resolveObjectName(link),
        deleteUrl: link.href,
        onConfirm: function () {
          postForm.submit();
        },
      });
    });

    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        if (!pendingConfirm) {
          return;
        }
        confirmBtn.disabled = true;
        pendingConfirm();
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

    function resolveConfirmationObjectName(content) {
      var breadcrumbLinks = document.querySelectorAll(".breadcrumbs a");
      if (breadcrumbLinks.length) {
        return breadcrumbLinks[breadcrumbLinks.length - 1].textContent.trim();
      }
      var paragraph = content && content.querySelector("p");
      if (!paragraph) {
        return "";
      }
      var quoted = paragraph.textContent.match(/["“]([^"”]+)["”]/);
      if (quoted) {
        return quoted[1].trim();
      }
      return "";
    }

    function initConfirmationPage() {
      var body = document.body;
      var isBulk = body.classList.contains("delete-selected-confirmation");
      var isSingle = body.classList.contains("delete-confirmation");
      if (!isBulk && !isSingle) {
        return;
      }

      var content = document.getElementById("content");
      var pageForm = content && content.querySelector("form");
      if (!pageForm) {
        return;
      }

      body.classList.add("admin-delete-confirmation-page");

      var cancelLink = pageForm.querySelector("a.cancel-link");
      if (cancelLink && cancelLink.href && cancelLink.href !== "#") {
        cancelBtns.forEach(function (btn) {
          btn.setAttribute("data-cancel-redirect", cancelLink.href);
        });
      }

      var isUser =
        body.classList.contains("model-user") ||
        /\/admin\/auth\/user\//.test(window.location.pathname);

      if (isBulk) {
        var items = [];
        content.querySelectorAll("ul li").forEach(function (li) {
          var text = (li.textContent || "").trim();
          if (text) {
            items.push(text);
          }
        });
        openModal({
          mode: isUser ? "user-bulk" : "bulk",
          items: items,
          onConfirm: function () {
            pageForm.submit();
          },
        });
        return;
      }

      openModal({
        mode: isUser ? "user" : "generic",
        objectName: resolveConfirmationObjectName(content),
        onConfirm: function () {
          pageForm.submit();
        },
      });
    }

    bindCancelHandlers();
    initConfirmationPage();

    window.AdminDeleteModal = {
      confirmDeleteAction: function (form, action) {
        if (!form || !isDeleteAction(action)) {
          return false;
        }
        var selected = form.querySelectorAll(
          'input.action-select[type="checkbox"]:checked'
        );
        if (!selected.length) {
          return false;
        }
        openModal({
          mode: "bulk",
          items: [],
          onConfirm: function () {
            form.submit();
          },
        });
        return true;
      },
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAdminDeleteModal);
  } else {
    initAdminDeleteModal();
  }
})();
