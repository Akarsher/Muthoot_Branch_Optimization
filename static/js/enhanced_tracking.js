// Enhanced features for the live tracking dashboard

class EnhancedTrackingFeatures {
    constructor(dashboard) {
        this.dashboard = dashboard;
        this.alerts = [];
        this.routes = {};
        this.init();
    }
    
    init() {
        this.addAlertSystem();
        this.addRouteTrails();
        this.addAnalytics();
    }
    
    addAlertSystem() {
        // Create alerts panel
        const alertsHTML = `
            <div id="alerts-panel" style="position: fixed; top: 80px; right: 20px; width: 300px; z-index: 2000;">
                <div style="background: white; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); display: none;" id="alerts-container">
                    <div style="padding: 12px; border-bottom: 1px solid #dee2e6; background: #f8f9fa; border-radius: 8px 8px 0 0;">
                        <h5 style="margin: 0;">🚨 Live Alerts</h5>
                    </div>
                    <div id="alerts-list" style="max-height: 300px; overflow-y: auto;"></div>
                </div>
                <button id="alerts-toggle" style="position: absolute; top: 0; right: 0; background: #dc3545; color: white; border: none; border-radius: 50%; width: 40px; height: 40px; font-size: 18px; cursor: pointer; display: none;">
                    🚨
                </button>
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', alertsHTML);
        
        document.getElementById('alerts-toggle').addEventListener('click', () => {
            const container = document.getElementById('alerts-container');
            container.style.display = container.style.display === 'block' ? 'none' : 'block';
        });
    }
    
    checkForAlerts(auditors) {
        const now = new Date();
        
        auditors.forEach(auditor => {
            // Alert: Auditor went offline
            if (auditor.status_class === 'offline' && !this.hasAlert(`offline_${auditor.id}`)) {
                this.addAlert({
                    id: `offline_${auditor.id}`,
                    type: 'warning',
                    title: 'Auditor Offline',
                    message: `${auditor.username} has been offline for over 15 minutes`,
                    timestamp: now
                });
            }
            
            // Alert: Low accuracy
            if (auditor.accuracy > 500 && !this.hasAlert(`accuracy_${auditor.id}`)) {
                this.addAlert({
                    id: `accuracy_${auditor.id}`,
                    type: 'warning',
                    title: 'Low Location Accuracy',
                    message: `${auditor.username} has low GPS accuracy (±${Math.round(auditor.accuracy)}m)`,
                    timestamp: now
                });
            }
            
            // Clear alerts when auditor comes back online
            if (auditor.status_class === 'online') {
                this.removeAlert(`offline_${auditor.id}`);
                this.removeAlert(`accuracy_${auditor.id}`);
            }
        });
        
        this.updateAlertsDisplay();
    }
    
    addAlert(alert) {
        this.alerts.push(alert);
        
        // Show alerts toggle button
        document.getElementById('alerts-toggle').style.display = 'block';
        
        // Flash the button
        const btn = document.getElementById('alerts-toggle');
        btn.style.animation = 'pulse 1s infinite';
        setTimeout(() => btn.style.animation = '', 3000);
    }
    
    hasAlert(alertId) {
        return this.alerts.some(alert => alert.id === alertId);
    }
    
    removeAlert(alertId) {
        this.alerts = this.alerts.filter(alert => alert.id !== alertId);
        this.updateAlertsDisplay();
    }
    
    updateAlertsDisplay() {
        const alertsList = document.getElementById('alerts-list');
        const alertsToggle = document.getElementById('alerts-toggle');
        
        if (this.alerts.length === 0) {
            alertsToggle.style.display = 'none';
            return;
        }
        
        alertsToggle.textContent = this.alerts.length > 9 ? '9+' : this.alerts.length.toString();
        
        alertsList.innerHTML = this.alerts.map(alert => `
            <div style="padding: 12px; border-bottom: 1px solid #e9ecef;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <strong style="color: ${alert.type === 'warning' ? '#856404' : '#721c24'};">
                        ${alert.title}
                    </strong>
                    <button onclick="enhancedFeatures.removeAlert('${alert.id}')" 
                            style="background: none; border: none; color: #666; cursor: pointer;">×</button>
                </div>
                <div style="font-size: 12px; color: #666; margin-top: 4px;">
                    ${alert.message}
                </div>
                <div style="font-size: 10px; color: #999; margin-top: 4px;">
                    ${alert.timestamp.toLocaleTimeString()}
                </div>
            </div>
        `).join('');
    }
    
    addRouteTrails() {
        // Store previous positions to show trails
        this.previousPositions = {};
    }
    
    updateRouteTrails(auditors) {
        auditors.forEach(auditor => {
            if (auditor.lat && auditor.lng) {
                const auditorId = auditor.id;
                
                if (!this.previousPositions[auditorId]) {
                    this.previousPositions[auditorId] = [];
                }
                
                const newPosition = { lat: auditor.lat, lng: auditor.lng, timestamp: auditor.last_update };
                const positions = this.previousPositions[auditorId];
                
                // Add new position if it's different from the last one
                const lastPosition = positions[positions.length - 1];
                if (!lastPosition || lastPosition.lat !== newPosition.lat || lastPosition.lng !== newPosition.lng) {
                    positions.push(newPosition);
                    
                    // Keep only last 20 positions
                    if (positions.length > 20) {
                        positions.shift();
                    }
                    
                    // Draw trail on map
                    this.drawTrail(auditorId, positions);
                }
            }
        });
    }
    
    drawTrail(auditorId, positions) {
        if (positions.length < 2) return;
        
        // Remove existing trail
        if (this.routes[auditorId]) {
            this.routes[auditorId].setMap(null);
        }
        
        // Create new trail
        const trail = new google.maps.Polyline({
            path: positions.map(pos => ({ lat: pos.lat, lng: pos.lng })),
            geodesic: true,
            strokeColor: '#007bff',
            strokeOpacity: 0.6,
            strokeWeight: 3
        });
        
        trail.setMap(this.dashboard.map);
        this.routes[auditorId] = trail;
    }
    
    addAnalytics() {
        // Add analytics panel to the sidebar
        const analyticsHTML = `
            <div style="margin-top: 20px; padding: 12px; background: white; border-radius: 6px;">
                <h5 style="margin: 0 0 8px 0;">📊 Live Statistics</h5>
                <div id="analytics-content" style="font-size: 12px; color: #666;">
                    <div>Loading analytics...</div>
                </div>
            </div>
        `;
        
        document.querySelector('.auditor-sidebar').insertAdjacentHTML('beforeend', analyticsHTML);
    }
    
    updateAnalytics(auditors) {
        const total = auditors.length;
        const online = auditors.filter(a => a.status_class === 'online').length;
        const recent = auditors.filter(a => a.status_class === 'recent').length;
        const stale = auditors.filter(a => a.status_class === 'stale').length;
        const offline = auditors.filter(a => a.status_class === 'offline').length;
        
        const avgAccuracy = auditors
            .filter(a => a.accuracy)
            .reduce((sum, a, _, arr) => sum + a.accuracy / arr.length, 0);
        
        const analyticsContent = document.getElementById('analytics-content');
        if (analyticsContent) {
            analyticsContent.innerHTML = `
                <div style="margin-bottom: 8px;">
                    <div>📊 Total Auditors: ${total}</div>
                    <div style="color: #28a745;">🟢 Online: ${online}</div>
                    <div style="color: #ffc107;">🟡 Recent: ${recent}</div>
                    <div style="color: #fd7e14;">🟠 Stale: ${stale}</div>
                    <div style="color: #dc3545;">🔴 Offline: ${offline}</div>
                </div>
                <div style="border-top: 1px solid #e9ecef; padding-top: 8px; margin-top: 8px;">
                    <div>📶 Avg Accuracy: ±${Math.round(avgAccuracy || 0)}m</div>
                    <div>🕐 Last Update: ${new Date().toLocaleTimeString()}</div>
                </div>
            `;
        }
    }
}

// CSS for pulse animation
const style = document.createElement('style');
style.textContent = `
    @keyframes pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.1); }
        100% { transform: scale(1); }
    }
`;
document.head.appendChild(style);