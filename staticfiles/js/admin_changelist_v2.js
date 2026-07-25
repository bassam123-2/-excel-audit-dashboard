(function () {
  "use strict";

  var SEARCH_DEBOUNCE_MS = 400;

  function initChangelistV2() {
    var root = document.querySelector("#content-start .admin-cl-v2");
    if (!root || root.classList.contains("admin-cl-v2-form")) {
      return;
    }
    if (!root.querySelector(".admin-cl-v2__table-panel")) {
      return;
    }
    initChangelistV2Root(root);
  }

  function initChangelistV2Root(root) {
    setupToolbar(root);
    wrapFilterGroups(root);
    enhanceFilterLinks(root);
    bindSelectionCounter(root);
    bindQuickActions(root);
    bindLiveSearch(root);
    bindActionSelect(root);
  }

  function setupToolbar(root) {
    var toolbarEnd = root.querySelector("[data-admin-cl-v2-toolbar-end]");
    var actionsHost = root.querySelector(".admin-cl-v2__actions-host .actions");
    if (!toolbarEnd) {
      return;
    }

    var pill = toolbarEnd.querySelector("[data-admin-cl-v2-selection-count]");
    if (!pill) {
      pill = document.createElement("span");
      pill.className = "admin-cl-v2__selection-pill";
      pill.dataset.adminClV2SelectionCount = "";
      pill.dataset.adminClV2SelectionLabel =
        root.getAttribute("data-selection-label") || "selected";
      toolbarEnd.insertBefore(pill, toolbarEnd.firstChild);
    }

    if (actionsHost && !toolbarEnd.contains(actionsHost)) {
      toolbarEnd.appendChild(actionsHost);
    }
  }

  function wrapFilterGroups(root) {
    var groupsHost = root.querySelector(".admin-cl-v2__filter-groups");
    if (!groupsHost || groupsHost.dataset.clV2FiltersReady === "1") {
      return;
    }

    groupsHost.querySelectorAll(":scope > h3").forEach(function (heading) {
      var details = document.createElement("details");
      details.className = "admin-cl-v2-filter-group";
      details.open = true;

      var summary = document.createElement("summary");
      summary.textContent = heading.textContent.trim();
      details.appendChild(summary);

      var list = heading.nextElementSibling;
      if (list && list.tagName === "UL") {
        details.appendChild(list);
      }

      heading.replaceWith(details);
    });

    groupsHost.dataset.clV2FiltersReady = "1";
  }

  function enhanceFilterLinks(root) {
    root.querySelectorAll(".admin-cl-v2__filter-groups li a").forEach(function (link) {
      if (link.dataset.clV2Enhanced === "1") {
        return;
      }

      var text = (link.textContent || "").trim();
      var match = text.match(/^(.+?)\s*\((\d+)\)\s*$/);
      if (!match) {
        link.dataset.clV2Enhanced = "1";
        return;
      }

      link.textContent = "";
      var labelSpan = document.createElement("span");
      labelSpan.className = "admin-cl-v2-filter-label";
      labelSpan.textContent = match[1].trim();
      var countSpan = document.createElement("span");
      countSpan.className = "admin-cl-v2-filter-count";
      countSpan.textContent = match[2];
      link.appendChild(labelSpan);
      link.appendChild(countSpan);
      link.dataset.clV2Enhanced = "1";
    });
  }

  function bindSelectionCounter(root) {
    var form = root.querySelector("#changelist-form");
    var pill = root.querySelector("[data-admin-cl-v2-selection-count]");
    if (!form || !pill) {
      return;
    }

    function visibleRows() {
      return form.querySelectorAll(
        '#result_list tbody input.action-select[type="checkbox"]'
      );
    }

    function updateCount() {
      var rows = visibleRows();
      var selected = 0;
      rows.forEach(function (input) {
        if (input.checked) {
          selected += 1;
        }
      });

      if (!rows.length) {
        pill.hidden = true;
      } else {
        pill.hidden = false;
        var label = pill.dataset.adminClV2SelectionLabel || "selected";
        pill.textContent = selected + " / " + rows.length + " " + label;
      }

      updateQuickActionsState(root, selected);
    }

    if (!form.dataset.clV2SelectionBound) {
      form.dataset.clV2SelectionBound = "1";
      form.addEventListener("change", function (event) {
        var target = event.target;
        if (!(target instanceof HTMLInputElement)) {
          return;
        }
        if (target.type !== "checkbox") {
          return;
        }
        if (
          target.name === "_selected_action" ||
          target.classList.contains("action-select")
        ) {
          updateCount();
        }
      });
    }

    updateCount();
  }

  function updateQuickActionsState(root, selectedCount) {
    root.querySelectorAll("[data-cl-v2-quick-action][data-requires-selection]").forEach(
      function (button) {
        var enabled = selectedCount > 0;
        button.disabled = !enabled;
        button.setAttribute(
          "aria-disabled",
          enabled ? "false" : "true"
        );
      }
    );
  }

  function bindQuickActions(root) {
    var hint =
      root.getAttribute("data-quick-action-hint") ||
      "Select at least one row in the table first.";

    root.querySelectorAll("[data-cl-v2-quick-action]").forEach(function (button) {
      if (button.dataset.clV2QuickActionBound === "1") {
        return;
      }
      button.dataset.clV2QuickActionBound = "1";

      button.addEventListener("click", function () {
        var form = root.querySelector("#changelist-form");
        if (!form) {
          return;
        }

        var action = button.getAttribute("data-cl-v2-quick-action");
        if (!action) {
          return;
        }

        var requiresSelection =
          button.getAttribute("data-requires-selection") === "1";
        var selected = form.querySelectorAll(
          'input.action-select[type="checkbox"]:checked'
        );
        if (requiresSelection && !selected.length) {
          window.alert(hint);
          return;
        }

        var actionSelect = form.querySelector('select[name="action"]');
        if (actionSelect) {
          actionSelect.value = action;
        } else {
          var hiddenAction = form.querySelector('input[name="action"]');
          if (!hiddenAction) {
            hiddenAction = document.createElement("input");
            hiddenAction.type = "hidden";
            hiddenAction.name = "action";
            form.appendChild(hiddenAction);
          }
          hiddenAction.value = action;
        }

        var indexInput = form.querySelector('input[name="index"]');
        if (!indexInput) {
          indexInput = document.createElement("input");
          indexInput.type = "hidden";
          indexInput.name = "index";
          form.appendChild(indexInput);
        }
        indexInput.value = "0";

        form.submit();
      });
    });

    var form = root.querySelector("#changelist-form");
    if (form) {
      var selected = form.querySelectorAll(
        'input.action-select[type="checkbox"]:checked'
      ).length;
      updateQuickActionsState(root, selected);
    }
  }

  function filterRowsClient(root, query) {
    var q = (query || "").trim().toLowerCase();
    root.querySelectorAll("#result_list tbody tr").forEach(function (row) {
      if (!q) {
        row.classList.remove("is-cl-v2-hidden");
        return;
      }
      var text = (row.textContent || "").toLowerCase();
      row.classList.toggle("is-cl-v2-hidden", text.indexOf(q) === -1);
    });
  }

  function buildSearchUrl(input) {
    var url = new URL(window.location.href);
    var value = (input.value || "").trim();
    if (value) {
      url.searchParams.set("q", value);
    } else {
      url.searchParams.delete("q");
    }
    url.searchParams.delete("p");
    return url;
  }

  function bindLiveSearch(root) {
    var input = root.querySelector("[data-admin-cl-v2-search-input]");
    var form = root.querySelector("[data-admin-cl-v2-search-form]");
    var tablePanel = root.querySelector(".admin-cl-v2__table-panel");
    if (!input || !form) {
      return;
    }

    if (input.dataset.clV2SearchBound === "1") {
      return;
    }
    input.dataset.clV2SearchBound = "1";

    var debounceTimer = null;
    var lastFetched = (input.value || "").trim();

    input.addEventListener("input", function () {
      filterRowsClient(root, input.value);

      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        var next = (input.value || "").trim();
        if (next === lastFetched) {
          return;
        }
        lastFetched = next;
        fetchSearchResults(root, input, tablePanel);
      }, SEARCH_DEBOUNCE_MS);
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        clearTimeout(debounceTimer);
        lastFetched = (input.value || "").trim();
        fetchSearchResults(root, input, tablePanel);
      }
    });
  }

  function fetchSearchResults(root, input, tablePanel) {
    var url = buildSearchUrl(input);
    if (tablePanel) {
      tablePanel.classList.add("is-searching");
    }

    fetch(url.toString(), {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("search failed");
        }
        return response.text();
      })
      .then(function (html) {
        var parser = new DOMParser();
        var doc = parser.parseFromString(html, "text/html");
        var newPanel = doc.querySelector(".admin-cl-v2__table-panel");
        var currentPanel = root.querySelector(".admin-cl-v2__table-panel");
        if (!newPanel || !currentPanel) {
          window.location.assign(url.toString());
          return;
        }

        currentPanel.replaceWith(newPanel);

        var newStats = doc.querySelector("[data-admin-cl-v2-stats]");
        var currentStats = root.querySelector("[data-admin-cl-v2-stats]");
        if (newStats && currentStats) {
          currentStats.replaceWith(newStats);
        }

        window.history.replaceState({}, "", url.toString());

        var searchInput = root.querySelector("[data-admin-cl-v2-search-input]");
        if (searchInput) {
          searchInput.focus();
          var len = searchInput.value.length;
          searchInput.setSelectionRange(len, len);
        }

        initChangelistV2Root(root);
      })
      .catch(function () {
        formFallbackSubmit(input);
      })
      .finally(function () {
        var panel = root.querySelector(".admin-cl-v2__table-panel");
        if (panel) {
          panel.classList.remove("is-searching");
        }
      });
  }

  function formFallbackSubmit(input) {
    var form = input.closest("form");
    if (form) {
      form.submit();
    }
  }

  function bindActionSelect(root) {
    var form = root.querySelector("#changelist-form");
    if (!form || form.dataset.clV2ActionBound === "1") {
      return;
    }
    form.dataset.clV2ActionBound = "1";

    form.addEventListener("change", function (event) {
      var target = event.target;
      if (!(target instanceof HTMLSelectElement)) {
        return;
      }
      if (target.name !== "action") {
        return;
      }
      var action = target.value;
      if (!action) {
        return;
      }

      var selected = form.querySelectorAll(
        'input.action-select[type="checkbox"]:checked'
      );
      if (!selected.length) {
        target.value = "";
        return;
      }

      form.submit();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initChangelistV2);
  } else {
    initChangelistV2();
  }
})();
