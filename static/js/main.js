// ===================== المتغيرات العامة =====================
let statsChart = null;
let usersChart = null;

// ===================== تهيئة الصفحة =====================
document.addEventListener('DOMContentLoaded', function() {
    loadDashboard();
    loadUsers();
    loadChannels();
    loadGroups();
    loadPosts();
    setupEventListeners();
    updateTime();
    setInterval(updateTime, 1000);
});

// ===================== تحديث الوقت =====================
function updateTime() {
    const now = new Date();
    document.getElementById('time').textContent = now.toLocaleTimeString('ar-EG');
}

// ===================== تبديل الصفحات =====================
function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.style.display = 'none');
    document.getElementById(pageId).style.display = 'block';
    document.querySelectorAll('.sidebar nav a').forEach(a => a.classList.remove('active'));
    document.querySelector(`.sidebar nav a[data-page="${pageId}"]`).classList.add('active');
    document.getElementById('page-title').textContent = document.querySelector(`.sidebar nav a[data-page="${pageId}"]`).textContent;
}

// ===================== تحميل لوحة التحكم =====================
async function loadDashboard() {
    try {
        const response = await fetch('/api/stats');
        const data = await response.json();
        
        document.getElementById('total-users').textContent = data.total_users || 0;
        document.getElementById('total-channels').textContent = data.channels || 0;
        document.getElementById('total-posts').textContent = data.pending_posts || 0;
        document.getElementById('total-groups').textContent = data.groups || 0;
        
        document.getElementById('status').textContent = '🟢 متصل';
        document.getElementById('status').className = 'online';
    } catch (error) {
        console.error('خطأ في تحميل الإحصائيات:', error);
        document.getElementById('status').textContent = '🔴 غير متصل';
        document.getElementById('status').className = 'offline';
    }
}

// ===================== تحميل المستخدمين =====================
async function loadUsers() {
    try {
        const response = await fetch('/api/users');
        const users = await response.json();
        const tbody = document.getElementById('usersTableBody');
        
        if (!users || users.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center">لا يوجد مستخدمين</td></tr>';
            return;
        }
        
        tbody.innerHTML = users.map(user => `
            <tr>
                <td>${user.user_id}</td>
                <td>${user.username || 'غير معروف'}</td>
                <td><span class="status-badge ${user.banned ? 'banned' : 'active'}">${user.banned ? '🚫 محظور' : '✅ نشط'}</span></td>
                <td>${user.channels || 0}</td>
                <td>
                    <button class="btn ${user.banned ? 'btn-success' : 'btn-danger'}" onclick="toggleBan(${user.user_id})">
                        ${user.banned ? '🔓 إلغاء الحظر' : '🚫 حظر'}
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('خطأ في تحميل المستخدمين:', error);
    }
}

// ===================== تحميل القنوات =====================
async function loadChannels() {
    try {
        const response = await fetch('/api/channels');
        const channels = await response.json();
        const tbody = document.getElementById('channelsTableBody');
        
        if (!channels || channels.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center">لا توجد قنوات</td></tr>';
            return;
        }
        
        tbody.innerHTML = channels.map(ch => `
            <tr>
                <td>${ch.user_id}</td>
                <td>${ch.channel_id}</td>
                <td>${ch.channel_name}</td>
                <td><span class="status-badge ${ch.banned ? 'banned' : 'active'}">${ch.banned ? '⛔ محظورة' : '✅ نشطة'}</span></td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('خطأ في تحميل القنوات:', error);
    }
}

// ===================== تحميل المجموعات =====================
async function loadGroups() {
    try {
        const response = await fetch('/api/groups');
        const groups = await response.json();
        const tbody = document.getElementById('groupsTableBody');
        
        if (!groups || groups.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center">لا توجد مجموعات</td></tr>';
            return;
        }
        
        tbody.innerHTML = groups.map(g => `
            <tr>
                <td>${g.chat_id}</td>
                <td>${g.chat_name}</td>
                <td>${g.added_by}</td>
                <td><span class="status-badge ${g.banned ? 'banned' : 'active'}">${g.banned ? '⛔ محظورة' : '✅ نشطة'}</span></td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('خطأ في تحميل المجموعات:', error);
    }
}

// ===================== تحميل المنشورات =====================
async function loadPosts() {
    try {
        const response = await fetch('/api/posts');
        const posts = await response.json();
        const tbody = document.getElementById('postsTableBody');
        
        if (!posts || posts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center">لا توجد منشورات غير منشورة</td></tr>';
            return;
        }
        
        tbody.innerHTML = posts.map(p => `
            <tr>
                <td>${p.channel_name}</td>
                <td>${(p.text || '').substring(0, 50)}${(p.text || '').length > 50 ? '...' : ''}</td>
                <td><span class="status-badge pending">${p.media_type || 'text'}</span></td>
                <td>${p.created_at ? new Date(p.created_at).toLocaleDateString('ar-EG') : '-'}</td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('خطأ في تحميل المنشورات:', error);
    }
}

// ===================== حظر/إلغاء حظر مستخدم =====================
async function toggleBan(userId) {
    if (!confirm('هل أنت متأكد من تغيير حالة المستخدم؟')) return;
    
    try {
        const response = await fetch(`/api/users/${userId}/toggle-ban`, { method: 'POST' });
        const data = await response.json();
        alert(data.message || 'تم تغيير الحالة بنجاح');
        loadUsers();
    } catch (error) {
        alert('❌ فشل تغيير الحالة');
        console.error(error);
    }
}

// ===================== حدث البحث =====================
function setupEventListeners() {
    document.getElementById('searchUsers')?.addEventListener('input', function() {
        const query = this.value.toLowerCase();
        const rows = document.querySelectorAll('#usersTableBody tr');
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(query) ? '' : 'none';
        });
    });
    
    document.querySelectorAll('.sidebar nav a').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const page = this.dataset.page;
            showPage(page);
            switch(page) {
                case 'dashboard': loadDashboard(); break;
                case 'users': loadUsers(); break;
                case 'channels': loadChannels(); break;
                case 'groups': loadGroups(); break;
                case 'posts': loadPosts(); break;
            }
        });
    });
    
    document.getElementById('settingsForm')?.addEventListener('submit', async function(e) {
        e.preventDefault();
        const data = {
            publish_interval: parseInt(document.getElementById('publishInterval').value) || 720,
            max_posts: parseInt(document.getElementById('maxPosts').value) || 1000,
            auto_publish: document.getElementById('autoPublish').checked,
            auto_backup: document.getElementById('autoBackup').checked
        };
        
        try {
            const response = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await response.json();
            alert(result.message || '✅ تم حفظ الإعدادات');
        } catch (error) {
            alert('❌ فشل حفظ الإعدادات');
        }
    });
}

setInterval(() => {
    const activePage = document.querySelector('.sidebar nav a.active');
    if (activePage) {
        const page = activePage.dataset.page;
        switch(page) {
            case 'dashboard': loadDashboard(); break;
            case 'users': loadUsers(); break;
            case 'channels': loadChannels(); break;
            case 'groups': loadGroups(); break;
            case 'posts': loadPosts(); break;
        }
    }
}, 30000);
