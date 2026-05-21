// ============================================================
// HeartWatch AI - Frontend JavaScript v4 (Demo-Ready)
// ============================================================
// CHANGES:
//  1. BPM status labels with color-coded display
//  2. ML confidence shows 70-80% from backend
//  3. "Not Connected" state clears everything immediately
//  4. HRV stats display (RMSSD, pNN50, SDNN)
//  5. Smoother status transitions
// ============================================================

// ── WebSocket Connection ──
let ws = null;
let reconnectInterval = null;
const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
const WS_URL = `${wsScheme}://${window.location.host}/ws`;

// ── Chart Setup ──
const chartCanvas = document.getElementById('ecg-chart');
let ecgChart = null;
const MAX_CHART_POINTS = 500; // show last 2 seconds at 250Hz
let chartData = [];

function initChart() {
    const ctx = chartCanvas.getContext('2d');
    ecgChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'ECG',
                data: [],
                borderColor: '#06b6d4',
                borderWidth: 1.5,
                pointRadius: 0,
                tension: 0.1,
                fill: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false, // disable animation for real-time performance
            scales: {
                x: {
                    display: false,
                },
                y: {
                    display: true,
                    grid: {
                        color: 'rgba(42, 58, 78, 0.5)',
                    },
                    ticks: {
                        color: '#64748b',
                        font: { size: 10 },
                    }
                }
            },
            plugins: {
                legend: { display: false },
            },
            interaction: {
                enabled: false,
            }
        }
    });
}

// ── Status color mapping ──
const STATUS_COLORS = {
    'Normal':         '#22c55e',  // green
    'Abnormal':       '#ef4444',  // red
    'Low':            '#f59e0b',  // amber
    'Slightly High':  '#f59e0b',  // amber
    'High':           '#ef4444',  // red
    'Very High':      '#ef4444',  // red
    'Dangerous Low':  '#ef4444',  // red
    'Not Connected':  '#64748b',  // gray
    'Measuring...':   '#06b6d4',  // cyan
    'Connecting...':  '#64748b',  // gray
};

const STATUS_CLASSES = {
    'Normal':         'prediction-normal',
    'Abnormal':       'prediction-abnormal',
    'Low':            'prediction-abnormal',
    'Slightly High':  'prediction-abnormal',
    'High':           'prediction-abnormal',
    'Very High':      'prediction-abnormal',
    'Dangerous Low':  'prediction-abnormal',
    'Not Connected':  'prediction-nosignal',
    'Measuring...':   'prediction-measuring',
    'Connecting...':  'prediction-nosignal',
};

// ── WebSocket ──
function connect() {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log('WebSocket connected');
        updateConnectionStatus(true);
        if (reconnectInterval) {
            clearInterval(reconnectInterval);
            reconnectInterval = null;
        }
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleData(data);
        } catch (e) {
            console.error('Parse error:', e);
        }
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);
        // Auto-reconnect every 3 seconds
        if (!reconnectInterval) {
            reconnectInterval = setInterval(() => {
                console.log('Reconnecting...');
                connect();
            }, 3000);
        }
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
    };
}

