/* ================================================================
   SPARTA Branded Alert / Toast System
   Replaces native alert(), confirm(), and toast calls
   Usage:
     spartaAlert('Message', 'success' | 'error' | 'warning' | 'info')
     spartaConfirm('Message').then(confirmed => ...)
     spartaToast('Message', 'success')
   ================================================================ */

(function() {
  // Inject CSS once
  if (!document.getElementById('sparta-alert-styles')) {
    const s = document.createElement('style');
    s.id = 'sparta-alert-styles';
    s.textContent = `
      .sparta-alert-overlay {
        position: fixed; inset: 0; z-index: 99999;
        background: rgba(0,0,0,0.45); backdrop-filter: blur(2px);
        display: flex; align-items: center; justify-content: center;
        animation: sAlphaIn 0.15s ease;
      }
      .sparta-alert-box {
        background: #fff; border-radius: 16px; padding: 28px 28px 20px;
        min-width: 300px; max-width: 420px; width: 90%;
        box-shadow: 0 20px 60px rgba(0,0,0,0.18);
        animation: sSlideUp 0.2s ease;
        display: flex; flex-direction: column; gap: 12px;
      }
      .sparta-alert-icon {
        width: 48px; height: 48px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 1.4rem; flex-shrink: 0; margin: 0 auto 4px;
      }
      .sparta-alert-icon.success { background: #D1FAE5; color: #065F46; }
      .sparta-alert-icon.error   { background: #FEE2E2; color: #B71C1C; }
      .sparta-alert-icon.warning { background: #FEF3C7; color: #92400E; }
      .sparta-alert-icon.info    { background: #DBEAFE; color: #1E40AF; }
      .sparta-alert-title {
        font-size: 1rem; font-weight: 700; color: #111827;
        text-align: center; margin: 0;
      }
      .sparta-alert-msg {
        font-size: 0.9rem; color: #4B5563; text-align: center;
        line-height: 1.5; margin: 0;
      }
      .sparta-alert-actions {
        display: flex; gap: 10px; justify-content: center; margin-top: 6px;
      }
      .sparta-alert-btn {
        padding: 9px 22px; border-radius: 8px; font-size: 0.88rem;
        font-weight: 600; border: none; cursor: pointer; transition: all 0.15s;
        font-family: inherit;
      }
      .sparta-alert-btn.primary { background: #B71C1C; color: #fff; }
      .sparta-alert-btn.primary:hover { background: #9B1515; }
      .sparta-alert-btn.secondary { background: #F3F4F6; color: #374151; border: 1px solid #E5E7EB; }
      .sparta-alert-btn.secondary:hover { background: #E5E7EB; }
      /* Toast */
      #sparta-toast-container {
        position: fixed; bottom: 24px; right: 24px; z-index: 99998;
        display: flex; flex-direction: column; gap: 10px; pointer-events: none;
      }
      .sparta-toast {
        background: #1F2937; color: #fff; padding: 12px 18px;
        border-radius: 10px; font-size: 0.875rem; font-weight: 500;
        display: flex; align-items: center; gap: 10px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.2);
        animation: sSlideUp 0.2s ease; pointer-events: all;
        max-width: 320px;
      }
      .sparta-toast.success { border-left: 4px solid #10B981; }
      .sparta-toast.error   { border-left: 4px solid #B71C1C; }
      .sparta-toast.warning { border-left: 4px solid #F59E0B; }
      .sparta-toast.info    { border-left: 4px solid #3B82F6; }
      .sparta-toast span.ms { font-size: 1.1rem; }
      @keyframes sAlphaIn  { from { opacity:0 } to { opacity:1 } }
      @keyframes sSlideUp  { from { opacity:0; transform:translateY(12px) } to { opacity:1; transform:none } }
    `;
    document.head.appendChild(s);
  }

  const ICONS = {
    success: 'check_circle',
    error:   'error',
    warning: 'warning',
    info:    'info'
  };

  // ── Alert (replaces window.alert) ─────────────────────────────
  window.spartaAlert = function(message, type = 'info', title = '') {
    return new Promise(resolve => {
      const overlay = document.createElement('div');
      overlay.className = 'sparta-alert-overlay';
      overlay.innerHTML = `
        <div class="sparta-alert-box" role="alertdialog">
          <div class="sparta-alert-icon ${type}">
            <span class="ms">${ICONS[type] || 'info'}</span>
          </div>
          ${title ? `<h3 class="sparta-alert-title">${title}</h3>` : ''}
          <p class="sparta-alert-msg">${message}</p>
          <div class="sparta-alert-actions">
            <button class="sparta-alert-btn primary" id="sAlertOk">OK</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      overlay.querySelector('#sAlertOk').focus();
      overlay.querySelector('#sAlertOk').onclick = () => { overlay.remove(); resolve(); };
      overlay.addEventListener('keydown', e => { if (e.key === 'Escape' || e.key === 'Enter') { overlay.remove(); resolve(); } });
    });
  };

  // ── Confirm (replaces window.confirm) ─────────────────────────
  window.spartaConfirm = function(message, type = 'warning', title = '') {
    return new Promise(resolve => {
      const overlay = document.createElement('div');
      overlay.className = 'sparta-alert-overlay';
      overlay.innerHTML = `
        <div class="sparta-alert-box" role="alertdialog">
          <div class="sparta-alert-icon ${type}">
            <span class="ms">${ICONS[type] || 'help'}</span>
          </div>
          ${title ? `<h3 class="sparta-alert-title">${title}</h3>` : ''}
          <p class="sparta-alert-msg">${message}</p>
          <div class="sparta-alert-actions">
            <button class="sparta-alert-btn secondary" id="sConfirmNo">Cancel</button>
            <button class="sparta-alert-btn primary" id="sConfirmYes">Confirm</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      overlay.querySelector('#sConfirmYes').focus();
      overlay.querySelector('#sConfirmYes').onclick = () => { overlay.remove(); resolve(true); };
      overlay.querySelector('#sConfirmNo').onclick  = () => { overlay.remove(); resolve(false); };
      overlay.addEventListener('keydown', e => { if (e.key === 'Escape') { overlay.remove(); resolve(false); } });
    });
  };

  // ── Toast (non-blocking) ───────────────────────────────────────
  window.spartaToast = function(message, type = 'info', duration = 3500) {
    let container = document.getElementById('sparta-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'sparta-toast-container';
      document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `sparta-toast ${type}`;
    toast.innerHTML = `<span class="ms">${ICONS[type] || 'info'}</span><span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.3s';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  };

  // ── Override native alert/confirm ─────────────────────────────
  // (commented out by default — enable if you want to intercept all native calls)
  // const _nativeAlert   = window.alert;
  // window.alert   = (msg) => spartaAlert(msg, 'info');
  // window.confirm = (msg) => { spartaConfirm(msg); return false; }; // sync compat

})();
