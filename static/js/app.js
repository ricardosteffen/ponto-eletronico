// Funções utilitárias globais

// Função para fazer requisições autenticadas
async function fetchWithAuth(url, options = {}) {
    const token = localStorage.getItem('token');

    if (!token) {
        console.warn('Token não encontrado');
        return null;
    }

    const defaultHeaders = {
        'Authorization': `Bearer ${token}`
    };

    // Não adiciona Content-Type se for FormData
    if (options.body instanceof FormData) {
        options.headers = {
            ...defaultHeaders,
            ...(options.headers || {})
        };
    } else {
        options.headers = {
            ...defaultHeaders,
            ...(options.headers || {})
        };
    }

    try {
        const response = await fetch(url, options);

        // Se receber 401, limpa e redireciona
        if (response.status === 401) {
            console.warn('Token inválido ou expirado');
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            window.location.href = '/login';
            return null;
        }

        return response;
    } catch (error) {
        console.error('Erro na requisição:', error);
        return null;
    }
}

// Função de logout
async function logout() {
    try {
        await fetch('/auth/logout', { method: 'POST' });
    } catch (error) {
        console.error('Erro no logout:', error);
    } finally {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = '/login';
    }
}

// Verifica autenticação
function checkAuth() {
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = '/login';
        return false;
    }
    return true;
}

// Formata data para exibição
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('pt-BR');
}

// Formata hora para exibição
function formatTime(dateString) {
    const date = new Date(dateString);
    return date.toLocaleTimeString('pt-BR');
}

// Formata data e hora para exibição
function formatDateTime(dateString) {
    const date = new Date(dateString);
    return `${date.toLocaleDateString('pt-BR')} ${date.toLocaleTimeString('pt-BR')}`;
}

// Mostra mensagem de alerta
function showAlert(elementId, message, type = 'danger') {
    const alertEl = document.getElementById(elementId);
    if (alertEl) {
        alertEl.className = `alert alert-${type}`;
        alertEl.textContent = message;
        alertEl.classList.remove('d-none');

        if (type === 'success') {
            setTimeout(() => {
                alertEl.classList.add('d-none');
            }, 5000);
        }
    }
}

// Esconde alerta
function hideAlert(elementId) {
    const alertEl = document.getElementById(elementId);
    if (alertEl) {
        alertEl.classList.add('d-none');
    }
}

// Verifica se está em dispositivo móvel
function isMobile() {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
}