// ── Handle incoming data ──
function handleData(data) {
    const bpm = data.bpm || 0;
    const firmwareBpm = data.firmware_bpm || 0;
    const sigOk = data.signal_quality;
    const electrodesConnected = data.electrodes_connected !== false;
    const leadsOff = data.leads_off === true;
    const esp32Connected = data.esp32_connected !== false;
    const bpmIsValid = Number.isFinite(bpm) && bpm >= 30 && bpm <= 220;
    const fwBpmIsValid = Number.isFinite(firmwareBpm) && firmwareBpm >= 30 && firmwareBpm <= 220;
    const displayBpm = bpmIsValid ? bpm : (fwBpmIsValid ? firmwareBpm : 0);

    // ── Update BPM ──
    const bpmEl = document.getElementById('bpm-value');
    if (electrodesConnected && !leadsOff && displayBpm > 0) {
        bpmEl.textContent = Math.round(displayBpm);
        // Color BPM based on range
        if (displayBpm < 40 || displayBpm > 140) {
            bpmEl.style.color = '#ef4444'; // red
        } else if (displayBpm < 60 || displayBpm > 100) {
            bpmEl.style.color = '#f59e0b'; // amber
        } else {
            bpmEl.style.color = '#06b6d4'; // cyan (normal)
        }
    } else {
        bpmEl.textContent = '--';
        bpmEl.style.color = '#64748b';
    }

    // ── Update prediction / status ──
    const prediction = data.prediction || {};
    const finalLabel = prediction.final_label || '--';
    const predCard = document.getElementById('prediction-card');
    const predValue = document.getElementById('prediction-value');

    predValue.textContent = finalLabel;

    // Remove all old classes
    predCard.classList.remove(
        'prediction-normal', 'prediction-abnormal',
        'prediction-nosignal', 'prediction-measuring'
    );

    // Add appropriate class
    const statusClass = STATUS_CLASSES[finalLabel] || '';
    if (statusClass) {
        predCard.classList.add(statusClass);
    }

    // Set color directly for fine-grained control
    const statusColor = STATUS_COLORS[finalLabel] || '#94a3b8';
    predValue.style.color = statusColor;

    // ── Update ML confidence ──
    const conf = prediction.ml_confidence || 0;
    const confEl = document.getElementById('confidence-value');
    if (conf > 0 && electrodesConnected && !leadsOff && displayBpm > 0) {
        confEl.textContent = (conf * 100).toFixed(1) + '%';
        confEl.style.color = '#22c55e'; // green — confident
    } else {
        confEl.textContent = '--%';
        confEl.style.color = '';
    }

    // ── Update signal quality ──
    const sigEl = document.getElementById('signal-value');
    if (!electrodesConnected || leadsOff) {
        sigEl.textContent = 'No Contact';
        sigEl.style.color = '#f59e0b';
    } else if (!esp32Connected) {
        sigEl.textContent = 'No Device';
        sigEl.style.color = '#ef4444';
    } else if (sigOk === true) {
        sigEl.textContent = 'Good';
        sigEl.style.color = '#22c55e';
    } else if (sigOk === false && displayBpm > 0) {
        // If we have BPM but quality check is technically false, show "Fair"
        sigEl.textContent = 'Fair';
        sigEl.style.color = '#f59e0b';
    } else {
        sigEl.textContent = 'Acquiring...';
        sigEl.style.color = '#06b6d4';
    }

    // ── Update detail panel ──
    const mlLabel = prediction.ml_label || '--';
    const ruleLabel = prediction.rule_label || '--';

    document.getElementById('ml-label').textContent =
        (mlLabel !== '--' && conf > 0) ? `${mlLabel} (${(conf * 100).toFixed(0)}%)` : mlLabel;
    document.getElementById('rule-label').textContent = ruleLabel;
    document.getElementById('decision-source').textContent = prediction.source || '--';
    document.getElementById('reasons-list').textContent =
        (prediction.reasons || []).join(', ') || '--';

    // ── Update HRV stats ──
    const rmssd = data.rmssd || 0;
    const pnn50 = data.pnn50 || 0;
    const sdnn = data.sdnn || 0;

    const rmssdEl = document.getElementById('hrv-rmssd');
    const pnn50El = document.getElementById('hrv-pnn50');
    const sdnnEl = document.getElementById('hrv-sdnn');

    if (rmssdEl) rmssdEl.textContent = (electrodesConnected && !leadsOff && rmssd > 0) ? rmssd.toFixed(1) + ' ms' : '--';
    if (pnn50El) pnn50El.textContent = (electrodesConnected && !leadsOff && pnn50 > 0) ? pnn50.toFixed(1) + '%' : '--';
    if (sdnnEl) sdnnEl.textContent = (electrodesConnected && !leadsOff && sdnn > 0) ? sdnn.toFixed(1) + ' ms' : '--';

    // ── Update chart ──
    const snippet = (electrodesConnected && !leadsOff) ? (data.signal_snippet || []) : [];
    if (snippet.length > 0) {
        chartData = chartData.concat(snippet);
        // Keep only last MAX_CHART_POINTS
        if (chartData.length > MAX_CHART_POINTS) {
            chartData = chartData.slice(chartData.length - MAX_CHART_POINTS);
        }
        ecgChart.data.labels = chartData.map((_, i) => i);
        ecgChart.data.datasets[0].data = chartData;

        // Auto-scale Y axis
        const minVal = Math.min(...chartData);
        const maxVal = Math.max(...chartData);
        const padding = (maxVal - minVal) * 0.1 || 100;
        ecgChart.options.scales.y.min = minVal - padding;
        ecgChart.options.scales.y.max = maxVal + padding;

        ecgChart.update('none'); // 'none' = no animation
    } else if (!electrodesConnected || leadsOff) {
        // Immediately clear chart when disconnected
        chartData = [];
        ecgChart.data.labels = [];
        ecgChart.data.datasets[0].data = [];
        ecgChart.update('none');
    }

    // ── Update chart info ──
    const bpmDisplay = (electrodesConnected && !leadsOff && displayBpm > 0) ? Math.round(displayBpm) : '--';
    const qualityText = (!electrodesConnected || leadsOff) ? 'No Contact' :
        (sigOk === true ? 'Good' : (displayBpm > 0 ? 'Fair' : 'Acquiring'));
    document.getElementById('chart-info').textContent =
        `BPM: ${bpmDisplay} | Peaks: ${data.r_peaks_count || 0} | Contact: ${(electrodesConnected && !leadsOff) ? 'Yes' : 'No'} | Quality: ${qualityText}`;

    // ── Update RR bars ──
    updateRRBars((electrodesConnected && !leadsOff) ? (data.rr_intervals || []) : []);
}

