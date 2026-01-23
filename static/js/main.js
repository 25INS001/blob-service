const API_BASE = '/blob'; // Updated to match Nginx route

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return; // Should be in base.html

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    // Icon based on type
    let icon = '';
    if (type === 'success') icon = '<i data-lucide="check-circle" style="color: var(--success); width: 16px;"></i>';
    else if (type === 'error') icon = '<i data-lucide="alert-circle" style="color: var(--danger); width: 16px;"></i>';
    else icon = '<i data-lucide="info" style="color: var(--accent); width: 16px;"></i>';

    toast.innerHTML = `${icon} <span>${message}</span>`;
    container.appendChild(toast);
    
    // Re-run icons for the new element if possible, or just insert SVG directly in future.
    // Since we use lucide.createIcons() globally, we might need to run it on this node.
    if (window.lucide) lucide.createIcons({ root: toast });

    // Trigger animation
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    // Remove after 3s
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// --- Auth & API Helpers ---

function getHeaders() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = '/blob/login'; // Redirect to login
        return {};
    }
    return {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    };
}

function checkAuth(isLoginPage = false) {
    const token = localStorage.getItem('access_token');
    if (isLoginPage && token) {
        window.location.href = '/blob/'; // Redirect to dashboard if logged in
    } 
    if (!isLoginPage && !token) {
        window.location.href = '/blob/login';
    }
    
    // Update User Info in UI
    if (!isLoginPage && token) {
        const email = localStorage.getItem('user_email');
        const userEl = document.getElementById('user-email-display');
        if (userEl) userEl.textContent = email;
        
        // Show/Hide Admin Tab
        const id = localStorage.getItem('user_id');
        if (id === '41') {
            document.querySelectorAll('.admin-only').forEach(el => el.classList.remove('hidden'));
        }
    }
}

function logout() {
    localStorage.clear();
    window.location.href = '/blob/login';
}

async function apiCall(endpoint, options = {}) {
    const defaults = { headers: getHeaders() };
    // Merge headers carefully (allow overriding content-type for uploads)
    if (options.body instanceof FormData) {
        delete defaults.headers['Content-Type'];
    }
    
    options = { ...defaults, ...options };
    
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    
    if (response.status === 401) {
        logout();
        return null;
    }
    
    return response;
}

// --- Common UI Helpers ---

function openModal(id) {
    document.getElementById(id).classList.remove('hidden');
}

function closeModal(id) {
    document.getElementById(id).classList.add('hidden');
}

// Close modals on escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay').forEach(el => el.classList.add('hidden'));
    }
});
