(function () {
    function getCsrfToken(fallback) {
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : (fallback || '');
    }

    function memberLabel(member) {
        return member.name + ' (@' + member.username + ')';
    }

    function memberSearchText(member) {
        return (member.name + ' ' + member.username).toLowerCase();
    }

    function sortListItems(listEl) {
        var items = Array.prototype.slice.call(listEl.querySelectorAll('.dv-picker-item'));
        items.sort(function (a, b) {
            var aText = (a.dataset.search || a.textContent || '');
            var bText = (b.dataset.search || b.textContent || '');
            return aText.localeCompare(bText, undefined, { sensitivity: 'base' });
        });
        items.forEach(function (item) {
            listEl.appendChild(item);
        });
    }

    function getSelectedItems(listEl) {
        return Array.prototype.slice.call(listEl.querySelectorAll('.dv-picker-item.is-selected'));
    }

    function clearSelection(listEl) {
        listEl.querySelectorAll('.dv-picker-item.is-selected').forEach(function (item) {
            item.classList.remove('is-selected');
        });
    }

    function applyFilter(listEl, query) {
        var q = (query || '').trim().toLowerCase();
        listEl.querySelectorAll('.dv-picker-item').forEach(function (item) {
            var match = !q || (item.dataset.search || '').indexOf(q) !== -1;
            item.hidden = !match;
            if (!match) item.classList.remove('is-selected');
        });
    }

    function bindListSelection(listEl) {
        listEl.addEventListener('click', function (event) {
            if (event.target.closest('.dv-attach-panel') || event.target.closest('.dv-attach-toggle')) {
                return;
            }
            var item = event.target.closest('.dv-picker-item');
            if (!item || !listEl.contains(item)) return;
            if (event.ctrlKey || event.metaKey) {
                item.classList.toggle('is-selected');
                return;
            }
            if (event.shiftKey) {
                item.classList.add('is-selected');
                return;
            }
            clearSelection(listEl);
            item.classList.add('is-selected');
        });
    }

    window.initDashboardViewersModal = function (options) {
        var modalEl = document.getElementById(options.modalId || 'viewersModal');
        if (!modalEl) return;

        var transferEl = document.getElementById('viewersTransfer');
        var availableList = document.getElementById('viewersAvailableList');
        var chosenList = document.getElementById('viewersChosenList');
        var availableFilter = document.getElementById('viewersAvailableFilter');
        var chosenFilter = document.getElementById('viewersChosenFilter');
        var loadingEl = document.getElementById('viewersLoading');
        var saveBtn = document.getElementById(options.saveBtnId || 'viewersSaveBtn');
        var errorEl = document.getElementById(options.errorId || 'viewersError');
        var viewersUrl = '';
        var attachmentKindOptions = [];
        var memberById = {};

        var labels = {
            attachmentsLabel: options.attachmentsLabel || 'Allowed attachment items',
            attachmentsNone: options.attachmentsNone || 'No attachments',
            attachmentsAll: options.attachmentsAll || 'All items',
            selectAll: options.attachmentsSelectAll || 'Select all',
            clearAll: options.attachmentsClear || 'Clear all',
        };

        if (!availableList || !chosenList) return;

        bindListSelection(availableList);
        bindListSelection(chosenList);

        function setLoading(isLoading) {
            if (loadingEl) loadingEl.classList.toggle('d-none', !isLoading);
            if (transferEl) transferEl.classList.toggle('d-none', isLoading);
            if (saveBtn) saveBtn.disabled = isLoading;
        }

        function hideError() {
            if (!errorEl) return;
            errorEl.classList.add('d-none');
            errorEl.textContent = '';
        }

        function showError(message) {
            if (!errorEl) return;
            errorEl.textContent = message;
            errorEl.classList.remove('d-none');
        }

        function resetFilters() {
            if (availableFilter) {
                availableFilter.value = '';
                applyFilter(availableList, '');
            }
            if (chosenFilter) {
                chosenFilter.value = '';
                applyFilter(chosenList, '');
            }
        }

        function getItemKinds(item) {
            try {
                var raw = item.dataset.attachmentKinds || '[]';
                var parsed = JSON.parse(raw);
                return Array.isArray(parsed) ? parsed.map(String) : [];
            } catch (_err) {
                return [];
            }
        }

        function setItemKinds(item, kinds) {
            var unique = [];
            var seen = {};
            (kinds || []).forEach(function (k) {
                var code = String(k);
                if (!seen[code]) {
                    seen[code] = true;
                    unique.push(code);
                }
            });
            item.dataset.attachmentKinds = JSON.stringify(unique);
            updateAttachSummary(item);
            syncAttachCheckboxes(item);
        }

        function updateAttachSummary(item) {
            var summary = item.querySelector('.dv-attach-summary');
            if (!summary) return;
            var kinds = getItemKinds(item);
            if (!kinds.length) {
                summary.textContent = labels.attachmentsNone;
                return;
            }
            if (attachmentKindOptions.length && kinds.length >= attachmentKindOptions.length) {
                summary.textContent = labels.attachmentsAll;
                return;
            }
            summary.textContent = String(kinds.length);
        }

        function syncAttachCheckboxes(item) {
            var kinds = getItemKinds(item);
            var set = {};
            kinds.forEach(function (k) { set[k] = true; });
            item.querySelectorAll('.dv-attach-check').forEach(function (cb) {
                cb.checked = !!set[cb.value];
            });
        }

        function createAvailableItem(member) {
            var li = document.createElement('li');
            li.className = 'dv-picker-item';
            li.setAttribute('role', 'option');
            li.dataset.userId = String(member.id);
            li.dataset.search = memberSearchText(member);
            li.dataset.attachmentKinds = JSON.stringify(member.attachment_kinds || []);
            li.textContent = memberLabel(member);
            return li;
        }

        function createChosenItem(member) {
            var li = document.createElement('li');
            li.className = 'dv-picker-item dv-picker-item--with-attach';
            li.setAttribute('role', 'option');
            li.dataset.userId = String(member.id);
            li.dataset.search = memberSearchText(member);
            li.dataset.attachmentKinds = JSON.stringify(member.attachment_kinds || []);

            var row = document.createElement('div');
            row.className = 'dv-picker-row';

            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'dv-attach-toggle';
            toggle.setAttribute('aria-expanded', 'false');
            toggle.title = labels.attachmentsLabel;
            toggle.innerHTML = '<i class="bi bi-chevron-down" aria-hidden="true"></i>';

            var name = document.createElement('span');
            name.className = 'dv-picker-name';
            name.textContent = memberLabel(member);

            var summary = document.createElement('span');
            summary.className = 'dv-attach-summary';

            row.appendChild(toggle);
            row.appendChild(name);
            row.appendChild(summary);
            li.appendChild(row);

            var panel = document.createElement('div');
            panel.className = 'dv-attach-panel d-none';

            var panelLabel = document.createElement('div');
            panelLabel.className = 'dv-attach-panel-label';
            panelLabel.textContent = labels.attachmentsLabel;
            panel.appendChild(panelLabel);

            var actions = document.createElement('div');
            actions.className = 'dv-attach-actions';
            var selectAllBtn = document.createElement('button');
            selectAllBtn.type = 'button';
            selectAllBtn.className = 'dv-attach-select-all btn btn-link btn-sm p-0';
            selectAllBtn.textContent = labels.selectAll;
            var clearBtn = document.createElement('button');
            clearBtn.type = 'button';
            clearBtn.className = 'dv-attach-clear btn btn-link btn-sm p-0';
            clearBtn.textContent = labels.clearAll;
            actions.appendChild(selectAllBtn);
            actions.appendChild(clearBtn);
            panel.appendChild(actions);

            var checks = document.createElement('div');
            checks.className = 'dv-attach-checks';
            attachmentKindOptions.forEach(function (opt) {
                var lab = document.createElement('label');
                lab.className = 'dv-attach-kind';
                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.className = 'dv-attach-check form-check-input';
                cb.value = opt.kind;
                var span = document.createElement('span');
                span.textContent = opt.label || opt.kind;
                lab.appendChild(cb);
                lab.appendChild(span);
                checks.appendChild(lab);
            });
            panel.appendChild(checks);
            li.appendChild(panel);

            toggle.addEventListener('click', function (event) {
                event.stopPropagation();
                var open = panel.classList.contains('d-none');
                panel.classList.toggle('d-none', !open);
                toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
                toggle.querySelector('i').className = open ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
            });

            selectAllBtn.addEventListener('click', function (event) {
                event.stopPropagation();
                setItemKinds(
                    li,
                    attachmentKindOptions.map(function (o) { return o.kind; })
                );
            });
            clearBtn.addEventListener('click', function (event) {
                event.stopPropagation();
                setItemKinds(li, []);
            });
            checks.addEventListener('change', function (event) {
                if (!event.target.classList.contains('dv-attach-check')) return;
                var selected = [];
                li.querySelectorAll('.dv-attach-check:checked').forEach(function (cb) {
                    selected.push(cb.value);
                });
                setItemKinds(li, selected);
            });
            checks.addEventListener('click', function (event) {
                event.stopPropagation();
            });

            updateAttachSummary(li);
            syncAttachCheckboxes(li);
            return li;
        }

        function toChosenItem(item) {
            var userId = parseInt(item.dataset.userId, 10);
            var member = memberById[userId] || {
                id: userId,
                name: item.textContent.trim(),
                username: '',
                attachment_kinds: getItemKinds(item),
            };
            member.attachment_kinds = getItemKinds(item);
            return createChosenItem(member);
        }

        function toAvailableItem(item) {
            var userId = parseInt(item.dataset.userId, 10);
            var member = memberById[userId] || {
                id: userId,
                name: (item.querySelector('.dv-picker-name') || item).textContent.trim(),
                username: '',
                attachment_kinds: getItemKinds(item),
            };
            member.attachment_kinds = getItemKinds(item);
            return createAvailableItem(member);
        }

        function moveItems(items, toList, asChosen) {
            if (!items.length) return;
            items.forEach(function (item) {
                item.classList.remove('is-selected');
                var next = asChosen ? toChosenItem(item) : toAvailableItem(item);
                item.remove();
                toList.appendChild(next);
            });
            sortListItems(toList);
        }

        function moveSelected(fromList, toList, asChosen) {
            moveItems(getSelectedItems(fromList), toList, asChosen);
        }

        function moveAll(fromList, toList, filterText, asChosen) {
            var q = (filterText || '').trim().toLowerCase();
            var items = Array.prototype.slice.call(fromList.querySelectorAll('.dv-picker-item')).filter(function (item) {
                if (item.hidden) return false;
                if (!q) return true;
                return (item.dataset.search || '').indexOf(q) !== -1;
            });
            moveItems(items, toList, asChosen);
        }

        function populateLists(members) {
            availableList.innerHTML = '';
            chosenList.innerHTML = '';
            memberById = {};
            members.forEach(function (member) {
                memberById[member.id] = member;
                if (member.assigned) {
                    chosenList.appendChild(createChosenItem(member));
                } else {
                    availableList.appendChild(createAvailableItem(member));
                }
            });
            sortListItems(availableList);
            sortListItems(chosenList);
        }

        function loadMembers() {
            hideError();
            resetFilters();
            setLoading(true);
            fetch(viewersUrl, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            }).then(function (res) {
                if (!res.ok) throw new Error('load failed');
                return res.json();
            }).then(function (data) {
                attachmentKindOptions = data.attachment_kind_options || [];
                var members = data.members || [];
                if (!members.length) {
                    showError(options.emptyText || 'No members');
                }
                populateLists(members);
                setLoading(false);
                if (saveBtn) saveBtn.disabled = false;
            }).catch(function () {
                setLoading(false);
                showError(options.errorText || 'Error');
            });
        }

        document.querySelectorAll(options.triggerSelector || '.js-viewers-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                viewersUrl = btn.getAttribute('data-viewers-url') || '';
                loadMembers();
            });
        });

        document.getElementById('viewersChooseBtn').addEventListener('click', function () {
            moveSelected(availableList, chosenList, true);
        });
        document.getElementById('viewersRemoveBtn').addEventListener('click', function () {
            moveSelected(chosenList, availableList, false);
        });
        document.getElementById('viewersChooseAll').addEventListener('click', function () {
            moveAll(availableList, chosenList, availableFilter ? availableFilter.value : '', true);
        });
        document.getElementById('viewersRemoveAll').addEventListener('click', function () {
            moveAll(chosenList, availableList, chosenFilter ? chosenFilter.value : '', false);
        });

        if (availableFilter) {
            availableFilter.addEventListener('input', function () {
                applyFilter(availableList, availableFilter.value);
            });
        }
        if (chosenFilter) {
            chosenFilter.addEventListener('input', function () {
                applyFilter(chosenList, chosenFilter.value);
            });
        }

        availableList.addEventListener('dblclick', function (event) {
            if (event.target.closest('.dv-attach-panel') || event.target.closest('.dv-attach-toggle')) return;
            var item = event.target.closest('.dv-picker-item');
            if (!item || !availableList.contains(item)) return;
            item.classList.add('is-selected');
            moveSelected(availableList, chosenList, true);
        });
        chosenList.addEventListener('dblclick', function (event) {
            if (event.target.closest('.dv-attach-panel') || event.target.closest('.dv-attach-toggle')) return;
            var item = event.target.closest('.dv-picker-item');
            if (!item || !chosenList.contains(item)) return;
            item.classList.add('is-selected');
            moveSelected(chosenList, availableList, false);
        });

        if (saveBtn) {
            saveBtn.addEventListener('click', function () {
                hideError();
                saveBtn.disabled = true;
                var assignments = [];
                chosenList.querySelectorAll('.dv-picker-item').forEach(function (item) {
                    assignments.push({
                        user_id: parseInt(item.dataset.userId, 10),
                        attachment_kinds: getItemKinds(item),
                    });
                });
                var formData = new FormData();
                formData.append('assignments', JSON.stringify(assignments));
                fetch(viewersUrl, {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': getCsrfToken(options.csrfToken),
                    },
                    body: formData,
                }).then(function (res) {
                    if (!res.ok) throw new Error('save failed');
                    return res.json();
                }).then(function () {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) modal.hide();
                }).catch(function () {
                    showError(options.errorText || 'Error');
                }).finally(function () {
                    saveBtn.disabled = false;
                });
            });
        }
    };
})();
