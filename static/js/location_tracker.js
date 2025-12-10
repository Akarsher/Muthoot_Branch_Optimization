class LocationTracker {
    constructor() {
        this.watchId = null;
        this.isTracking = false;
        this.sessionId = null;
        this.updateInterval = 30000; // 30 seconds
        this.lastUpdate = null;
        this.locationHistory = [];
        
        this.init();
    }
    
    init() {
        // Check if geolocation is supported
        if (!navigator.geolocation) {
            console.error('Geolocation is not supported by this browser');
            this.showError('Location tracking not supported in this browser');
            return;
        }
        
        console.log('📍 Location tracker initialized');
        this.createTrackingUI();
    }
    
    createTrackingUI() {
        // Create tracking controls HTML
        const trackingHTML = `
            <div class="location-tracking-panel card" id="tracking-panel" style="margin: 20px 0; padding: 20px; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px;">
                <div class="tracking-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <h4 style="margin: 0; color: #333;">📍 Live Location Tracking</h4>
                    <div class="tracking-status" id="tracking-status" style="padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; background: #f8d7da; color: #721c24;">⭕ Ready to track</div>
                </div>
                
                <div class="location-test" style="margin: 10px 0;">
                    <button id="test-location-btn" class="btn" style="background: #17a2b8; color: white; padding: 6px 12px; border: none; border-radius: 4px; font-size: 12px; cursor: pointer;" onclick="locationTracker.testCurrentLocation()">
                        📍 Test Current Location
                    </button>
                    <button id="use-network-btn" class="btn" style="background: #6c757d; color: white; padding: 6px 12px; border: none; border-radius: 4px; font-size: 12px; cursor: pointer; margin-left: 5px;" onclick="locationTracker.testNetworkLocation()">
                        📶 Use Network Location
                    </button>
                    <div id="test-result" style="margin-top: 5px; font-size: 12px; color: #666;"></div>
                </div>
                
                <div class="tracking-info" id="tracking-info" style="display: none; background: white; border: 1px solid #e9ecef; border-radius: 6px; padding: 12px; margin: 12px 0;">
                    <div class="location-display" id="location-display"></div>
                    <div class="tracking-stats" id="tracking-stats"></div>
                </div>
                
                <div class="tracking-controls">
                    <button id="start-tracking-btn" class="btn btn-success" onclick="locationTracker.startTracking()" style="background: #28a745; color: white; margin-right: 8px; padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer;">
                        🚀 Start Live Tracking
                    </button>
                    <button id="stop-tracking-btn" class="btn btn-danger" onclick="locationTracker.stopTracking()" style="display: none; background: #dc3545; color: white; margin-right: 8px; padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer;">
                        ⏹️ Stop Tracking
                    </button>
                </div>
                
                <div class="tracking-help" style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #e9ecef; color: #666; font-size: 12px;">
                    <small>📱 Try "Test Current Location" first. If it times out, use "Use Network Location" for approximate location. For GPS accuracy, ensure location services are enabled and you're near a window or outdoors.</small>
                </div>
            </div>
        `;
        
        // Find the main content area in the auditor page
        let targetContainer = document.querySelector('main.content-area');
        if (!targetContainer) {
            targetContainer = document.querySelector('.content-area');
        }
        if (!targetContainer) {
            targetContainer = document.querySelector('main');
        }
        if (!targetContainer) {
            // Insert after the status box
            targetContainer = document.querySelector('.status-box');
        }
        
        if (targetContainer) {
            // Add after the status box or at the beginning of main
            if (targetContainer.className && targetContainer.className.includes('status-box')) {
                targetContainer.insertAdjacentHTML('afterend', trackingHTML);
            } else {
                targetContainer.insertAdjacentHTML('afterbegin', trackingHTML);
            }
            console.log('✅ Tracking UI created');
        } else {
            console.warn('⚠️ Could not find container for tracking UI');
        }
    }
    
    async testCurrentLocation() {
        const testBtn = document.getElementById('test-location-btn');
        const testResult = document.getElementById('test-result');
        
        testBtn.textContent = 'Getting precise location...';
        testBtn.disabled = true;
        testResult.innerHTML = '<em style="color: #17a2b8;">🎯 Getting most accurate location possible (may take 60+ seconds)...</em>';
        
        try {
            // Use ultra-accurate method
            const position = await this.getCurrentLocationUltraAccuracy();
            this.displayLocationResult(position, 'High-Precision GPS');
            
        } catch (error) {
            console.error('❌ Ultra-accurate location failed:', error);
            
            // Fallback to regular high accuracy
            try {
                const position = await this.getCurrentLocationHighAccuracy();
                this.displayLocationResult(position, 'GPS');
            } catch (fallbackError) {
                this.displayLocationError(fallbackError, 'All location methods failed.');
            }
            
        } finally {
            testBtn.textContent = '📍 Test Current Location';
            testBtn.disabled = false;
        }
    }
    
    async testNetworkLocation() {
        const testBtn = document.getElementById('use-network-btn');
        const testResult = document.getElementById('test-result');
        
        testBtn.textContent = 'Getting network location...';
        testBtn.disabled = true;
        testResult.innerHTML = '<em style="color: #17a2b8;">📶 Using network-based location (faster but less accurate)...</em>';
        
        try {
            // Use network-based location (faster, less accurate)
            const position = await this.getCurrentLocationNetwork();
            this.displayLocationResult(position, 'Network');
            
        } catch (error) {
            console.error('❌ Network location failed:', error);
            this.displayLocationError(error, 'Network location also failed.');
            
        } finally {
            testBtn.textContent = '📶 Use Network Location';
            testBtn.disabled = false;
        }
    }
    
    displayLocationResult(position, source) {
        const testResult = document.getElementById('test-result');
        const lat = position.coords.latitude;
        const lng = position.coords.longitude;
        const accuracy = position.coords.accuracy;
        const timestamp = new Date(position.timestamp);
        
        // Determine accuracy quality
        let accuracyColor = '#28a745'; // Green
        let accuracyText = 'Excellent';
        if (accuracy > 1000) {
            accuracyColor = '#dc3545'; // Red
            accuracyText = 'Very Poor';
        } else if (accuracy > 500) {
            accuracyColor = '#fd7e14'; // Orange
            accuracyText = 'Poor';
        } else if (accuracy > 100) {
            accuracyColor = '#ffc107'; // Yellow
            accuracyText = 'Fair';
        } else if (accuracy > 50) {
            accuracyColor = '#17a2b8'; // Blue
            accuracyText = 'Good';
        }
        
        testResult.innerHTML = `
            <div style="color: #28a745; font-weight: bold;">📍 Location Found! (${source})</div>
            <div style="font-family: monospace; font-size: 11px; color: #333;">
                📍 ${lat.toFixed(6)}, ${lng.toFixed(6)}
            </div>
            <div style="color: ${accuracyColor}; font-size: 11px;">
                📶 Accuracy: ±${Math.round(accuracy)}m (${accuracyText})
            </div>
            <div style="font-size: 11px; color: #666;">
                🕐 ${timestamp.toLocaleTimeString()}
            </div>
            <div style="margin-top: 5px;">
                <a href="https://www.google.com/maps?q=${lat},${lng}" target="_blank" style="color: #007bff; font-size: 11px;">🗺️ View on Google Maps</a>
            </div>
        `;
        
        console.log('📍 Test location:', {lat, lng, accuracy, source});
    }
    
    displayLocationError(error, customMessage) {
        const testResult = document.getElementById('test-result');
        
        let errorMsg = customMessage || 'Unknown error';
        let suggestions = '';
        
        switch(error.code) {
            case 1: // PERMISSION_DENIED
                errorMsg = 'Location permission denied';
                suggestions = '<br><small>💡 Please enable location access in your browser settings</small>';
                break;
            case 2: // POSITION_UNAVAILABLE
                errorMsg = 'Location unavailable';
                suggestions = '<br><small>💡 Check your internet connection and device location settings</small>';
                break;
            case 3: // TIMEOUT
                errorMsg = 'Location request timed out';
                suggestions = '<br><small>💡 Try moving near a window or outdoors for better GPS signal</small>';
                break;
            default:
                errorMsg = error.message || 'Failed to get location';
        }
        
        testResult.innerHTML = `
            <div style="color: #dc3545;">❌ ${errorMsg}</div>
            ${suggestions}
        `;
    }
    
    getCurrentLocationHighAccuracy() {
        return new Promise((resolve, reject) => {
            navigator.geolocation.getCurrentPosition(resolve, reject, {
                enableHighAccuracy: true,    // Force GPS usage
                timeout: 60000,              // Increase timeout to 60 seconds
                maximumAge: 0                // Never use cached location
            });
        });
    }

    // Add a more aggressive high-accuracy method
    getCurrentLocationUltraAccuracy() {
        return new Promise((resolve, reject) => {
            let bestPosition = null;
            let attempts = 0;
            const maxAttempts = 3;
            
            const tryGetLocation = () => {
                navigator.geolocation.getCurrentPosition(
                    (position) => {
                        attempts++;
                        console.log(`📍 Attempt ${attempts}: Accuracy ±${Math.round(position.coords.accuracy)}m`);
                        
                        // Accept if accuracy is good enough or max attempts reached
                        if (position.coords.accuracy <= 20 || attempts >= maxAttempts) {
                            resolve(bestPosition || position);
                        } else {
                            // Store best position so far
                            if (!bestPosition || position.coords.accuracy < bestPosition.coords.accuracy) {
                                bestPosition = position;
                            }
                            // Try again for better accuracy
                            setTimeout(tryGetLocation, 2000);
                        }
                    },
                    (error) => {
                        if (bestPosition) {
                            resolve(bestPosition);
                        } else {
                            reject(error);
                        }
                    },
                    {
                        enableHighAccuracy: true,
                        timeout: 30000,
                        maximumAge: 0
                    }
                );
            };
            
            tryGetLocation();
        });
    }

    getCurrentLocationNetwork() {
        return new Promise((resolve, reject) => {
            navigator.geolocation.getCurrentPosition(resolve, reject, {
                enableHighAccuracy: false,   // Use network location (faster)
                timeout: 10000,              // 10 seconds timeout
                maximumAge: 60000            // Can use 1-minute old cached location
            });
        });
    }
    
    getCurrentPosition() {
        return new Promise((resolve, reject) => {
            navigator.geolocation.getCurrentPosition(resolve, reject, {
                enableHighAccuracy: true,
                timeout: 20000,              // Increased timeout
                maximumAge: 30000
            });
        });
    }
    
    async startTracking() {
        console.log('🚀 Starting location tracking...');
        
        try {
            // Get initial ultra-accurate position
            let position;
            const testResult = document.getElementById('test-result');
            
            if (testResult) testResult.innerHTML = '<em style="color: #17a2b8;">🎯 Getting precise initial location...</em>';
            
            position = await this.getCurrentLocationUltraAccuracy();
            console.log('✅ Ultra-accurate location obtained for initial position');
            
            // Start tracking session on server
            const sessionResponse = await this.startTrackingSession();
            if (!sessionResponse.success) {
                throw new Error(sessionResponse.error || 'Failed to start tracking session');
            }
            
            this.sessionId = sessionResponse.session_id;
            this.isTracking = true;
            
            // For continuous tracking, use balanced settings
            this.watchId = navigator.geolocation.watchPosition(
                (position) => this.onLocationUpdate(position),
                (error) => this.onLocationError(error),
                {
                    enableHighAccuracy: true,    // Keep GPS enabled for continuous tracking
                    timeout: 20000,              // 20 seconds per reading
                    maximumAge: 10000            // Use cached location if less than 10 seconds old
                }
            );
            
            // Send initial ultra-accurate location
            await this.sendLocationUpdate(position);
            
            this.updateTrackingUI();
            this.showSuccess('High-precision tracking started! 🎯');
            
            if (testResult) {
                testResult.innerHTML = '<div style="color: #28a745;">✅ High-precision tracking active</div>';
            }
            
        } catch (error) {
            console.error('❌ Failed to start tracking:', error);
            this.showError('Failed to start tracking: ' + error.message);
            this.isTracking = false;
            
            const testResult = document.getElementById('test-result');
            if (testResult) {
                testResult.innerHTML = '<div style="color: #dc3545;">❌ Failed to start tracking</div>';
            }
        }
    }
    
    async onLocationUpdate(position) {
        if (!this.isTracking) return;
        
        const lat = position.coords.latitude;
        const lng = position.coords.longitude;
        const accuracy = position.coords.accuracy;
        
        console.log('📍 Location update:', lat, lng, `±${Math.round(accuracy)}m`);
        
        // Store location in history
        this.locationHistory.push({
            lat, lng, accuracy, 
            timestamp: new Date(position.timestamp)
        });
        
        // Keep only last 10 locations
        if (this.locationHistory.length > 10) {
            this.locationHistory = this.locationHistory.slice(-10);
        }
        
        try {
            await this.sendLocationUpdate(position);
            this.updateLocationDisplay(position);
            this.lastUpdate = new Date();
            
        } catch (error) {
            console.error('❌ Failed to send location update:', error);
        }
    }
    
    updateLocationDisplay(position) {
        const displayEl = document.getElementById('location-display');
        const statsEl = document.getElementById('tracking-stats');
        
        if (displayEl) {
            const lat = position.coords.latitude;
            const lng = position.coords.longitude;
            const accuracy = Math.round(position.coords.accuracy);
            
            // Determine accuracy quality
            let accuracyColor = '#28a745'; // Green
            let accuracyText = 'Excellent';
            if (accuracy > 1000) {
                accuracyColor = '#dc3545'; // Red
                accuracyText = 'Very Poor';
            } else if (accuracy > 500) {
                accuracyColor = '#fd7e14'; // Orange
                accuracyText = 'Poor';
            } else if (accuracy > 100) {
                accuracyColor = '#ffc107'; // Yellow
                accuracyText = 'Fair';
            } else if (accuracy > 50) {
                accuracyColor = '#17a2b8'; // Blue
                accuracyText = 'Good';
            }
            
            displayEl.innerHTML = `
                <div class="location-coords" style="font-family: monospace; margin-bottom: 4px;">
                    📍 <strong>${lat.toFixed(6)}, ${lng.toFixed(6)}</strong>
                    <a href="https://www.google.com/maps?q=${lat},${lng}" target="_blank" style="margin-left: 10px; font-size: 11px; color: #007bff;">🗺️ View</a>
                </div>
                <div class="location-accuracy" style="color: ${accuracyColor}; font-size: 12px;">
                    📶 Accuracy: ±${accuracy}m (${accuracyText})
                </div>
            `;
        }
        
        if (statsEl) {
            const now = new Date();
            const historyCount = this.locationHistory.length;
            
            statsEl.innerHTML = `
                <div style="font-size: 12px; color: #666;">
                    <div>🕐 Last update: ${now.toLocaleTimeString()}</div>
                    <div>🎯 Session: ${this.sessionId} | 📊 Updates: ${historyCount}</div>
                    <div>🛰️ Location Source: ${position.coords.accuracy < 100 ? 'GPS/Mixed' : 'Network'}</div>
                </div>
            `;
        }
    }
    
    // Add this method to validate location accuracy
    isLocationAccurate(position) {
        const accuracy = position.coords.accuracy;
        return accuracy <= 50; // Accept only if accurate within 50 meters
    }

    // ... Keep all your existing methods (stopTracking, onLocationError, API methods, etc.)
    
    async stopTracking() {
        console.log('⏹️ Stopping location tracking...');
        
        try {
            if (this.watchId) {
                navigator.geolocation.clearWatch(this.watchId);
                this.watchId = null;
            }
            
            if (this.sessionId) {
                await this.stopTrackingSession();
            }
            
            this.isTracking = false;
            this.sessionId = null;
            this.lastUpdate = null;
            
            this.updateTrackingUI();
            this.showSuccess('Location tracking stopped 🛑');
            
            const testResult = document.getElementById('test-result');
            if (testResult) {
                testResult.innerHTML = '<div style="color: #6c757d;">⏹️ Tracking stopped</div>';
            }
            
        } catch (error) {
            console.error('❌ Error stopping tracking:', error);
            this.showError('Error stopping tracking: ' + error.message);
        }
    }
    
    onLocationError(error) {
        console.error('📍 Location error:', error);
        
        // Don't show errors for timeouts during continuous tracking - just log them
        if (error.code === 3) { // TIMEOUT
            console.log('⚠️ Location timeout (continuing tracking)');
            return;
        }
        
        let errorMessage = 'Unknown location error';
        let suggestions = '';
        
        switch(error.code) {
            case 1: // PERMISSION_DENIED
                errorMessage = 'Location permission denied.';
                suggestions = ' Please enable location access in your browser settings.';
                this.isTracking = false;
                break;
            case 2: // POSITION_UNAVAILABLE
                errorMessage = 'Location unavailable.';
                suggestions = ' Check GPS signal and internet connection.';
                break;
        }
        
        this.showError(errorMessage + suggestions);
        
        if (error.code === 1) { // PERMISSION_DENIED
            this.updateTrackingUI();
        }
    }
    
    // ... Keep all your existing API and utility methods unchanged
    async startTrackingSession() {
        const response = await fetch('/api/location/start-tracking', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ route_data: this.getRouteData() })
        });
        return await response.json();
    }
    
    async stopTrackingSession() {
        const response = await fetch('/api/location/stop-tracking', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: this.sessionId })
        });
        return await response.json();
    }
    
    async sendLocationUpdate(position) {
        const locationData = {
            lat: position.coords.latitude,
            lng: position.coords.longitude,
            accuracy: position.coords.accuracy,
            session_id: this.sessionId
        };
        
        const response = await fetch('/api/location/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(locationData)
        });
        
        const result = await response.json();
        if (!result.success) {
            throw new Error(result.error || 'Failed to update location');
        }
        return result;
    }
    
    updateTrackingUI() {
        const startBtn = document.getElementById('start-tracking-btn');
        const stopBtn = document.getElementById('stop-tracking-btn');
        const status = document.getElementById('tracking-status');
        const info = document.getElementById('tracking-info');
        
        if (this.isTracking) {
            if (startBtn) startBtn.style.display = 'none';
            if (stopBtn) stopBtn.style.display = 'inline-block';
            if (status) {
                status.textContent = '🟢 Live tracking active';
                status.style.cssText = 'padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; background: #d4edda; color: #155724;';
            }
            if (info) info.style.display = 'block';
        } else {
            if (startBtn) startBtn.style.display = 'inline-block';
            if (stopBtn) stopBtn.style.display = 'none';
            if (status) {
                status.textContent = '⭕ Tracking stopped';
                status.style.cssText = 'padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; background: #f8d7da; color: #721c24;';
            }
            if (info) info.style.display = 'none';
        }
    }
    
    getRouteData() {
        try {
            const lastRoute = window.lastRouteData || {};
            return {
                route_type: lastRoute.type || 'unknown',
                timestamp: new Date().toISOString(),
                user_agent: navigator.userAgent
            };
        } catch (error) {
            return { timestamp: new Date().toISOString() };
        }
    }
    
    showSuccess(message) { this.showMessage(message, 'success'); }
    showError(message) { this.showMessage(message, 'error'); }
    
    showMessage(message, type) {
        let messageEl = document.getElementById('tracking-message');
        if (!messageEl) {
            messageEl = document.createElement('div');
            messageEl.id = 'tracking-message';
            messageEl.style.cssText = `
                position: fixed; top: 20px; right: 20px; padding: 12px 20px;
                border-radius: 6px; color: white; font-weight: 500; z-index: 10000;
                max-width: 300px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            `;
            document.body.appendChild(messageEl);
        }
        
        messageEl.textContent = message;
        messageEl.style.backgroundColor = type === 'success' ? '#28a745' : '#dc3545';
        messageEl.style.display = 'block';
        
        setTimeout(() => {
            if (messageEl && messageEl.parentNode) {
                messageEl.style.display = 'none';
            }
        }, 5000);
    }
}

// Auto-initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize for auditors
    const userRole = document.body.getAttribute('data-user-role');
    if (userRole === 'auditor' || window.location.pathname.includes('auditor')) {
        window.locationTracker = new LocationTracker();
        console.log('🎯 Location tracking ready for auditor');
    }
});