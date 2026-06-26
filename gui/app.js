/* ==========================================================================
   Stoddard Financial — Trading System
   Frontend logic for the pywebview desktop app. Vanilla JS, no dependencies.
   ========================================================================== */
(function () {
  'use strict';

  // ------------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------------
  let state = null;          // last bootstrap/get_state payload
  let inFlight = false;      // a chat request is pending
  let initialized = false;   // init() has been started
  let bannerDismissed = false;
  let activeConfirm = null;  // container of live Confirm/Cancel buttons
  let typingEl = null;       // typing indicator bubble
  let bridgePoll = null;     // startup bridge-availability poll interval id
  let editingBuyList = false;     // a buy-list add/remove is pending
  let pickingFile = false;        // a pick_data_file dialog/reload is pending
  let needsFile = false;          // sticky: bootstrap said the holdings file is missing
  let holdingsReq = 0;            // monotonic token for get_holdings responses
  let settingsReturnFocus = null; // element to refocus when settings closes
  let holdingsReturnFocus = null; // element to refocus when holdings closes
  let currentProposal = null;     // latest staged proposal reply (for the modal)
  let planReturnFocus = null;     // element to refocus when the plan modal closes
  let planStaged = false;         // a plan is staged and awaiting the advisor

  const $ = function (id) { return document.getElementById(id); };

  function api() { return window.pywebview.api; }

  // ------------------------------------------------------------------------
  // Formatting helpers
  // ------------------------------------------------------------------------
  function fmtMoney(v) {
    var n = Number(v) || 0;
    var sign = n < 0 ? '−' : '';
    return sign + '$' + Math.round(Math.abs(n)).toLocaleString('en-US');
  }

  function fmtPrice(v) {
    var n = Number(v) || 0;
    var sign = n < 0 ? '−' : '';
    return sign + '$' + Math.abs(n).toLocaleString('en-US', {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }

  function fmtPct(v) {
    return (Number(v) || 0).toFixed(1) + '%';
  }

  function fmtShares(v) {
    if (v === null || v === undefined || v === '') return '—';
    var n = Number(v);
    if (!isFinite(n)) return '—';
    if (Math.abs(n - Math.round(n)) < 1e-9) {
      return Math.round(n).toLocaleString('en-US');
    }
    return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // ------------------------------------------------------------------------
  // HTML escaping + minimal markdown (escape FIRST, then markup)
  // ------------------------------------------------------------------------
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function mdInline(s) {
    // operates on already-escaped text. Stash `code` spans behind NUL-framed
    // placeholders first so the bold/italic regexes can never rewrite their
    // contents, then restore them as <code> tags.
    var codes = [];
    s = s.replace(/`([^`]+)`/g, function (_, body) {
      codes.push(body);
      return '\u0000' + (codes.length - 1) + '\u0000';
    });
    s = s
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*\s][^*]*)\*/g, '<em>$1</em>');
    return s.replace(/\u0000(\d+)\u0000/g, function (_, i) {
      return '<code>' + codes[Number(i)] + '</code>';
    });
  }

  function renderMarkdown(text) {
    var lines = esc(text).split(/\r?\n/);
    var html = '';
    var listOpen = false;
    var para = [];

    function flushPara() {
      if (para.length) {
        html += '<p>' + para.join('<br>') + '</p>';
        para = [];
      }
    }
    function closeList() {
      if (listOpen) { html += '</ul>'; listOpen = false; }
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var bullet = line.match(/^\s*[-*]\s+(.*)$/);
      if (bullet) {
        flushPara();
        if (!listOpen) { html += '<ul>'; listOpen = true; }
        html += '<li>' + mdInline(bullet[1]) + '</li>';
      } else if (/^\s*$/.test(line)) {
        closeList();
        flushPara();
      } else {
        closeList();
        para.push(mdInline(line));
      }
    }
    closeList();
    flushPara();
    return html;
  }

  // ------------------------------------------------------------------------
  // Toasts
  // ------------------------------------------------------------------------
  function toast(message, type, duration) {
    var el = document.createElement('div');
    el.className = 'toast ' + (type || 'info');
    el.textContent = message;
    el.title = 'Click to dismiss';
    $('toast-container').appendChild(el);
    var ttl = duration || 4500;
    var hideTimer = setTimeout(function () {
      el.classList.add('leaving');
      setTimeout(function () { el.remove(); }, 300);
    }, ttl);
    el.addEventListener('click', function () {
      clearTimeout(hideTimer);
      el.remove();
    });
  }

  // ------------------------------------------------------------------------
  // Boot
  // ------------------------------------------------------------------------
  async function init() {
    if (initialized) return;
    initialized = true;

    $('loading-screen').classList.remove('hidden');
    $('error-screen').classList.add('hidden');

    var r;
    try {
      r = await api().bootstrap();
    } catch (e) {
      r = { ok: false, error: 'Could not reach the application backend: ' + e };
    }

    if (!r || !r.ok) {
      // needs_file means the failure is recoverable in-app via the picker;
      // sticky so a later, differently-worded failure keeps the button
      if (r && r.needs_file) needsFile = true;
      showBootError((r && r.error) || 'Unknown error during startup.');
      initialized = false; // allow Retry
      return;
    }

    finishBootstrap(r);
  }

  // Shared post-bootstrap initialization — used by the normal boot path and by
  // a successful pick_data_file() (which returns the same payload shape).
  function finishBootstrap(r) {
    initialized = true;
    state = r;
    renderState();
    $('loading-screen').classList.add('hidden');
    $('error-screen').classList.add('hidden');
    $('app').classList.remove('hidden');

    addWelcomeMessage();
    // A freshly loaded backend has no staged plan; keep the bar in sync anyway.
    planStaged = !!state.awaiting_confirmation;
    updateStagedBar();
    $('composer-input').focus();
  }

  function showBootError(message) {
    $('loading-screen').classList.add('hidden');
    $('error-message').textContent = message || 'Unknown error during startup.';
    $('error-locate').classList.toggle('hidden', !needsFile);
    $('error-screen').classList.remove('hidden');
  }

  function clearBridgePoll() {
    if (bridgePoll !== null) {
      clearInterval(bridgePoll);
      bridgePoll = null;
    }
  }

  function startup() {
    if (window.pywebview && window.pywebview.api) {
      clearBridgePoll();
      init();
      return;
    }
    window.addEventListener('pywebviewready', function () {
      clearBridgePoll();
      init();
    }, { once: true });

    // Polling fallback: on some WebKit builds the pywebviewready event fires
    // before the listener above is attached. Poll every 250ms; if the bridge
    // still hasn't appeared after ~15s, show the error screen instead of
    // spinning forever. The poll is cleared as soon as either path runs init()
    // so a failed bootstrap can't be re-triggered by a stale interval.
    var waited = 0;
    bridgePoll = setInterval(function () {
      if (window.pywebview && window.pywebview.api) {
        clearBridgePoll();
        init();
        return;
      }
      waited += 250;
      if (waited >= 15000) {
        clearBridgePoll();
        if (initialized) return;
        showBootError(
          'The Python bridge (window.pywebview) never became available after 15 seconds. ' +
          'The backend may have failed to start — close this window and relaunch the ' +
          'application, or run it from a terminal to see the underlying error.');
      }
    }, 250);
  }

  function addWelcomeMessage() {
    var n = state.accounts.length;
    var text = 'Loaded **' + n + ' account' + (n === 1 ? '' : 's') + '** · ' +
      fmtMoney(state.total_value) + ' under management.\n' +
      'Describe a trade in plain English, type `default` to run the standard spec, ' +
      'or `help` for examples. Nothing is executed without your confirmation.';
    addAssistantMarkdown(text);
  }

  // ------------------------------------------------------------------------
  // State rendering (top bar, sidebar, banner, settings)
  // ------------------------------------------------------------------------
  function renderState() {
    renderTopbar();
    renderAccounts();
    renderBuyList();
    renderKeyBanner();
    renderSettings();
  }

  function renderTopbar() {
    $('stat-aum').textContent = fmtMoney(state.total_value);
    $('stat-accounts').textContent = String(state.accounts.length);
    $('stat-prices').textContent = state.prices_as_of || '—';
    $('topbar-version').textContent = 'v' + state.version;
  }

  function renderAccounts() {
    var filter = $('account-filter').value.trim().toLowerCase();
    var list = $('account-list');
    list.textContent = '';

    var shown = 0;
    state.accounts.forEach(function (a) {
      var hay = (a.client_name + ' ' + a.number).toLowerCase();
      if (filter && hay.indexOf(filter) === -1) return;
      shown++;

      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'acct-row';

      var line1 = document.createElement('div');
      line1.className = 'acct-line1';
      var name = document.createElement('span');
      name.className = 'acct-name';
      name.textContent = a.client_name || '(unnamed)';
      var total = document.createElement('span');
      total.className = 'acct-total';
      total.textContent = fmtMoney(a.total);
      line1.appendChild(name);
      line1.appendChild(total);

      var meta = document.createElement('div');
      meta.className = 'acct-meta';
      meta.textContent = a.n_positions + ' pos · ' + fmtPct(a.cash_pct) + ' cash';

      row.appendChild(line1);
      row.appendChild(meta);
      row.addEventListener('click', function () { openHoldings(a.number); });
      list.appendChild(row);
    });

    if (!shown) {
      var empty = document.createElement('div');
      empty.className = 'side-empty';
      empty.textContent = filter ? 'No accounts match “' + filter + '”.' : 'No accounts.';
      list.appendChild(empty);
    }

    $('accounts-count').textContent =
      filter ? shown + ' / ' + state.accounts.length : String(state.accounts.length);
  }

  function renderBuyList() {
    var list = $('buy-list');
    list.textContent = '';

    if (!state.buy_list.length) {
      var empty = document.createElement('div');
      empty.className = 'side-empty';
      empty.textContent = 'Buy list is empty. Add a ticker below.';
      list.appendChild(empty);
    }

    state.buy_list.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'buy-row';

      var ticker = document.createElement('span');
      ticker.className = 'buy-ticker';
      ticker.textContent = item.ticker;

      var price = document.createElement('span');
      price.className = 'buy-price';
      price.textContent = fmtPrice(item.price);

      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'buy-remove';
      remove.title = 'Remove ' + item.ticker + ' from buy list';
      remove.setAttribute('aria-label', 'Remove ' + item.ticker);
      remove.innerHTML =
        '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2.4" stroke-linecap="round" aria-hidden="true">' +
        '<path d="M18 6 6 18M6 6l12 12"></path></svg>';
      remove.disabled = inFlight || editingBuyList;
      remove.addEventListener('click', function () { removeBuyTicker(item.ticker); });

      row.appendChild(ticker);
      row.appendChild(price);
      row.appendChild(remove);
      list.appendChild(row);
    });

    // mtime of the CSV — it also bumps on manual ticker edits, so this is
    // "when the list last changed", not a price-freshness claim
    $('prices-caption').textContent =
      state.prices_as_of ? 'List updated ' + state.prices_as_of : '';
  }

  function renderKeyBanner() {
    var show = !state.api_key_set && !bannerDismissed;
    $('key-banner').classList.toggle('hidden', !show);
  }

  function renderSettings() {
    $('settings-version').textContent = 'v' + state.version;
    $('settings-model').textContent = state.model || '—';
    var status = $('settings-key-status');
    if (state.api_key_set) {
      status.textContent = 'Configured';
      status.className = 'kv-val key-ok';
    } else {
      status.textContent = 'Not set';
      status.className = 'kv-val key-missing';
    }
    renderPathRow($('settings-data-path'), state.investment_data_path, 'Not set');
    renderPathRow($('settings-exports-path'), state.exports_dir, '—');
  }

  // Fills a .data-row-path span. The CSS renders these spans RTL so that
  // overflow ellipsizes on the LEFT and the filename tail stays visible;
  // wrapping the text in LRI…PDI isolates keeps the characters in logical
  // order despite the RTL paragraph direction. Full path goes in the title.
  function renderPathRow(el, path, emptyLabel) {
    path = String(path == null ? '' : path);
    if (path) {
      el.textContent = '\u2066' + path + '\u2069'; // LRI + path + PDI
      el.title = path;
      el.classList.remove('empty');
    } else {
      el.textContent = emptyLabel;
      el.title = '';
      el.classList.add('empty');
    }
  }

  async function refreshState() {
    var r;
    try { r = await api().get_state(); } catch (e) { return; }
    if (r && r.ok) {
      state = r;
      renderState();
    }
  }

  // ------------------------------------------------------------------------
  // Chat thread
  // ------------------------------------------------------------------------
  function thread() { return $('chat-thread'); }

  function scrollChat() {
    var t = thread();
    t.scrollTop = t.scrollHeight;
  }

  function addUserMessage(text) {
    var el = document.createElement('div');
    el.className = 'msg msg-user';
    el.textContent = text;
    thread().appendChild(el);
    scrollChat();
  }

  function addAssistantMarkdown(text) {
    // Never render an empty/whitespace-only bubble (it shows as a blank message).
    if (text == null || String(text).trim() === '') return false;
    var el = document.createElement('div');
    el.className = 'msg msg-assistant';
    el.innerHTML = renderMarkdown(text);
    thread().appendChild(el);
    scrollChat();
    return true;
  }

  function addErrorMessage(text) {
    var el = document.createElement('div');
    el.className = 'msg msg-error';
    var label = document.createElement('span');
    label.className = 'msg-error-label';
    label.textContent = 'Error';
    var body = document.createElement('span');
    body.textContent = text;
    el.appendChild(label);
    el.appendChild(body);
    thread().appendChild(el);
    scrollChat();
  }

  function showTyping() {
    hideTyping();
    typingEl = document.createElement('div');
    typingEl.className = 'msg msg-typing';
    typingEl.innerHTML = '<i></i><i></i><i></i>';
    thread().appendChild(typingEl);
    scrollChat();
  }

  function hideTyping() {
    if (typingEl) { typingEl.remove(); typingEl = null; }
  }

  function setBuyListControlsDisabled(disabled) {
    $('add-btn').disabled = disabled;
    $('clear-btn').disabled = disabled;
    $('buy-list').querySelectorAll('.buy-remove').forEach(function (b) {
      b.disabled = disabled;
    });
  }

  function setBusy(busy) {
    inFlight = busy;
    $('composer-input').disabled = busy;
    $('send-btn').disabled = busy;
    $('chip-default').disabled = busy;
    $('chip-help').disabled = busy;
    // refresh + buy-list controls are shared with their own in-flight flags;
    // never re-enable them here while one of those operations is still pending
    $('chip-refresh').disabled = busy || refreshing;
    $('refresh-btn').disabled = busy || refreshing;
    setBuyListControlsDisabled(busy || editingBuyList);
    if (planStaged) {
      $('staged-confirm').disabled = busy;
      $('staged-discard').disabled = busy;
    }
  }

  function disableActiveConfirm() {
    if (activeConfirm) {
      activeConfirm.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
      activeConfirm = null;
    }
  }

  async function sendMessage(text) {
    text = String(text == null ? '' : text).trim();
    if (!text || inFlight) return;

    disableActiveConfirm();
    addUserMessage(text);
    setBusy(true);
    showTyping();

    var r;
    try {
      r = await api().chat(text);
    } catch (e) {
      r = { error: 'Request failed: ' + e };
    }

    hideTyping();
    setBusy(false);
    handleReply(r);
    $('composer-input').focus();
  }

  function handleReply(r) {
    if (!r) {
      addErrorMessage('Empty response from the backend.');
      return;
    }
    if (r.error) {
      addErrorMessage(r.error);
      return;
    }

    var rendered = false;

    if (addAssistantMarkdown(r.text)) rendered = true;

    if (r.preview) {
      var card = buildProposalCard(r);
      thread().appendChild(card);
      scrollChat();
      rendered = true;
    }
    // A reply with needs_confirmation but no preview (e.g. the model answered a
    // question while a plan is staged) needs no bare card — the persistent
    // staged-plan bar keeps the plan visible and confirmable.

    if (r.exported) {
      thread().appendChild(buildExportCard(r.exported));
      scrollChat();
      refreshState();
      rendered = true;
    }

    // Drive the persistent staged-plan bar from the reply.
    if (r.exported) {
      planStaged = false;
      currentProposal = null;
    } else if (r.needs_confirmation === true) {
      planStaged = true;
    } else if (r.needs_confirmation === false) {
      planStaged = false;
    }
    updateStagedBar();

    if (handleView(r.view)) rendered = true;

    // A reply that produced no visible output at all would look like a blank
    // message — surface a small fallback instead of a silent gap.
    if (!rendered && !r.should_exit) {
      addAssistantMarkdown('Done. What else can I help with?');
    }

    if (r.should_exit) {
      setTimeout(function () {
        try { api().quit(); } catch (e) { /* window already closing */ }
      }, 1200);
    }
  }

  // Returns true if it produced visible output.
  function handleView(view) {
    if (!view) return false;
    if (view === 'help') {
      thread().appendChild(buildHelpCard());
      scrollChat();
      return true;
    } else if (view === 'summary') {
      flashSection('accounts-section');
      return true;
    } else if (view === 'buy_list') {
      flashSection('buylist-section');
      return true;
    } else if (view === 'holdings') {
      if (state && state.accounts.length) {
        openHoldings(state.accounts[0].number);
        addAssistantMarkdown('Showing holdings for **' +
          (state.accounts[0].client_name || state.accounts[0].number) +
          '** — click any account in the sidebar to view another.');
      } else {
        addAssistantMarkdown('Click an account in the sidebar to view its holdings.');
      }
      return true;
    }
    return false;
  }

  function flashSection(id) {
    var el = $(id);
    el.classList.remove('flash');
    // force reflow so the animation can replay
    void el.offsetWidth;
    el.classList.add('flash');
    setTimeout(function () { el.classList.remove('flash'); }, 1500);
  }

  // ------------------------------------------------------------------------
  // Proposal card
  // ------------------------------------------------------------------------
  function buildConfirmActions() {
    var actions = document.createElement('div');
    actions.className = 'prop-actions';

    var confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'btn btn-confirm';
    confirm.textContent = 'Confirm & export';
    confirm.addEventListener('click', confirmPlan);

    var cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn btn-cancel';
    cancel.textContent = 'Discard';
    cancel.addEventListener('click', dismissPlan);

    var hint = document.createElement('span');
    hint.className = 'prop-hint';
    if (state && state.api_key_set) {
      hint.textContent = '…or type a revision below, e.g. “make it 3%”';
    } else {
      // revisions need an API key — only confirm / discard work without one
      hint.textContent = '…or click Discard to cancel';
    }

    actions.appendChild(confirm);
    actions.appendChild(cancel);
    actions.appendChild(hint);
    return actions;
  }

  function buildOrdersTable(orders) {
    var table = document.createElement('table');
    table.className = 'orders-table';
    table.innerHTML =
      '<thead><tr>' +
      '<th>Account</th><th>Client</th><th>Action</th><th>Ticker</th>' +
      '<th class="r">Shares</th><th class="r">Est. Value</th>' +
      '</tr></thead>';
    var tbody = document.createElement('tbody');
    orders.forEach(function (o) {
      var tr = document.createElement('tr');
      var isSell = String(o.action).toLowerCase() === 'sell';
      tr.innerHTML =
        '<td>' + esc(o.account) + '</td>' +
        '<td>' + esc(o.client) + '</td>' +
        '<td class="' + (isSell ? 'action-sell' : 'action-buy') + '">' +
          esc(String(o.action).toUpperCase()) + '</td>' +
        '<td class="ticker">' + esc(o.ticker) + '</td>' +
        '<td class="r">' + esc(fmtShares(o.shares)) + '</td>' +
        '<td class="r">' + esc(fmtPrice(o.value)) + '</td>';
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  function propStat(label, value, cls) {
    var box = document.createElement('div');
    box.className = 'prop-stat';
    var l = document.createElement('span');
    l.className = 'prop-stat-label';
    l.textContent = label;
    var v = document.createElement('span');
    v.className = 'prop-stat-value' + (cls ? ' ' + cls : '');
    v.textContent = value;
    box.appendChild(l);
    box.appendChild(v);
    return box;
  }

  // Renders one engine warning. Warnings are {account, client, message}; the
  // account/client is shown emphasized so a flattened list still says WHICH
  // account each warning applies to. (Tolerates legacy plain-string warnings.)
  function buildWarningItem(w) {
    var li = document.createElement('li');
    if (w && typeof w === 'object') {
      var who = document.createElement('span');
      who.className = 'warn-acct';
      who.textContent = w.account + (w.client ? ' · ' + w.client : '');
      li.appendChild(who);
      li.appendChild(document.createTextNode(': ' + (w.message || '')));
    } else {
      li.textContent = w;
    }
    return li;
  }

  function buildProposalCard(r) {
    var p = r.preview;
    currentProposal = r;   // the modal renders from this
    var card = document.createElement('div');
    card.className = 'card proposal-card';
    card.title = 'Click to view the full plan';

    // header
    var header = document.createElement('div');
    header.className = 'card-header';
    var kicker = document.createElement('span');
    kicker.className = 'card-kicker';
    kicker.textContent = 'Proposed trades';
    var title = document.createElement('span');
    title.className = 'card-title';
    title.textContent = p.description || 'Trade proposal';
    var expand = document.createElement('button');
    expand.type = 'button';
    expand.className = 'prop-expand';
    expand.textContent = 'View full plan ›';
    expand.addEventListener('click', function (e) {
      e.stopPropagation();
      openPlanModal();
    });
    header.appendChild(kicker);
    header.appendChild(title);
    header.appendChild(expand);
    card.appendChild(header);

    // clicking anywhere on the card (except a button) opens the full view
    card.addEventListener('click', function (e) {
      if (e.target.closest('button')) return;
      openPlanModal();
    });

    // stats strip
    var stats = document.createElement('div');
    stats.className = 'prop-stats';
    stats.appendChild(propStat('Accounts', String(p.n_accounts)));
    stats.appendChild(propStat('Sells', p.sell_count + ' · ' + fmtPrice(p.sell_total), 'sell'));
    stats.appendChild(propStat('Buys', p.buy_count + ' · ' + fmtPrice(p.buy_total), 'buy'));
    stats.appendChild(propStat('Net cash impact', fmtPrice(p.sell_total - p.buy_total)));
    card.appendChild(stats);

    // diff line
    if (r.diff) {
      var diff = document.createElement('div');
      diff.className = 'prop-diff';
      var dl = document.createElement('span');
      dl.className = 'prop-diff-label';
      dl.textContent = 'Changed';
      var dt = document.createElement('span');
      dt.textContent = r.diff;
      diff.appendChild(dl);
      diff.appendChild(dt);
      card.appendChild(diff);
    }

    // pre-flight alerts
    if (r.alerts && r.alerts.length) {
      var alerts = document.createElement('div');
      alerts.className = 'prop-alerts';
      var at = document.createElement('div');
      at.className = 'prop-alerts-title';
      at.textContent = 'Pre-flight checks — ' + r.alerts.length +
        ' alert' + (r.alerts.length === 1 ? '' : 's');
      alerts.appendChild(at);
      var ul = document.createElement('ul');
      r.alerts.forEach(function (a) {
        var li = document.createElement('li');
        li.textContent = a;
        ul.appendChild(li);
      });
      alerts.appendChild(ul);
      card.appendChild(alerts);
    }

    // orders table (capped height; full view is in the modal)
    if (p.orders && p.orders.length) {
      var wrap = document.createElement('div');
      wrap.className = 'orders-wrap';
      wrap.appendChild(buildOrdersTable(p.orders));
      card.appendChild(wrap);
    }

    // warnings expander
    if (p.warnings && p.warnings.length) {
      var toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'warn-toggle';
      var caret = document.createElement('span');
      caret.className = 'warn-caret';
      var tlabel = document.createElement('span');
      tlabel.textContent = p.warnings.length + ' engine warning' +
        (p.warnings.length === 1 ? '' : 's');
      toggle.appendChild(caret);
      toggle.appendChild(tlabel);

      var warnList = document.createElement('ul');
      warnList.className = 'warn-list hidden';
      p.warnings.forEach(function (w) {
        warnList.appendChild(buildWarningItem(w));
      });

      toggle.addEventListener('click', function () {
        var open = warnList.classList.toggle('hidden');
        toggle.classList.toggle('open', !open);
      });

      card.appendChild(toggle);
      card.appendChild(warnList);
    }

    // actions
    if (r.needs_confirmation) {
      var actions = buildConfirmActions();
      card.appendChild(actions);
      activeConfirm = actions;
    }

    return card;
  }

  // ------------------------------------------------------------------------
  // Full-screen plan modal
  // ------------------------------------------------------------------------
  function sectionLabel(text) {
    var el = document.createElement('div');
    el.className = 'plan-section-label';
    el.textContent = text;
    return el;
  }

  function renderPlanModalBody(r) {
    var p = r.preview;
    var body = $('plan-modal-body');
    body.innerHTML = '';

    // title
    var title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = p.description || 'Trade proposal';
    body.appendChild(title);

    // stats
    var stats = document.createElement('div');
    stats.className = 'prop-stats';
    stats.appendChild(propStat('Accounts', String(p.n_accounts)));
    stats.appendChild(propStat('Sells', p.sell_count + ' · ' + fmtPrice(p.sell_total), 'sell'));
    stats.appendChild(propStat('Buys', p.buy_count + ' · ' + fmtPrice(p.buy_total), 'buy'));
    stats.appendChild(propStat('Net cash impact', fmtPrice(p.sell_total - p.buy_total)));
    body.appendChild(stats);

    // diff
    if (r.diff) {
      var diff = document.createElement('div');
      diff.className = 'prop-diff';
      var dl = document.createElement('span');
      dl.className = 'prop-diff-label';
      dl.textContent = 'Changed';
      var dt = document.createElement('span');
      dt.textContent = r.diff;
      diff.appendChild(dl);
      diff.appendChild(dt);
      body.appendChild(diff);
    }

    // alerts
    if (r.alerts && r.alerts.length) {
      var alerts = document.createElement('div');
      alerts.className = 'prop-alerts';
      var at = document.createElement('div');
      at.className = 'prop-alerts-title';
      at.textContent = 'Pre-flight checks — ' + r.alerts.length +
        ' alert' + (r.alerts.length === 1 ? '' : 's');
      alerts.appendChild(at);
      var ul = document.createElement('ul');
      r.alerts.forEach(function (a) {
        var li = document.createElement('li');
        li.textContent = a;
        ul.appendChild(li);
      });
      alerts.appendChild(ul);
      body.appendChild(alerts);
    }

    // full orders table (uncapped)
    if (p.orders && p.orders.length) {
      body.appendChild(sectionLabel('All orders — ' + p.orders.length));
      var wrap = document.createElement('div');
      wrap.className = 'orders-wrap';
      wrap.appendChild(buildOrdersTable(p.orders));
      body.appendChild(wrap);
    }

    // warnings (always expanded in the full view)
    if (p.warnings && p.warnings.length) {
      body.appendChild(sectionLabel(p.warnings.length + ' engine warning' +
        (p.warnings.length === 1 ? '' : 's')));
      var warnList = document.createElement('ul');
      warnList.className = 'warn-list';
      p.warnings.forEach(function (w) {
        warnList.appendChild(buildWarningItem(w));
      });
      body.appendChild(warnList);
    }
  }

  function updateStagedBar() {
    var bar = $('staged-bar');
    if (!planStaged) {
      bar.classList.add('hidden');
      return;
    }
    var sum = $('staged-summary');
    if (currentProposal && currentProposal.preview) {
      var p = currentProposal.preview;
      sum.textContent =
        p.sell_count + ' sell' + (p.sell_count === 1 ? '' : 's') + ' · ' +
        p.buy_count + ' buy' + (p.buy_count === 1 ? '' : 's') + ' · ' +
        p.n_accounts + ' account' + (p.n_accounts === 1 ? '' : 's') + ' · net ' +
        fmtPrice(p.sell_total - p.buy_total);
      $('staged-view').disabled = false;
    } else {
      sum.textContent = 'Awaiting your confirmation';
      $('staged-view').disabled = true;
    }
    $('staged-confirm').disabled = inFlight;
    $('staged-discard').disabled = inFlight;
    bar.classList.remove('hidden');
  }

  function openPlanModal() {
    if (!currentProposal || !currentProposal.preview) return;
    renderPlanModalBody(currentProposal);
    // confirm/discard only make sense while the plan is actually staged
    var staged = !!currentProposal.needs_confirmation;
    $('plan-confirm').disabled = !staged || inFlight;
    $('plan-changes').disabled = !staged;
    $('plan-dismiss').disabled = !staged || inFlight;
    planReturnFocus = document.activeElement;
    $('plan-modal').classList.remove('hidden');
    $('plan-close').focus();
  }

  function closePlanModal() {
    $('plan-modal').classList.add('hidden');
    if (planReturnFocus && document.contains(planReturnFocus) &&
        typeof planReturnFocus.focus === 'function') {
      planReturnFocus.focus();
    }
    planReturnFocus = null;
  }

  function planModalOpen() {
    return !$('plan-modal').classList.contains('hidden');
  }

  // Confirm the staged plan — deterministic, never routed through the LLM.
  async function confirmPlan() {
    if (inFlight) return;
    disableActiveConfirm();
    closePlanModal();
    currentProposal = null;
    setBusy(true);
    showTyping();
    var r;
    try {
      r = await api().confirm_pending();
    } catch (e) {
      r = { error: 'Request failed: ' + e };
    }
    hideTyping();
    setBusy(false);
    handleReply(r);
    $('composer-input').focus();
  }

  // Discard the staged plan entirely.
  async function dismissPlan() {
    if (inFlight) return;
    disableActiveConfirm();
    closePlanModal();
    currentProposal = null;
    setBusy(true);
    var r;
    try {
      r = await api().cancel_pending();
    } catch (e) {
      r = { error: 'Request failed: ' + e };
    }
    setBusy(false);
    handleReply(r);
    $('composer-input').focus();
  }

  // "Request changes": keep the plan staged, close the modal, and prompt the
  // user to type what to change. The next message revises it into a new plan.
  function requestChanges() {
    closePlanModal();
    if (state && state.api_key_set) {
      addAssistantMarkdown('Sure — tell me what to change (e.g. **make it 3%**, ' +
        '**leave out NVDA**, **only the Smith accounts**) and I’ll redraft the ' +
        'plan for you to review.');
      $('composer-input').focus();
    } else {
      addAssistantMarkdown('Revisions need an API key (add one in Settings). ' +
        'The plan is still staged — use Confirm to export it or Discard to cancel.');
    }
  }

  // ------------------------------------------------------------------------
  // Export card
  // ------------------------------------------------------------------------
  function buildExportCard(exported) {
    var card = document.createElement('div');
    card.className = 'card export-card';

    var header = document.createElement('div');
    header.className = 'card-header';
    var kicker = document.createElement('span');
    kicker.className = 'card-kicker';
    kicker.textContent = 'Orders exported';
    var title = document.createElement('span');
    title.className = 'card-title';
    title.textContent = 'CSV order sheets written to disk';
    header.appendChild(kicker);
    header.appendChild(title);
    card.appendChild(header);

    var body = document.createElement('div');
    body.className = 'export-body';

    var counts = document.createElement('span');
    counts.className = 'export-counts';
    counts.innerHTML =
      '<span class="sell">' + esc(String(exported.n_sells)) + ' sell order' +
      (exported.n_sells === 1 ? '' : 's') + '</span> · ' +
      '<span class="buy">' + esc(String(exported.n_buys)) + ' buy order' +
      (exported.n_buys === 1 ? '' : 's') + '</span>';

    var openBtn = document.createElement('button');
    openBtn.type = 'button';
    openBtn.className = 'btn btn-sm';
    openBtn.textContent = 'Open folder';
    openBtn.addEventListener('click', async function () {
      var r;
      try { r = await api().open_folder(exported.folder); }
      catch (e) { r = { ok: false, error: String(e) }; }
      if (!r || !r.ok) toast((r && r.error) || 'Could not open folder.', 'error');
    });

    var path = document.createElement('span');
    path.className = 'export-path';
    path.textContent = exported.folder;

    body.appendChild(counts);
    body.appendChild(openBtn);
    body.appendChild(path);
    card.appendChild(body);
    return card;
  }

  // ------------------------------------------------------------------------
  // Help card
  // ------------------------------------------------------------------------
  function buildHelpCard() {
    var card = document.createElement('div');
    card.className = 'card help-card';

    var header = document.createElement('div');
    header.className = 'card-header';
    var kicker = document.createElement('span');
    kicker.className = 'card-kicker';
    kicker.textContent = 'How to use';
    var title = document.createElement('span');
    title.className = 'card-title';
    title.textContent = 'Plain-English trading';
    header.appendChild(kicker);
    header.appendChild(title);
    card.appendChild(header);

    var body = document.createElement('div');
    body.className = 'help-body';

    var exTitle = document.createElement('div');
    exTitle.className = 'help-section-title';
    exTitle.textContent = 'Try one of these';
    body.appendChild(exTitle);

    var examples = [
      'Buy everything on the buy list at 2.5%, skip if I already own 2%',
      'Sell all LUMN and put the proceeds into GOOGL',
      'Raise $50,000 in cash from the largest positions',
      'How does the cash floor work?'
    ];
    var ul = document.createElement('ul');
    ul.className = 'help-examples';
    examples.forEach(function (ex) {
      var li = document.createElement('li');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'help-example-btn';
      btn.textContent = ex;
      btn.addEventListener('click', function () {
        // load into the composer for editing rather than sending immediately —
        // agent calls take 5-30s, so let the advisor adjust the text first
        var ta = $('composer-input');
        ta.value = ex;
        autosizeComposer();
        ta.focus();
        ta.setSelectionRange(ta.value.length, ta.value.length);
      });
      li.appendChild(btn);
      ul.appendChild(li);
    });
    body.appendChild(ul);

    var note = document.createElement('div');
    note.className = 'help-note';
    note.innerHTML =
      '<strong>Trades are never executed automatically.</strong> While a plan is staged it ' +
      'stays pinned in the bar at the bottom — click <strong>View full plan</strong> to see ' +
      'every order, then <strong>Confirm &amp; export</strong> or <strong>Discard</strong>. ' +
      'Instead of confirming, you can type a revision like <code>make it 3%</code> or ' +
      '<code>leave NVDA out</code> and the plan updates in place.';
    body.appendChild(note);

    card.appendChild(body);
    return card;
  }

  // ------------------------------------------------------------------------
  // Holdings slide-over
  // ------------------------------------------------------------------------
  var KIND_LABEL = { stock: 'Stock', cash_equiv: 'Cash eq', cash: 'Cash' };

  async function openHoldings(accountNumber) {
    var token = ++holdingsReq;
    var panel = $('holdings-panel');
    var overlay = $('holdings-overlay');
    if (!panel.classList.contains('open')) {
      // remember what opened the panel so close can hand focus back
      holdingsReturnFocus = document.activeElement;
    }
    overlay.classList.remove('hidden');
    panel.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    $('holdings-close').focus();

    $('holdings-title').textContent = 'Loading…';
    $('holdings-number').textContent = accountNumber;
    $('holdings-total').textContent = '';
    var tbody = $('holdings-body');
    tbody.innerHTML = '<tr><td colspan="6" class="panel-loading">Fetching positions…</td></tr>';

    var r;
    try { r = await api().get_holdings(accountNumber); }
    catch (e) { r = { ok: false, error: String(e) }; }

    // a newer request started while this one was in flight — drop this
    // response so account A's holdings never render over account B's
    if (token !== holdingsReq) return;

    if (!r || !r.ok) {
      // keep the panel open and surface the error inline; the close button
      // and overlay still dismiss it as usual
      $('holdings-title').textContent = 'Holdings unavailable';
      $('holdings-total').textContent = '';
      tbody.innerHTML =
        '<tr><td colspan="6" class="panel-error-cell">' +
        '<div class="panel-error">' +
        '<div class="panel-error-title">Could not load holdings</div>' +
        '<div class="panel-error-msg">' +
        esc((r && r.error) || 'Unknown error fetching this account.') +
        '</div></div></td></tr>';
      return;
    }

    $('holdings-title').textContent = r.client_name || '(unnamed account)';
    $('holdings-number').textContent = r.number;
    $('holdings-total').textContent = fmtMoney(r.total) + ' total';

    tbody.textContent = '';
    r.holdings.forEach(function (h) {
      var tr = document.createElement('tr');
      tr.className = 'row-' + h.kind;
      var isCash = h.kind === 'cash';
      var allocPct = Math.max(0, Math.min(100, Number(h.alloc) || 0));
      tr.innerHTML =
        '<td class="symbol">' + esc(h.symbol) + '</td>' +
        '<td><span class="kind-badge ' + esc(h.kind) + '">' +
          esc(KIND_LABEL[h.kind] || h.kind) + '</span></td>' +
        '<td class="r">' + esc(isCash ? '—' : fmtShares(h.shares)) + '</td>' +
        '<td class="r">' + esc(isCash || h.price == null ? '—' : fmtPrice(h.price)) + '</td>' +
        '<td class="r">' + esc(fmtMoney(h.value)) + '</td>' +
        '<td class="r alloc-cell">' + esc(fmtPct(h.alloc)) +
          '<div class="alloc-track"><div class="alloc-fill" style="width:' +
          allocPct.toFixed(1) + '%"></div></div>' +
        '</td>';
      tbody.appendChild(tr);
    });
  }

  function closeHoldings() {
    $('holdings-panel').classList.remove('open');
    $('holdings-panel').setAttribute('aria-hidden', 'true');
    $('holdings-overlay').classList.add('hidden');
    if (holdingsReturnFocus && document.contains(holdingsReturnFocus) &&
        typeof holdingsReturnFocus.focus === 'function') {
      holdingsReturnFocus.focus();
    }
    holdingsReturnFocus = null;
  }

  // ------------------------------------------------------------------------
  // Buy list operations
  // ------------------------------------------------------------------------
  function applyBuyListResult(r) {
    state.buy_list = r.buy_list;
    if (r.prices_as_of !== undefined) state.prices_as_of = r.prices_as_of;
    renderBuyList();
    renderTopbar();
  }

  async function removeBuyTicker(ticker) {
    if (editingBuyList || inFlight) return;
    editingBuyList = true;
    setBuyListControlsDisabled(true);
    try {
      var r;
      try { r = await api().edit_buy_list('remove', ticker, null); }
      catch (e) { r = { ok: false, error: String(e) }; }
      if (r && r.ok) {
        applyBuyListResult(r);
        toast(r.message || 'Removed ' + ticker + '.', 'success');
      } else {
        toast((r && r.error) || 'Could not remove ' + ticker + '.', 'error');
      }
    } finally {
      editingBuyList = false;
      setBuyListControlsDisabled(inFlight);
    }
  }

  async function addBuyTicker(ticker) {
    if (editingBuyList || inFlight) return;
    ticker = (ticker || '').trim().toUpperCase();
    if (!ticker) { toast('Enter a ticker symbol.', 'error'); return; }

    editingBuyList = true;
    setBuyListControlsDisabled(true);
    var addBtn = $('add-btn');
    var prevLabel = addBtn.textContent;
    addBtn.textContent = 'Fetching…';
    try {
      var r;
      try { r = await api().add_ticker_live(ticker); }
      catch (e) { r = { ok: false, error: String(e) }; }
      if (r && r.ok) {
        applyBuyListResult(r);
        $('add-ticker').value = '';
        toast(r.message || 'Added ' + ticker + '.', 'success');
        $('add-ticker').focus();
      } else {
        toast((r && r.error) || 'Could not add ' + ticker + '.', 'error');
      }
    } finally {
      addBtn.textContent = prevLabel;
      editingBuyList = false;
      setBuyListControlsDisabled(inFlight);
    }
  }

  // Clear-all uses a two-click confirm (window.confirm is unreliable in webviews).
  var clearArmed = null;
  async function clearBuyList() {
    if (editingBuyList || inFlight) return;
    var btn = $('clear-btn');
    if (!clearArmed) {
      btn.textContent = 'Confirm?';
      btn.classList.add('danger');
      clearArmed = setTimeout(function () {
        btn.textContent = 'Clear all';
        btn.classList.remove('danger');
        clearArmed = null;
      }, 3000);
      return;
    }
    clearTimeout(clearArmed);
    clearArmed = null;
    btn.textContent = 'Clear all';
    btn.classList.remove('danger');

    editingBuyList = true;
    setBuyListControlsDisabled(true);
    try {
      var r;
      try { r = await api().clear_buy_list(); }
      catch (e) { r = { ok: false, error: String(e) }; }
      if (r && r.ok) {
        applyBuyListResult(r);
        toast(r.message || 'Buy list cleared.', 'success');
      } else {
        toast((r && r.error) || 'Could not clear the buy list.', 'error');
      }
    } finally {
      editingBuyList = false;
      setBuyListControlsDisabled(inFlight);
    }
  }

  var refreshing = false;

  async function doRefreshPrices() {
    if (refreshing) return;
    refreshing = true;
    var btn = $('refresh-btn');
    btn.classList.add('busy');
    btn.disabled = true;
    $('chip-refresh').disabled = true;

    var r;
    try { r = await api().refresh_prices(); }
    catch (e) { r = { ok: false, error: String(e) }; }

    refreshing = false;
    btn.classList.remove('busy');
    // if a chat went in flight while we were refreshing, stay disabled —
    // setBusy(false) will release these when the chat completes
    btn.disabled = inFlight;
    $('chip-refresh').disabled = inFlight;

    if (!r || !r.ok) {
      toast((r && r.error) || 'Price refresh failed.', 'error');
      return;
    }

    applyBuyListResult(r);

    var parts = [];
    var updated = r.updated || [];
    var n = updated.length;
    var changed = updated.filter(function (u) { return u.new !== u.old; }).length;
    parts.push('Updated ' + n + ' price' + (n === 1 ? '' : 's') +
      ' (' + changed + ' changed).');
    updated.slice(0, 6).forEach(function (u) {
      parts.push(u.ticker + ': ' + fmtPrice(u.old) + ' → ' + fmtPrice(u.new));
    });
    if (n > 6) parts.push('…and ' + (n - 6) + ' more.');
    if (r.failed && r.failed.length) {
      parts.push('Failed: ' + r.failed.join(', '));
    }
    toast(parts.join('\n'), (r.failed && r.failed.length) ? 'info' : 'success', 6500);
  }

  // ------------------------------------------------------------------------
  // API key saving (banner + settings modal)
  // ------------------------------------------------------------------------
  async function saveKey(key) {
    var r;
    try { r = await api().save_api_key(key); }
    catch (e) { r = { ok: false, error: String(e) }; }
    return r || { ok: false, error: 'No response.' };
  }

  async function saveKeyFromBanner() {
    var input = $('key-banner-input');
    var btn = $('key-banner-save');
    btn.disabled = true;
    var r = await saveKey(input.value);
    btn.disabled = false;
    if (r.ok) {
      state.api_key_set = true;
      input.value = '';
      renderKeyBanner();
      renderSettings();
      toast('API key saved. Natural-language requests are now available.', 'success');
    } else {
      toast(r.error || 'Could not save the API key.', 'error');
    }
  }

  async function saveKeyFromSettings() {
    var input = $('settings-key');
    var btn = $('settings-key-save');
    var msg = $('settings-key-msg');
    btn.disabled = true;
    msg.textContent = '';
    msg.className = 'settings-msg';
    var r = await saveKey(input.value);
    btn.disabled = false;
    if (r.ok) {
      state.api_key_set = true;
      input.value = '';
      renderKeyBanner();
      renderSettings();
      msg.textContent = 'API key saved.';
      msg.className = 'settings-msg ok';
    } else {
      msg.textContent = r.error || 'Could not save the API key.';
      msg.className = 'settings-msg err';
    }
  }

  // ------------------------------------------------------------------------
  // Holdings file picker (error screen + settings modal)
  // ------------------------------------------------------------------------
  function fileBaseName(p) {
    p = String(p == null ? '' : p);
    var i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'));
    return i === -1 ? p : p.slice(i + 1);
  }

  // Opens the native OS file dialog and, if a file is chosen, reloads all
  // data from it. The promise stays pending while the dialog is open.
  // Returns {ok:true, ...bootstrap state} | {ok:false, cancelled:true} |
  // {ok:false, error}.
  async function pickDataFile() {
    var r;
    try { r = await api().pick_data_file(); }
    catch (e) { r = { ok: false, error: 'Request failed: ' + e }; }
    return r || { ok: false, error: 'Empty response from the backend.' };
  }

  async function locateFromErrorScreen() {
    if (pickingFile) return;
    pickingFile = true;
    var locate = $('error-locate');
    var prevLabel = locate.textContent;
    locate.textContent = 'Choosing…';
    locate.disabled = true;
    $('error-retry').disabled = true;
    $('error-quit').disabled = true;
    try {
      var r = await pickDataFile();
      if (r.ok) {
        // exactly the successful-bootstrap path: hides the error screen and
        // renders sidebar, topbar, key banner, welcome + confirmation hint
        finishBootstrap(r);
      } else if (!r.cancelled) {
        // chosen file failed to load — needsFile is still set, so the
        // locate button stays visible alongside the new message
        showBootError(r.error || 'Could not load the selected file.');
      }
      // cancelled: stay on the error screen silently
    } finally {
      pickingFile = false;
      locate.textContent = prevLabel;
      locate.disabled = false;
      $('error-retry').disabled = false;
      $('error-quit').disabled = false;
      // disabling dropped focus to <body>; hand it back for keyboard users
      // (on success the error screen is gone and the composer has focus)
      if (!$('error-screen').classList.contains('hidden')) locate.focus();
    }
  }

  async function changeDataFileFromSettings() {
    if (pickingFile) return;
    pickingFile = true;
    var btn = $('settings-data-change');
    var prevLabel = btn.textContent;
    btn.textContent = 'Choosing…';
    btn.disabled = true;
    try {
      var r = await pickDataFile();
      if (r.ok) {
        state = r;
        renderState(); // topbar, sidebar, key banner, settings paths
        // the reload rebuilt the agent, so any pending proposal is gone —
        // retire stale Confirm/Cancel buttons, the plan modal, and the bar
        disableActiveConfirm();
        currentProposal = null;
        planStaged = false;
        updateStagedBar();
        closePlanModal();
        var n = state.accounts.length;
        toast('Loaded ' + n + ' account' + (n === 1 ? '' : 's') + ' from ' +
          fileBaseName(state.investment_data_path) + '.', 'success');
      } else if (!r.cancelled) {
        toast(r.error || 'Could not load the selected file.', 'error');
      }
      // cancelled: nothing to do, no toast
    } finally {
      pickingFile = false;
      btn.textContent = prevLabel;
      btn.disabled = false;
      // disabling dropped focus to <body>; hand it back for keyboard users
      if (!$('settings-modal').classList.contains('hidden')) btn.focus();
    }
  }

  async function openExportsFolder() {
    var r;
    try { r = await api().open_folder(state.exports_dir); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      // the folder is created on first export, so it may not exist yet
      toast((r && r.error) || 'Could not open the exports folder.', 'error');
    }
  }

  // ------------------------------------------------------------------------
  // Composer
  // ------------------------------------------------------------------------
  function autosizeComposer() {
    var ta = $('composer-input');
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 132) + 'px';
  }

  function submitComposer() {
    var ta = $('composer-input');
    var text = ta.value.trim();
    if (!text || inFlight) return;
    ta.value = '';
    autosizeComposer();
    sendMessage(text);
  }

  // ------------------------------------------------------------------------
  // Event wiring
  // ------------------------------------------------------------------------
  function wireEvents() {
    // error screen
    $('error-retry').addEventListener('click', function () { init(); });
    $('error-locate').addEventListener('click', locateFromErrorScreen);
    $('error-quit').addEventListener('click', function () {
      try { api().quit(); } catch (e) { /* window already closing */ }
    });

    // composer
    var ta = $('composer-input');
    ta.addEventListener('input', autosizeComposer);
    ta.addEventListener('keydown', function (e) {
      // ignore Enter that confirms an IME composition (e.g. Japanese input)
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        submitComposer();
      }
    });
    $('send-btn').addEventListener('click', submitComposer);

    // chips
    $('chip-default').addEventListener('click', function () { sendMessage('default'); });
    $('chip-refresh').addEventListener('click', doRefreshPrices);
    $('chip-help').addEventListener('click', function () { sendMessage('help'); });

    // sidebar
    $('account-filter').addEventListener('input', renderAccounts);
    $('refresh-btn').addEventListener('click', doRefreshPrices);
    $('buylist-add-form').addEventListener('submit', function (e) {
      e.preventDefault();
      addBuyTicker($('add-ticker').value);
    });
    $('clear-btn').addEventListener('click', clearBuyList);

    // holdings panel
    $('holdings-close').addEventListener('click', closeHoldings);
    $('holdings-overlay').addEventListener('click', closeHoldings);

    // key banner
    $('key-banner-save').addEventListener('click', saveKeyFromBanner);
    $('key-banner-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); saveKeyFromBanner(); }
    });
    $('key-banner-dismiss').addEventListener('click', function () {
      bannerDismissed = true;
      renderKeyBanner();
    });

    // settings modal
    $('settings-btn').addEventListener('click', openSettings);
    $('settings-close').addEventListener('click', closeSettings);
    $('settings-modal').addEventListener('click', function (e) {
      if (e.target === $('settings-modal')) closeSettings();
    });
    $('settings-key-save').addEventListener('click', saveKeyFromSettings);
    $('settings-key').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); saveKeyFromSettings(); }
    });
    $('settings-data-change').addEventListener('click', changeDataFileFromSettings);
    $('settings-exports-open').addEventListener('click', openExportsFolder);

    // persistent staged-plan bar
    $('staged-view').addEventListener('click', openPlanModal);
    $('staged-confirm').addEventListener('click', confirmPlan);
    $('staged-discard').addEventListener('click', dismissPlan);

    // plan detail modal
    $('plan-close').addEventListener('click', closePlanModal);
    $('plan-modal').addEventListener('click', function (e) {
      if (e.target === $('plan-modal')) closePlanModal();
    });
    $('plan-confirm').addEventListener('click', confirmPlan);
    $('plan-changes').addEventListener('click', requestChanges);
    $('plan-dismiss').addEventListener('click', dismissPlan);

    // Escape closes the top-most open overlay
    // (plan modal z115 > settings z110 > holdings z100)
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (planModalOpen()) {
          closePlanModal();
        } else if (!$('settings-modal').classList.contains('hidden')) {
          closeSettings();
        } else if ($('holdings-panel').classList.contains('open')) {
          closeHoldings();
        }
      }
    });
  }

  // ------------------------------------------------------------------------
  // Settings modal open/close (with focus management)
  // ------------------------------------------------------------------------
  function openSettings() {
    settingsReturnFocus = document.activeElement;
    $('settings-key-msg').textContent = '';
    $('settings-key-msg').className = 'settings-msg';
    $('settings-modal').classList.remove('hidden');
    $('settings-key').focus();
  }

  function closeSettings() {
    $('settings-modal').classList.add('hidden');
    if (settingsReturnFocus && document.contains(settingsReturnFocus) &&
        typeof settingsReturnFocus.focus === 'function') {
      settingsReturnFocus.focus();
    }
    settingsReturnFocus = null;
  }

  // ------------------------------------------------------------------------
  // Go
  // ------------------------------------------------------------------------
  wireEvents();
  startup();

})();