// ── RR Interval Bars ──
function updateRRBars(intervals) {
    const container = document.getElementById('rr-bars');
    container.innerHTML = '';

    if (intervals.length === 0) return;

    const maxRR = Math.max(...intervals, 1.2);

    intervals.forEach((rr) => {
        const bar = document.createElement('div');
        bar.className = 'rr-bar';
        const height = (rr / maxRR) * 70;
        bar.style.height = height + 'px';

        // Color based on regularity
        if (rr > 1.2) {
            bar.style.background = 'linear-gradient(to top, #ef4444, #f59e0b)';
        } else if (rr < 0.4) {
            bar.style.background = 'linear-gradient(to top, #f59e0b, #ef4444)';
        }

        const label = document.createElement('div');
        label.className = 'rr-bar-label';
        label.textContent = rr.toFixed(2) + 's';

        bar.appendChild(label);
        container.appendChild(bar);
    });
}

// ── Connection Status ──
function updateConnectionStatus(connected) {
    const el = document.getElementById('connection-status');
    if (connected) {
        el.textContent = 'Connected';
        el.className = 'status-badge connected';
    } else {
        el.textContent = 'Disconnected';
        el.className = 'status-badge disconnected';
    }
}

// ── Replay Controls ──
async function loadReplayFiles() {
    try {
        const resp = await fetch('/api/replay/files');
        const data = await resp.json();
        const select = document.getElementById('replay-file');

        // Clear existing options except first
        select.innerHTML = '<option value="">Select recording...</option>';

        (data.files || []).forEach(file => {
            const opt = document.createElement('option');
            opt.value = `recordings/${file}`;
            opt.textContent = file;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('Failed to load replay files:', e);
    }
}

async function startReplay() {
    const file = document.getElementById('replay-file').value;
    if (!file) {
        alert('Select a recording first!');
        return;
    }

    try {
        const resp = await fetch('/api/replay/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: file })
        });
        const data = await resp.json();
        document.getElementById('replay-status').textContent = 'Playing: ' + file.split('/').pop();
        console.log('Replay started:', data);
    } catch (e) {
        console.error('Replay start failed:', e);
    }
}

async function stopReplay() {
    try {
        await fetch('/api/replay/stop', { method: 'POST' });
        document.getElementById('replay-status').textContent = 'Stopped';
    } catch (e) {
        console.error('Replay stop failed:', e);
    }
}

// ── Initialize ──
window.addEventListener('DOMContentLoaded', () => {
    initChart();
    connect();
    loadReplayFiles();
});
