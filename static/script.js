document.addEventListener('DOMContentLoaded', function() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(protocol + '//' + window.location.host + '/ws');
    let chartPosts, chartViews;

    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.type === 'stats') updateStats(data.data);
        else if (data.type === 'users') updateUsersTable(data.data);
        else if (data.type === 'channels') updateChannelsTable(data.data);
        else if (data.type === 'groups') updateGroupsTable(data.data);
        else if (data.type === 'posts') updatePostsTable(data.data);
        else if (data.type === 'logs') updateLogs(data.data);
        else if (data.type === 'chart_posts') updatePostsChart(data.data);
        else if (data.type === 'chart_views') updateViewsChart(data.data);
    };
    ws.onclose = function() { setTimeout(() => location.reload(), 5000); };

    function updateStats(data) {
        document.getElementById('totalUsers').textContent = data.total_users;
        document.getElementById('activeUsers').textContent = data.active_users;
        document.getElementById('bannedUsers').textContent = data.banned_users;
        document.getElementById('pendingPosts').textContent = data.pending_posts;
        document.getElementById('groups').textContent = data.groups;
        document.getElementById('channels').textContent = data.channels;
        document.getElementById('ramPercent').textContent = data.ram_percent + '%';
        document.getElementById('ramUsed').textContent = data.ram_used;
        document.getElementById('ramTotal').textContent = data.ram_total;
        document.getElementById('uptimeHours').textContent = data.uptime_hours;
    }

    function updateUsersTable(users) {
        const tbody = document.getElementById('usersTableBody');
        tbody.innerHTML = '';
        users.forEach(u => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${u.user_id}</td>
                <td><span class="status-badge ${u.banned ? 'banned' : 'active'}">${u.banned ? '🚫 محظور' : '✅ نشط'}</span></td>
                <td>${u.banned ? `<button class="btn btn-success" onclick="unbanUser(${u.user_id})">🔓 إلغاء الحظر</button>` : `<button class="btn btn-danger" onclick="banUser(${u.user_id})">⛔ حظر</button>`}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function updateChannelsTable(channels) {
        const tbody = document.getElementById('channelsTableBody');
        tbody.innerHTML = '';
        channels.forEach(c => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${c.user_id}</td>
                <td>${c.channel_name} (${c.channel_id})</td>
                <td><span class="status-badge ${c.banned ? 'banned' : 'active'}">${c.banned ? '⛔ محظورة' : '✅ نشطة'}</span></td>
                <td>${c.banned ? `<button class="btn btn-success" onclick="unbanChannel(${c.id})">🔓 إلغاء الحظر</button>` : `<button class="btn btn-danger" onclick="banChannel(${c.id})">⛔ حظر</button>`}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function updateGroupsTable(groups) {
        const tbody = document.getElementById('groupsTableBody');
        tbody.innerHTML = '';
        groups.forEach(g => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${g.chat_name}</td>
                <td>${g.chat_id}</td>
                <td><span class="status-badge ${g.banned ? 'banned' : 'active'}">${g.banned ? '⛔ محظورة' : '✅ نشطة'}</span></td>
                <td>${g.banned ? `<button class="btn btn-success" onclick="unbanGroup(${g.chat_id})">🔓 إلغاء الحظر</button>` : `<button class="btn btn-danger" onclick="banGroup(${g.chat_id})">⛔ حظر</button>`}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function updatePostsTable(posts) {
        const tbody = document.getElementById('postsTableBody');
        tbody.innerHTML = '';
        posts.forEach(p => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${p.text ? p.text.substring(0, 50) + '...' : '(بدون نص)'}</td>
                <td>${p.media_type || 'نص'}</td>
                <td>${p.channel_name || 'غير معروف'}</td>
                <td>
                    <button class="btn btn-success" onclick="publishPost(${p.id})">📤 نشر</button>
                    <button class="btn btn-danger" onclick="deletePost(${p.id})">🗑️ حذف</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    function updateLogs(logs) {
        document.getElementById('logEntries').innerHTML = logs.map(log => `<div>${log}</div>`).join('');
    }

    function initCharts() {
        chartPosts = new Chart(document.getElementById('postsChart'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'المنشورات', data: [], borderColor: '#e94560', fill: false }] },
            options: { responsive: true }
        });
        chartViews = new Chart(document.getElementById('viewsChart'), {
            type: 'bar',
            data: { labels: [], datasets: [{ label: 'المشاهدات', data: [], backgroundColor: '#0984e3' }] },
            options: { responsive: true }
        });
    }

    function updatePostsChart(data) {
        if (chartPosts) {
            chartPosts.data.labels = data.labels;
            chartPosts.data.datasets[0].data = data.values;
            chartPosts.update();
        }
    }

    function updateViewsChart(data) {
        if (chartViews) {
            chartViews.data.labels = data.labels;
            chartViews.data.datasets[0].data = data.values;
            chartViews.update();
        }
    }

    window.banUser = function(userId) {
        if (confirm(`هل أنت متأكد من حظر المستخدم ${userId}؟`)) {
            ws.send(JSON.stringify({ action: 'ban_user', user_id: userId }));
        }
    };
    window.unbanUser = function(userId) {
        ws.send(JSON.stringify({ action: 'unban_user', user_id: userId }));
    };
    window.banChannel = function(channelId) {
        ws.send(JSON.stringify({ action: 'ban_channel', channel_id: channelId }));
    };
    window.unbanChannel = function(channelId) {
        ws.send(JSON.stringify({ action: 'unban_channel', channel_id: channelId }));
    };
    window.banGroup = function(groupId) {
        ws.send(JSON.stringify({ action: 'ban_group', group_id: groupId }));
    };
    window.unbanGroup = function(groupId) {
        ws.send(JSON.stringify({ action: 'unban_group', group_id: groupId }));
    };
    window.publishPost = function(postId) {
        ws.send(JSON.stringify({ action: 'publish_post', post_id: postId }));
    };
    window.deletePost = function(postId) {
        if (confirm('هل أنت متأكد من حذف هذا المنشور؟')) {
            ws.send(JSON.stringify({ action: 'delete_post', post_id: postId }));
        }
    };

    document.getElementById('unbanAllBtn').addEventListener('click', function() {
        if (confirm('هل أنت متأكد من إلغاء حظر جميع المستخدمين؟')) {
            ws.send(JSON.stringify({ action: 'unban_all_users' }));
        }
    });

    document.getElementById('exportBtn').addEventListener('click', function() {
        window.location.href = '/api/export?type=users';
    });

    document.getElementById('themeToggle').addEventListener('click', function() {
        document.body.classList.toggle('dark-mode');
        this.textContent = document.body.classList.contains('dark-mode') ? '☀️' : '🌙';
    });

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(tc => tc.classList.add('hidden'));
            document.getElementById('tab-' + this.dataset.tab).classList.remove('hidden');
            ws.send(JSON.stringify({ action: 'refresh_' + this.dataset.tab }));
        });
    });

    document.getElementById('userSearch').addEventListener('input', function() {
        const query = this.value.toLowerCase();
        document.querySelectorAll('#usersTableBody tr').forEach(tr => {
            tr.style.display = tr.textContent.toLowerCase().includes(query) ? '' : 'none';
        });
    });

    setTimeout(() => {
        ws.send(JSON.stringify({ action: 'refresh_users' }));
        ws.send(JSON.stringify({ action: 'refresh_channels' }));
        ws.send(JSON.stringify({ action: 'refresh_groups' }));
        ws.send(JSON.stringify({ action: 'refresh_posts' }));
        ws.send(JSON.stringify({ action: 'refresh_logs' }));
        ws.send(JSON.stringify({ action: 'refresh_charts' }));
    }, 500);

    initCharts();
});
