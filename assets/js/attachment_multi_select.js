/**
 * Accumulate multiple attachment picks before save (browser FileList replaces otherwise).
 * Exposes window.AttachmentMultiSelect
 */
(function (window) {
  "use strict";

  var queues = Object.create(null);
  var labels = {
    pendingTitle: "New files to add",
    removeOne: "Remove",
    maxLimit: "Max attachments",
    remaining: "{n} remaining",
    limitFull: "Attachment limit reached for this type",
    exceedLimit:
      "Attachment count exceeds the limit. Remove extra files before saving.",
    cannotUncheck:
      "Cannot keep this file — attachment limit would be exceeded. Remove a new file first, or leave this file marked for removal.",
  };

  function keyFor(fieldPrefix, idPrefix) {
    return String(idPrefix || "") + ":" + String(fieldPrefix || "");
  }

  function getQueue(fieldPrefix, idPrefix) {
    var key = keyFor(fieldPrefix, idPrefix);
    if (!queues[key]) queues[key] = [];
    return queues[key];
  }

  function setLabels(next) {
    if (!next) return;
    Object.keys(next).forEach(function (k) {
      if (next[k] != null && next[k] !== "") labels[k] = String(next[k]);
    });
  }

  function fileInputId(fieldPrefix, idPrefix) {
    return idPrefix === "review-"
      ? "review-id_" + fieldPrefix
      : "id_" + fieldPrefix;
  }

  function el(id) {
    return document.getElementById(id);
  }

  function countKeptExisting(kind, fieldPrefix, idPrefix) {
    var panel = el((idPrefix || "") + kind + "ExistingPanel");
    var removeAll = el(
      idPrefix === "review-" ? "review-remove-" + kind : "remove-" + kind
    );
    if (removeAll && removeAll.value === "1") return 0;
    if (!panel || panel.style.display === "none") return 0;
    var n = 0;
    panel.querySelectorAll(".js-attach-item-remove").forEach(function (cb) {
      if (!cb.checked && !cb.disabled) n += 1;
    });
    return n;
  }

  function maxForInput(input) {
    return parseInt((input && input.getAttribute("data-max-files")) || "4", 10) || 4;
  }

  function projectedTotal(kind, fieldPrefix, idPrefix) {
    return (
      countKeptExisting(kind, fieldPrefix, idPrefix) +
      getQueue(fieldPrefix, idPrefix).length
    );
  }

  function setSlotError(kind, idPrefix, message) {
    idPrefix = idPrefix || "";
    var box = el(idPrefix + kind + "SlotError");
    if (!box) return;
    if (message) {
      box.textContent = message;
      box.style.display = "block";
    } else {
      box.textContent = "";
      box.style.display = "none";
    }
  }

  function clearSlotError(kind, idPrefix) {
    setSlotError(kind, idPrefix, "");
  }

  function formatRemaining(n) {
    return String(labels.remaining || "{n} remaining").replace(/\{n\}/g, String(n));
  }

  function updateSlotMeter(kind, fieldPrefix, idPrefix) {
    idPrefix = idPrefix || "";
    var input = el(fileInputId(fieldPrefix, idPrefix));
    var meter = el(idPrefix + kind + "SlotMeter");
    var countEl = el(idPrefix + kind + "SlotCount");
    var remainEl = el(idPrefix + kind + "SlotRemain");
    if (!input) return { total: 0, maxFiles: 4, remaining: 4, over: false };
    var maxFiles = maxForInput(input);
    var total = projectedTotal(kind, fieldPrefix, idPrefix);
    var remaining = Math.max(0, maxFiles - total);
    var over = total > maxFiles;
    if (countEl) countEl.textContent = total + "/" + maxFiles;
    if (remainEl) {
      remainEl.textContent = over ? "" : formatRemaining(remaining);
    }
    if (meter) {
      meter.classList.toggle("is-full", !over && remaining === 0);
      meter.classList.toggle("is-over", over);
    }
    var headCount = el(idPrefix + kind + "ExistingHeadCount");
    if (headCount) {
      headCount.textContent =
        "(" + countKeptExisting(kind, fieldPrefix, idPrefix) + "/" + maxFiles + ")";
    }
    return { total: total, maxFiles: maxFiles, remaining: remaining, over: over };
  }

  function syncInputFiles(fieldPrefix, idPrefix) {
    var input = el(fileInputId(fieldPrefix, idPrefix));
    if (!input) return false;
    var q = getQueue(fieldPrefix, idPrefix);
    try {
      var dt = new DataTransfer();
      q.forEach(function (f) {
        dt.items.add(f);
      });
      input.files = dt.files;
      return true;
    } catch (_e) {
      return false;
    }
  }

  function renderPending(kind, fieldPrefix, idPrefix) {
    idPrefix = idPrefix || "";
    var list = el(idPrefix + kind + "PendingList");
    var wrap = el(idPrefix + kind + "PendingWrap");
    var hint = el(idPrefix + kind + "ReplaceHint");
    var zone = el(idPrefix + kind + "Zone");
    var q = getQueue(fieldPrefix, idPrefix);
    if (list) {
      list.innerHTML = "";
      q.forEach(function (file, index) {
        var li = document.createElement("li");
        li.className = "attach-pending__item";
        var name = document.createElement("span");
        name.className = "attach-pending__name";
        name.textContent = file.name || "file";
        name.title = file.name || "";
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-sm btn-outline-danger attach-pending__remove";
        btn.textContent = labels.removeOne;
        btn.addEventListener("click", function () {
          removePendingAt(kind, fieldPrefix, idPrefix, index);
        });
        li.appendChild(name);
        li.appendChild(btn);
        list.appendChild(li);
      });
    }
    if (wrap) wrap.style.display = q.length ? "block" : "none";
    if (hint) hint.style.display = q.length ? "block" : "none";
    if (zone) {
      if (q.length) zone.classList.add("is-filled");
      else zone.classList.remove("is-filled");
    }
    var selected = el(idPrefix + kind + "Selected");
    if (selected) selected.style.display = "none";
    refreshAvailability(kind, fieldPrefix, idPrefix);
  }

  function refreshAvailability(kind, fieldPrefix, idPrefix) {
    idPrefix = idPrefix || "";
    var input = el(fileInputId(fieldPrefix, idPrefix));
    var zone = el(idPrefix + kind + "Zone");
    var limitHint = el(idPrefix + kind + "LimitHint");
    if (!input) return;
    var state = updateSlotMeter(kind, fieldPrefix, idPrefix);
    var room = state.remaining;
    var full = !state.over && room <= 0;
    input.disabled = full;
    if (zone) zone.style.opacity = full ? ".55" : "";
    if (limitHint) {
      limitHint.style.display = full ? "block" : "none";
      if (full) {
        limitHint.textContent = labels.limitFull + " (" + state.maxFiles + ")";
      }
    }
    if (state.over) {
      setSlotError(
        kind,
        idPrefix,
        labels.exceedLimit + " (" + state.total + "/" + state.maxFiles + ")"
      );
    } else {
      clearSlotError(kind, idPrefix);
    }
  }

  function clearQueue(fieldPrefix, idPrefix) {
    queues[keyFor(fieldPrefix, idPrefix)] = [];
    syncInputFiles(fieldPrefix, idPrefix);
  }

  function removePendingAt(kind, fieldPrefix, idPrefix, index) {
    var q = getQueue(fieldPrefix, idPrefix);
    if (index < 0 || index >= q.length) return;
    q.splice(index, 1);
    syncInputFiles(fieldPrefix, idPrefix);
    renderPending(kind, fieldPrefix, idPrefix);
  }

  function sameFile(a, b) {
    return (
      a &&
      b &&
      a.name === b.name &&
      a.size === b.size &&
      a.lastModified === b.lastModified
    );
  }

  function onFilesChosen(input, kind, fieldPrefix, idPrefix) {
    idPrefix = idPrefix || "";
    if (!input) return;
    var removeAll = el(
      idPrefix === "review-" ? "review-remove-" + kind : "remove-" + kind
    );
    var panel = el(idPrefix + kind + "ExistingPanel");
    var notice = el(idPrefix + kind + "RemovedNotice");
    var hadRemove = removeAll && removeAll.value === "1";
    if (removeAll) removeAll.value = "0";
    if (notice) notice.style.display = "none";
    if (panel) {
      panel.style.display = hadRemove ? "none" : "";
      panel.querySelectorAll(".js-attach-item-remove").forEach(function (cb) {
        cb.disabled = false;
      });
    }

    var maxFiles = maxForInput(input);
    var q = getQueue(fieldPrefix, idPrefix);
    var kept = countKeptExisting(kind, fieldPrefix, idPrefix);
    var room = Math.max(0, maxFiles - kept - q.length);
    var incoming = input.files ? Array.prototype.slice.call(input.files) : [];

    incoming.forEach(function (file) {
      if (room <= 0) return;
      var dup = q.some(function (f) {
        return sameFile(f, file);
      });
      if (dup) return;
      q.push(file);
      room -= 1;
    });

    try {
      input.value = "";
    } catch (_e2) {}
    syncInputFiles(fieldPrefix, idPrefix);
    renderPending(kind, fieldPrefix, idPrefix);
  }

  function onRemoveCheckboxChange(cb) {
    var kind = cb.getAttribute("data-kind") || "";
    var name = cb.getAttribute("name") || "";
    var prefix = name.replace(/^remove_/, "").replace(/_item$/, "");
    var idPrefix = cb.closest("#reviewAttachmentSections") ? "review-" : "";
    var input = el(fileInputId(prefix, idPrefix));
    var maxFiles = maxForInput(input);

    // Unchecking = keep the existing file. Block if that would exceed the limit.
    if (!cb.checked) {
      var total = projectedTotal(kind, prefix, idPrefix);
      if (total > maxFiles) {
        cb.checked = true;
        refreshAvailability(kind, prefix, idPrefix);
        setSlotError(kind, idPrefix, labels.cannotUncheck);
        try {
          cb.focus();
        } catch (_f) {}
        return false;
      }
    }
    refreshAvailability(kind, prefix, idPrefix);
    return true;
  }

  function bindItemRemoveHandlers(root) {
    var scope = root || document;
    scope.querySelectorAll(".js-attach-item-remove").forEach(function (cb) {
      if (cb.dataset.multiBound === "1") return;
      cb.dataset.multiBound = "1";
      cb.addEventListener("change", function () {
        onRemoveCheckboxChange(cb);
      });
    });
  }

  function initRoot(root) {
    if (!root) return;
    var idPrefix = root.id === "reviewAttachmentSections" ? "review-" : "";
    root.querySelectorAll(".js-attachment-slot").forEach(function (slot) {
      var kind = slot.getAttribute("data-kind") || "";
      var fieldPrefix = slot.getAttribute("data-field-prefix") || "";
      if (!kind || !fieldPrefix) return;
      refreshAvailability(kind, fieldPrefix, idPrefix);
    });
  }

  function syncAllQueues() {
    Object.keys(queues).forEach(function (key) {
      var parts = key.split(":");
      var idPrefix = parts[0] || "";
      var fieldPrefix = parts.slice(1).join(":");
      syncInputFiles(fieldPrefix, idPrefix);
    });
  }

  function validateRoot(root) {
    if (!root) return true;
    var idPrefix = root.id === "reviewAttachmentSections" ? "review-" : "";
    var ok = true;
    var firstBad = null;
    root.querySelectorAll(".js-attachment-slot").forEach(function (slot) {
      var kind = slot.getAttribute("data-kind") || "";
      var fieldPrefix = slot.getAttribute("data-field-prefix") || "";
      if (!kind || !fieldPrefix) return;
      var input = el(fileInputId(fieldPrefix, idPrefix));
      var maxFiles = maxForInput(input);
      var total = projectedTotal(kind, fieldPrefix, idPrefix);
      if (total > maxFiles) {
        ok = false;
        setSlotError(
          kind,
          idPrefix,
          labels.exceedLimit +
            " (" +
            total +
            "/" +
            maxFiles +
            ")"
        );
        if (!firstBad) firstBad = el(idPrefix + kind + "SlotError") || slot;
      } else {
        clearSlotError(kind, idPrefix);
      }
    });
    if (!ok && firstBad) {
      try {
        firstBad.scrollIntoView({ behavior: "smooth", block: "center" });
      } catch (_s) {}
    }
    return ok;
  }

  window.AttachmentMultiSelect = {
    setLabels: setLabels,
    onFilesChosen: onFilesChosen,
    clearQueue: clearQueue,
    renderPending: renderPending,
    refreshAvailability: refreshAvailability,
    bindItemRemoveHandlers: bindItemRemoveHandlers,
    initRoot: initRoot,
    getQueue: getQueue,
    syncAllQueues: syncAllQueues,
    validateRoot: validateRoot,
  };
})(window);
