(function () {
  "use strict";

  function getJQuery() {
    return window.django && window.django.jQuery ? window.django.jQuery : null;
  }

  function getAssigneeSelectValue(select) {
    if (!select) {
      return "";
    }
    var $ = getJQuery();
    if ($ && $(select).hasClass("select2-hidden-accessible")) {
      var select2Value = $(select).val();
      if (select2Value) {
        return String(select2Value);
      }
    }
    if (select.value) {
      return String(select.value);
    }
    var selectedOption = select.querySelector("option:checked");
    if (selectedOption && selectedOption.value) {
      return String(selectedOption.value);
    }
    return "";
  }

  function getInlineGroup(tbody) {
    return (
      tbody.closest(".js-inline-admin-formset") ||
      tbody.closest(".inline-group") ||
      null
    );
  }

  function getFormsetPrefix(tbody) {
    var group = getInlineGroup(tbody);
    if (!group) {
      return null;
    }
    var totalForms = group.querySelector('input[name$="-TOTAL_FORMS"]');
    if (!totalForms || !totalForms.name) {
      return null;
    }
    return totalForms.name.replace(/-TOTAL_FORMS$/, "");
  }

  function updateElementIndex(element, prefix, index) {
    var pattern = new RegExp("(" + prefix + "-(\\d+|__prefix__))", "g");
    var replacement = prefix + "-" + index;
    if (element.htmlFor) {
      element.htmlFor = element.htmlFor.replace(pattern, replacement);
    }
    if (element.id) {
      element.id = element.id.replace(pattern, replacement);
    }
    if (element.name) {
      element.name = element.name.replace(pattern, replacement);
    }
  }

  function reindexFormsetRows(tbody) {
    var prefix = getFormsetPrefix(tbody);
    if (!prefix) {
      return false;
    }

    var rows = Array.prototype.filter.call(
      tbody.querySelectorAll("tr.form-row"),
      function (row) {
        return !row.classList.contains("empty-form");
      }
    );

    rows.forEach(function (row, index) {
      row.id = prefix + "-" + index;
      row.querySelectorAll("input, select, textarea, label").forEach(function (el) {
        updateElementIndex(el, prefix, index);
      });
    });
    return true;
  }

  function isRowActive(row) {
    if (!row || row.classList.contains("empty-form")) {
      return false;
    }
    var deleteInput = row.querySelector('input[name$="-DELETE"]');
    if (deleteInput && deleteInput.checked) {
      return false;
    }
    var assignee = row.querySelector('select[name$="-assignee"]');
    return Boolean(getAssigneeSelectValue(assignee));
  }

  function selectedAssigneeIds(tbody, excludeRow) {
    var ids = [];
    tbody.querySelectorAll("tr.form-row").forEach(function (row) {
      if (row === excludeRow || row.classList.contains("empty-form")) {
        return;
      }
      if (!isRowActive(row)) {
        return;
      }
      var select = row.querySelector('select[name$="-assignee"]');
      var value = getAssigneeSelectValue(select);
      if (value) {
        ids.push(value);
      }
    });
    return ids;
  }

  function buildAssigneeAjaxData(tbody, row) {
    return function (params) {
      return {
        term: params.term || "",
        page: params.page || 1,
        exclude_assignees: selectedAssigneeIds(tbody, row).join(","),
      };
    };
  }

  function updateRowOrderHiddenFields(tbody) {
    var order = 0;
    tbody.querySelectorAll("tr.form-row").forEach(function (row) {
      if (row.classList.contains("empty-form")) {
        return;
      }
      var hidden = row.querySelector('input[name$="-wf_row_order"]');
      if (!hidden) {
        return;
      }
      if (!isRowActive(row)) {
        hidden.value = "";
        return;
      }
      hidden.value = String(order);
      order += 1;
    });
  }

  function renumberRows(tbody) {
    var order = 1;
    tbody.querySelectorAll("tr.form-row").forEach(function (row) {
      var num = row.querySelector(".wf-step-order-num");
      if (!num) {
        return;
      }
      if (!isRowActive(row)) {
        num.textContent = "—";
        return;
      }
      num.textContent = String(order);
      order += 1;
    });
  }

  function refreshStepRows(tbody) {
    updateRowOrderHiddenFields(tbody);
    renumberRows(tbody);
  }

  function destroyAssigneeSelect2(select) {
    var $ = getJQuery();
    if (!$ || !$.fn.select2) {
      return;
    }
    var $select = $(select);
    if ($select.hasClass("select2-hidden-accessible")) {
      $select.select2("destroy");
    }
  }

  function initWorkflowAssigneeSelect(select, tbody) {
    var $ = getJQuery();
    if (!$ || !$.fn.select2) {
      return;
    }

    destroyAssigneeSelect2(select);

    var $select = $(select);
    var row = select.closest("tr.form-row");
    var ajaxUrl = select.getAttribute("data-ajax--url");
    if (!ajaxUrl) {
      return;
    }
    var baseUrl = ajaxUrl.split("?")[0];
    var ajaxData = buildAssigneeAjaxData(tbody, row);

    $select.select2({
      theme: "admin-autocomplete",
      allowClear: select.dataset.allowClear === "true",
      placeholder: "",
      width: "100%",
      ajax: {
        url: baseUrl,
        dataType: "json",
        delay: 250,
        cache: false,
        data: ajaxData,
      },
    });

    $select.off("select2:select.wf select2:clear.wf select2:opening.wf");
    $select.on("select2:opening.wf", function () {
      var data = $select.data("select2");
      if (data && data.options && data.options.options && data.options.options.ajax) {
        data.options.options.ajax.data = buildAssigneeAjaxData(tbody, row);
      }
    });
    $select.on("select2:select.wf select2:clear.wf", function () {
      afterRowOrderChanged(tbody, false);
    });
  }

  function initAllWorkflowAssigneeSelects(tbody) {
    tbody.querySelectorAll("select.wf-assignee-autocomplete").forEach(function (select) {
      initWorkflowAssigneeSelect(select, tbody);
    });
  }

  function afterRowOrderChanged(tbody, reindex) {
    if (reindex !== false) {
      reindexFormsetRows(tbody);
    }
    refreshStepRows(tbody);
    initAllWorkflowAssigneeSelects(tbody);
  }

  function bindFormSubmit(tbody) {
    var form = tbody.closest("form");
    if (!form || form.dataset.wfStepsSubmitBound === "1") {
      return;
    }
    form.dataset.wfStepsSubmitBound = "1";
    form.addEventListener(
      "submit",
      function () {
        reindexFormsetRows(tbody);
        updateRowOrderHiddenFields(tbody);
      },
      true
    );
  }

  function initSortable(tbody) {
    if (tbody.dataset.wfSortableBound === "1") {
      return;
    }
    tbody.dataset.wfSortableBound = "1";

    var dragRow = null;

    tbody.querySelectorAll("tr.form-row").forEach(function (row) {
      if (row.classList.contains("empty-form")) {
        return;
      }
      row.setAttribute("draggable", "true");

      row.addEventListener("dragstart", function (event) {
        dragRow = row;
        row.classList.add("wf-step-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", "workflow-step");
      });

      row.addEventListener("dragend", function () {
        row.classList.remove("wf-step-dragging");
        dragRow = null;
        afterRowOrderChanged(tbody, true);
      });

      row.addEventListener("dragover", function (event) {
        event.preventDefault();
        if (!dragRow || dragRow === row || row.classList.contains("empty-form")) {
          return;
        }
        var rect = row.getBoundingClientRect();
        var insertAfter = event.clientY > rect.top + rect.height / 2;
        tbody.insertBefore(dragRow, insertAfter ? row.nextSibling : row);
      });
    });

    tbody.querySelectorAll('input[name$="-DELETE"]').forEach(function (input) {
      input.addEventListener("change", function () {
        afterRowOrderChanged(tbody, true);
      });
    });

    bindFormSubmit(tbody);
  }

  function findStepsTbody() {
    var marker = document.querySelector(".inline-group .wf-step-order-num");
    var group =
      document.getElementById("steps-group") ||
      (marker ? marker.closest(".inline-group") : null);
    if (!group) {
      return null;
    }
    return group.querySelector("tbody");
  }

  function bootWorkflowSteps() {
    var tbody = findStepsTbody();
    if (!tbody) {
      return;
    }
    initSortable(tbody);
    refreshStepRows(tbody);
    initAllWorkflowAssigneeSelects(tbody);
  }

  function scheduleBootWorkflowSteps() {
    bootWorkflowSteps();
    window.setTimeout(bootWorkflowSteps, 0);
    var $ = getJQuery();
    if ($) {
      $(bootWorkflowSteps);
    }
  }

  document.addEventListener("DOMContentLoaded", scheduleBootWorkflowSteps);
  document.addEventListener("formset:added", function () {
    window.setTimeout(scheduleBootWorkflowSteps, 0);
  });
})();
