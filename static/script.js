let bridgeHasInternet = false;

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
  refreshState();
});

async function refreshState() {
  try {
    const res = await fetch('/api/state');
    const data = await res.json();

    renderDevices(data.mesh.devices);
    renderLog(data.mesh.log);
    renderAccounts(data.accounts);
    renderTransactions(data.transactions);

    // Update Bridge Internet Button
    if (data.mesh.devices['phone-bridge']) {
      bridgeHasInternet = data.mesh.devices['phone-bridge'].has_internet;
      const btn4G = document.getElementById('btnToggle4G');
      if (bridgeHasInternet) {
        btn4G.innerText = '📶 4G Connected (Click to Disconnect)';
        btn4G.className = 'btn btn-success';
      } else {
        btn4G.innerText = '📶 Connect Bridge to 4G';
        btn4G.className = 'btn btn-outline';
      }
    }
  } catch (err) {
    console.error('Error fetching state:', err);
  }
}

function renderDevices(devices) {
  const container = document.getElementById('deviceList');
  container.innerHTML = '';

  const deviceIcons = {
    'phone-sender': '📱',
    'phone-stranger-1': '🚶',
    'phone-stranger-2': '🚶‍♂️',
    'phone-bridge': '🌉'
  };

  for (const key in devices) {
    const d = devices[key];
    const card = document.createElement('div');
    card.className = 'device-card';

    const count = d.held_packets.length;
    const packetPill = count > 0 
      ? `<span class="pill pill-packet">${count} Packet${count > 1 ? 's' : ''}</span>`
      : `<span class="pill pill-offline">0 Packets</span>`;

    const netPill = d.has_internet
      ? `<span class="pill pill-online">4G Online</span>`
      : `<span class="pill pill-offline">Offline</span>`;

    card.innerHTML = `
      <div class="device-left">
        <span class="device-icon">${deviceIcons[d.id] || '📱'}</span>
        <div>
          <div class="device-name">${d.name}</div>
          <div class="device-role">${d.role}</div>
        </div>
      </div>
      <div class="device-right">
        ${packetPill}
        ${netPill}
      </div>
    `;
    container.appendChild(card);
  }
}

function renderLog(logLines) {
  const container = document.getElementById('terminalLog');
  if (!logLines || logLines.length === 0) return;
  container.innerHTML = logLines.map(line => `<div class="log-line">> ${line}</div>`).join('');
}

function renderAccounts(accounts) {
  const tbody = document.getElementById('accountsTableBody');
  tbody.innerHTML = '';

  accounts.forEach(acc => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><b>${acc.vpa}</b></td>
      <td>${acc.holder_name}</td>
      <td>₹${acc.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
      <td><span class="pill pill-offline">v${acc.version}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function renderTransactions(transactions) {
  const tbody = document.getElementById('transactionsTableBody');
  tbody.innerHTML = '';

  if (!transactions || transactions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#64748b;padding:1.5rem;">No transactions settled yet. Run Step 1 to 3 above!</td></tr>';
    return;
  }

  transactions.forEach(tx => {
    const tr = document.createElement('tr');
    let badgeClass = 'badge-settled';
    if (tx.status.includes('DUPLICATE')) badgeClass = 'badge-duplicate';
    if (tx.status.includes('REJECTED') || tx.status.includes('INVALID')) badgeClass = 'badge-invalid';

    const dateStr = tx.settled_at ? new Date(tx.settled_at).toLocaleTimeString() : '-';

    tr.innerHTML = `
      <td>#${tx.id}</td>
      <td>${tx.sender_vpa}</td>
      <td>${tx.receiver_vpa}</td>
      <td><b>₹${tx.amount}</b></td>
      <td><span class="${badgeClass}">${tx.status}</span></td>
      <td>${tx.hop_count} hops</td>
      <td>${dateStr}</td>
    `;
    tbody.appendChild(tr);
  });
}

// -------------------------------------------------------------
// Action Handlers
// -------------------------------------------------------------

async function handleCreatePayment(e) {
  e.preventDefault();
  const sender = document.getElementById('senderVpa').value;
  const receiver = document.getElementById('receiverVpa').value;
  const amount = parseFloat(document.getElementById('payAmount').value);
  const pin = document.getElementById('payPin').value;

  try {
    const res = await fetch('/api/demo/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sender, receiver, amount, pin })
    });
    const result = await res.json();
    if (result.success) {
      refreshState();
    }
  } catch (err) {
    alert('Error creating payment: ' + err.message);
  }
}

async function handleGossipStep() {
  try {
    const res = await fetch('/api/demo/gossip', { method: 'POST' });
    const result = await res.json();
    refreshState();
  } catch (err) {
    alert('Error stepping gossip: ' + err.message);
  }
}

async function toggleBridgeInternet() {
  try {
    const res = await fetch('/api/demo/bridge-internet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hasInternet: !bridgeHasInternet })
    });
    refreshState();
  } catch (err) {
    alert('Error toggling internet: ' + err.message);
  }
}

async function handleFlushBridge() {
  try {
    const res = await fetch('/api/demo/flush-bridge', { method: 'POST' });
    const result = await res.json();
    if (!result.success) {
      alert(result.error);
    }
    refreshState();
  } catch (err) {
    alert('Error uploading to bridge: ' + err.message);
  }
}

async function handleTamperTest() {
  try {
    const res = await fetch('/api/demo/tamper', { method: 'POST' });
    const result = await res.json();
    refreshState();
    alert(`Tamper Test Result: Outcome is ${result.attackResult.outcome} (${result.attackResult.reason}). The altered packet was rejected before touching the ledger!`);
  } catch (err) {
    alert('Error running tamper test: ' + err.message);
  }
}

async function resetDemo() {
  try {
    await fetch('/api/demo/reset', { method: 'POST' });
    refreshState();
  } catch (err) {
    alert('Error resetting demo: ' + err.message);
  }
}
