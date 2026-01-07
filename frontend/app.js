/**
 * Chat2Excel Frontend Application
 */

// 开发环境使用完整地址，生产环境使用相对路径
const API_BASE = window.location.hostname === 'localhost' || window.location.protocol === 'file:' 
    ? 'http://localhost:8000/api' 
    : '/api';

// ============ 状态管理 ============
const state = {
    config: null,
    messages: [],
    isLoading: false,
    sessionId: localStorage.getItem('sessionId') || null,
    tables: [],
    currentTable: null,
    pollingInterval: null,
    // 报告相关
    reports: [],
    currentReport: null,
    isGeneratingReport: false,
    // Clarification 状态
    pendingClarification: null,  // { questions: [], context: '', original_request: '' }
    // Agent 监控状态
    agentMonitor: {
        agents: {},        // agent_id -> { type, label, status, logs: [] }
        expanded: true,    // 监控面板是否展开
        viewMode: 'grid',  // 'grid' | 'list' | 'timeline'
        activeAgentId: null,  // 当前选中的 agent
    },
};

// ============ DOM 元素 ============
const elements = {
    // 导航
    navBtns: document.querySelectorAll('.nav-btn'),
    tabContents: document.querySelectorAll('.tab-content'),
    
    // 状态
    status: document.getElementById('status'),
    statusDot: document.querySelector('.status-dot'),
    statusText: document.querySelector('.status-text'),
    
    // 数据页面
    uploadArea: document.getElementById('uploadArea'),
    fileInput: document.getElementById('fileInput'),
    selectFilesBtn: document.getElementById('selectFilesBtn'),
    generateDescriptions: document.getElementById('generateDescriptions'),
    processStatus: document.getElementById('processStatus'),
    statusList: document.getElementById('statusList'),
    knowledgeSection: document.getElementById('knowledgeSection'),
    tablesGrid: document.getElementById('tablesGrid'),
    tableModal: document.getElementById('tableModal'),
    modalTitle: document.getElementById('modalTitle'),
    modalBody: document.getElementById('modalBody'),
    closeModal: document.getElementById('closeModal'),
    
    // 控制台
    toggleConsole: document.getElementById('toggleConsole'),
    consolePanel: document.getElementById('consolePanel'),
    consoleBody: document.getElementById('consoleBody'),
    closeConsole: document.getElementById('closeConsole'),
    clearAllBtn: document.getElementById('clearAllBtn'),
    
    // 对话
    chatMessages: document.getElementById('chatMessages'),
    chatInput: document.getElementById('chatInput'),
    sendBtn: document.getElementById('sendBtn'),
    chatSidebar: document.getElementById('chatSidebar'),
    sidebarContent: document.getElementById('sidebarContent'),
    toggleSidebar: document.getElementById('toggleSidebar'),
    welcomeHint: document.getElementById('welcomeHint'),
    suggestedQuestions: document.getElementById('suggestedQuestions'),
    modelIndicator: document.getElementById('modelIndicator'),
    
    // 配置
    apiKey: document.getElementById('apiKey'),
    toggleApiKey: document.getElementById('toggleApiKey'),
    baseUrl: document.getElementById('baseUrl'),
    testConnection: document.getElementById('testConnection'),
    testResult: document.getElementById('testResult'),
    
    defaultModel: document.getElementById('defaultModel'),
    enableThinking: document.getElementById('enableThinking'),
    maxTokens: document.getElementById('maxTokens'),
    temperature: document.getElementById('temperature'),
    temperatureValue: document.getElementById('temperatureValue'),
    
    agentConfigs: document.getElementById('agentConfigs'),
    
    resetConfig: document.getElementById('resetConfig'),
    saveConfig: document.getElementById('saveConfig'),
    
    // 报告
    reportRequest: document.getElementById('reportRequest'),
    generateReportBtn: document.getElementById('generateReportBtn'),
    reportProgress: document.getElementById('reportProgress'),
    progressStatus: document.getElementById('progressStatus'),
    reportProgressBar: document.getElementById('reportProgressBar'),
    progressLog: document.getElementById('progressLog'),
    reportPreview: document.getElementById('reportPreview'),
    reportTitle: document.getElementById('reportTitle'),
    reportSummary: document.getElementById('reportSummary'),
    reportContent: document.getElementById('reportContent'),
    exportReportBtn: document.getElementById('exportReportBtn'),
    closeReportBtn: document.getElementById('closeReportBtn'),
    reportHistory: document.getElementById('reportHistory'),
    reportList: document.getElementById('reportList'),
};

// ============ API 调用 ============
async function apiCall(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: '请求失败' }));
        throw new Error(error.detail || '请求失败');
    }
    
    return response.json();
}

async function apiUpload(endpoint, formData) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        body: formData,
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: '上传失败' }));
        throw new Error(error.detail || '上传失败');
    }
    
    return response.json();
}

// ============ 配置管理 ============
async function loadConfig() {
    try {
        const config = await apiCall('/config');
        state.config = config;
        updateConfigUI(config);
        updateStatus(config.api_key_configured);
    } catch (error) {
        console.error('加载配置失败:', error);
        showTestResult('加载配置失败: ' + error.message, false);
    }
}

function updateConfigUI(config) {
    // API 配置
    elements.apiKey.value = '';
    elements.apiKey.placeholder = config.api_key_configured 
        ? config.api_key_masked 
        : '请输入 API Key';
    elements.baseUrl.value = config.base_url;
    
    // 默认配置
    elements.defaultModel.value = config.default.model;
    elements.enableThinking.checked = config.default.enable_thinking;
    elements.maxTokens.value = config.default.max_tokens;
    elements.temperature.value = config.default.temperature;
    elements.temperatureValue.textContent = config.default.temperature;
    
    // Agent 配置
    renderAgentConfigs(config.agents);
}

function renderAgentConfigs(agents) {
    const agentInfo = {
        router: { name: 'Router Agent', desc: '意图识别' },
        data: { name: 'Data Agent', desc: '数据处理' },
        clarification: { name: 'Clarification Agent', desc: '问题澄清' },
        center: { name: 'Center Agent', desc: '报告规划' },
        research: { name: 'Research Agent', desc: '章节研究' },
        nl2sql: { name: 'NL2SQL Agent', desc: 'SQL 生成' },
        chart: { name: 'Chart Agent', desc: '图表配置' },
        summary: { name: 'Summary Agent', desc: '总结生成' },
    };
    
    let html = '';
    for (const [id, config] of Object.entries(agents)) {
        const info = agentInfo[id] || { name: id, desc: '' };
        html += `
            <div class="agent-config-item" data-agent="${id}">
                <div class="agent-config-header">
                    <h4>${info.name}</h4>
                    <span>${info.desc}</span>
                </div>
                <div class="agent-config-fields">
                    <div class="form-group">
                        <label>模型</label>
                        <input type="text" class="agent-model" 
                            value="${config.model ?? ''}" 
                            placeholder="使用默认">
                    </div>
                    <div class="form-group">
                        <label>温度</label>
                        <input type="number" class="agent-temperature" 
                            value="${config.temperature ?? ''}" 
                            min="0" max="1" step="0.1" 
                            placeholder="使用默认">
                    </div>
                    <div class="form-group">
                        <label>
                            <input type="checkbox" class="agent-thinking" 
                                ${config.enable_thinking ? 'checked' : ''}>
                            思考模式
                        </label>
                    </div>
                    <div class="form-group">
                        <label>Max Tokens</label>
                        <input type="number" class="agent-max-tokens" 
                            value="${config.max_tokens ?? ''}" 
                            placeholder="使用默认">
                    </div>
                </div>
            </div>
        `;
    }
    elements.agentConfigs.innerHTML = html;
}

async function saveConfig() {
    try {
        elements.saveConfig.disabled = true;
        elements.saveConfig.innerHTML = '<span class="loading"></span>';
        
        // 收集配置
        const config = {
            base_url: elements.baseUrl.value,
            default: {
                model: elements.defaultModel.value,
                enable_thinking: elements.enableThinking.checked,
                max_tokens: parseInt(elements.maxTokens.value),
                temperature: parseFloat(elements.temperature.value),
                top_p: 0.9,
            },
            agents: {},
        };
        
        // 如果输入了新的 API Key
        if (elements.apiKey.value) {
            config.api_key = elements.apiKey.value;
        }
        
        // 收集 Agent 配置
        document.querySelectorAll('.agent-config-item').forEach(item => {
            const agentId = item.dataset.agent;
            const model = item.querySelector('.agent-model').value.trim();
            const temp = item.querySelector('.agent-temperature').value;
            const thinking = item.querySelector('.agent-thinking').checked;
            const maxTokens = item.querySelector('.agent-max-tokens').value;
            
            config.agents[agentId] = {
                model: model || null,
                temperature: temp ? parseFloat(temp) : null,
                enable_thinking: thinking || null,
                max_tokens: maxTokens ? parseInt(maxTokens) : null,
            };
        });
        
        await apiCall('/config', {
            method: 'PUT',
            body: JSON.stringify(config),
        });
        
        showTestResult('配置已保存', true);
        await loadConfig();
    } catch (error) {
        showTestResult('保存失败: ' + error.message, false);
    } finally {
        elements.saveConfig.disabled = false;
        elements.saveConfig.innerHTML = '💾 保存配置';
    }
}

async function testConnection() {
    try {
        elements.testConnection.disabled = true;
        elements.testConnection.innerHTML = '<span class="loading"></span> 测试中...';
        elements.testResult.textContent = '';
        elements.testResult.className = 'test-result';
        
        const result = await apiCall('/config/test', { method: 'POST' });
        
        if (result.success) {
            showTestResult(`✅ ${result.message}`, true);
            updateStatus(true);
        } else {
            showTestResult(`❌ ${result.message}`, false);
            updateStatus(false);
        }
    } catch (error) {
        showTestResult(`❌ ${error.message}`, false);
        updateStatus(false);
    } finally {
        elements.testConnection.disabled = false;
        elements.testConnection.innerHTML = '🔌 测试连接';
    }
}

async function resetConfig() {
    if (!confirm('确定要重置为默认配置吗？（API Key 会保留）')) return;
    
    try {
        await apiCall('/config/reset', { method: 'POST' });
        showTestResult('已重置为默认配置', true);
        await loadConfig();
    } catch (error) {
        showTestResult('重置失败: ' + error.message, false);
    }
}

function showTestResult(message, success) {
    elements.testResult.textContent = message;
    elements.testResult.className = `test-result ${success ? 'success' : 'error'}`;
}

function updateStatus(connected) {
    elements.statusDot.className = `status-dot ${connected ? 'connected' : 'error'}`;
    elements.statusText.textContent = connected ? '已连接' : '未连接';
}

// ============ 文件上传管理 ============
async function uploadFiles(files) {
    if (!files || files.length === 0) return;
    
    const formData = new FormData();
    
    // 添加文件
    for (const file of files) {
        formData.append('files', file);
    }
    
    // 添加会话ID
    if (state.sessionId) {
        formData.append('session_id', state.sessionId);
    }
    
    // 添加是否生成描述选项
    formData.append('generate_descriptions', elements.generateDescriptions.checked);
    
    try {
        elements.processStatus.style.display = 'block';
        elements.statusList.innerHTML = '<div class="loading"></div> 正在上传...';
        
        const result = await apiUpload('/upload', formData);
        
        // 保存会话ID
        state.sessionId = result.session_id;
        localStorage.setItem('sessionId', result.session_id);
        
        // 更新状态列表
        renderFileStatus(result.files);
        
        // 开始轮询处理状态
        startPollingStatus();
        
    } catch (error) {
        console.error('上传失败:', error);
        elements.statusList.innerHTML = `<div class="status-item"><span class="file-status error">❌ ${error.message}</span></div>`;
    }
}

function renderFileStatus(files) {
    const statusIcons = {
        pending: '⏳',
        processing: '🔄',
        ready: '✅',
        error: '❌',
    };
    
    const statusLabels = {
        pending: '等待处理',
        processing: '处理中',
        ready: '已完成',
        error: '处理失败',
    };
    
    elements.statusList.innerHTML = files.map(file => {
        const fileInfo = file.file_info || {};
        const progress = file.progress || {};
        
        // 文件信息
        const fileInfoHtml = `
            <div class="file-info-row">
                <div class="file-info-item">
                    <span>📦 大小:</span>
                    <span class="value">${fileInfo.file_size_mb?.toFixed(2) || '-'} MB</span>
                </div>
                ${fileInfo.row_count ? `
                <div class="file-info-item">
                    <span>📊 行数:</span>
                    <span class="value">${formatNumber(fileInfo.row_count)}</span>
                </div>
                <div class="file-info-item">
                    <span>📋 列数:</span>
                    <span class="value">${fileInfo.column_count || '-'}</span>
                </div>
                ` : ''}
            </div>
        `;
        
        // 进度条 (仅处理中时显示)
        let progressHtml = '';
        if (file.status === 'processing' && progress.current_step) {
            const remainingText = progress.estimated_remaining_seconds 
                ? `预计剩余: ${formatTime(progress.estimated_remaining_seconds)}`
                : '';
            
            progressHtml = `
                <div class="progress-section">
                    <div class="progress-header">
                        <span class="progress-step">
                            ${progress.current_step} (${progress.step_index}/${progress.total_steps})
                        </span>
                        <span class="progress-percent">${progress.percent}%</span>
                    </div>
                    <div class="progress-bar-container">
                        <div class="progress-bar" style="width: ${progress.percent}%"></div>
                    </div>
                    <div class="progress-footer">
                        <span>${remainingText}</span>
                        <span>${progress.started_at ? '开始于 ' + formatStartTime(progress.started_at) : ''}</span>
                    </div>
                </div>
            `;
        }
        
        // 错误信息
        const errorHtml = file.error_message 
            ? `<div class="error-message">❌ ${file.error_message}</div>` 
            : '';
        
        // 操作按钮
        let actionsHtml = '';
        if (file.status === 'processing') {
            actionsHtml = `
                <button class="btn-icon danger" onclick="cancelProcessing('${file.file_id}')" title="取消处理">
                    ⏹️
                </button>
            `;
        } else {
            actionsHtml = `
                <button class="btn-icon danger" onclick="deleteFile('${file.file_id}')" title="删除">
                    🗑️
                </button>
            `;
        }
        
        return `
            <div class="status-item" data-file-id="${file.file_id}">
                <div class="status-item-header">
                    <span class="file-name">📄 ${file.original_name}</span>
                    <div class="status-item-actions">
                        <span class="file-status ${file.status}">
                            ${statusIcons[file.status]} ${statusLabels[file.status]}
                        </span>
                        ${actionsHtml}
                    </div>
                </div>
                ${fileInfoHtml}
                ${progressHtml}
                ${errorHtml}
            </div>
        `;
    }).join('');
    
    // 更新控制台日志
    updateConsoleLogs(files);
}

function updateConsoleLogs(files) {
    const allLogs = [];
    
    files.forEach(file => {
        if (file.progress && file.progress.logs && file.progress.logs.length > 0) {
            file.progress.logs.forEach(log => {
                allLogs.push({
                    fileName: file.original_name,
                    log: log,
                    status: file.status
                });
            });
        }
    });
    
    if (allLogs.length === 0) {
        elements.consoleBody.innerHTML = '<div class="console-placeholder">等待处理...</div>';
        return;
    }
    
    elements.consoleBody.innerHTML = allLogs.map(item => {
        // 解析日志类型
        let logClass = 'info';
        if (item.log.includes('✓') || item.log.includes('完成')) {
            logClass = 'success';
        } else if (item.log.includes('✗') || item.log.includes('失败') || item.log.includes('错误')) {
            logClass = 'error';
        } else if (item.log.includes('开始')) {
            logClass = 'info';
        }
        
        return `<div class="console-line ${logClass}">${item.log}</div>`;
    }).join('');
    
    // 自动滚动到底部
    elements.consoleBody.scrollTop = elements.consoleBody.scrollHeight;
}

function formatTime(seconds) {
    if (seconds < 60) {
        return `${seconds}秒`;
    } else if (seconds < 3600) {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}分${secs}秒`;
    } else {
        const hours = Math.floor(seconds / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        return `${hours}小时${mins}分`;
    }
}

function formatStartTime(isoString) {
    try {
        const date = new Date(isoString);
        return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
        return '';
    }
}

function startPollingStatus() {
    // 清除已有的轮询
    if (state.pollingInterval) {
        clearInterval(state.pollingInterval);
    }
    
    // 每1秒轮询一次（处理中时需要更频繁更新进度）
    state.pollingInterval = setInterval(async () => {
        try {
            const status = await apiCall(`/upload/status/${state.sessionId}`);
            renderFileStatus(status.files);
            
            // 如果所有文件都处理完成，停止轮询并加载知识库
            if (status.all_ready) {
                clearInterval(state.pollingInterval);
                state.pollingInterval = null;
                await loadKnowledgeBase();
            }
        } catch (error) {
            console.error('获取状态失败:', error);
        }
    }, 1000);
}

function toggleConsolePanel() {
    const isVisible = elements.consolePanel.style.display !== 'none';
    elements.consolePanel.style.display = isVisible ? 'none' : 'block';
    elements.toggleConsole.textContent = isVisible ? '📋 控制台' : '📋 隐藏';
}

// ============ 删除和中断操作 ============
async function deleteFile(fileId) {
    if (!confirm('确定要删除这个文件吗？关联的知识库也会被删除。')) return;
    
    try {
        await apiCall(`/file/${state.sessionId}/${fileId}`, { method: 'DELETE' });
        // 刷新状态
        const status = await apiCall(`/upload/status/${state.sessionId}`);
        renderFileStatus(status.files);
        
        // 如果没有文件了，隐藏状态区域
        if (status.files.length === 0) {
            elements.processStatus.style.display = 'none';
        }
        
        // 刷新知识库
        await loadKnowledgeBase();
    } catch (error) {
        console.error('删除文件失败:', error);
        alert('删除失败: ' + error.message);
    }
}

async function cancelProcessing(fileId) {
    if (!confirm('确定要取消处理吗？')) return;
    
    try {
        await apiCall(`/cancel/${state.sessionId}/${fileId}`, { method: 'POST' });
        // 刷新状态
        const status = await apiCall(`/upload/status/${state.sessionId}`);
        renderFileStatus(status.files);
    } catch (error) {
        console.error('取消处理失败:', error);
        alert('取消失败: ' + error.message);
    }
}

async function deleteTable(tableId) {
    if (!confirm('确定要删除这个知识库吗？')) return;
    
    try {
        await apiCall(`/table/${state.sessionId}/${tableId}`, { method: 'DELETE' });
        // 刷新知识库
        await loadKnowledgeBase();
    } catch (error) {
        console.error('删除知识库失败:', error);
        alert('删除失败: ' + error.message);
    }
}

async function clearAll() {
    if (!confirm('确定要清空所有文件和知识库吗？此操作不可恢复！')) return;
    
    try {
        await apiCall(`/session/${state.sessionId}/clear`, { method: 'DELETE' });
        
        // 停止轮询
        if (state.pollingInterval) {
            clearInterval(state.pollingInterval);
            state.pollingInterval = null;
        }
        
        // 清空状态
        state.tables = [];
        elements.processStatus.style.display = 'none';
        elements.knowledgeSection.style.display = 'none';
        elements.statusList.innerHTML = '';
        elements.tablesGrid.innerHTML = '';
        elements.consoleBody.innerHTML = '<div class="console-placeholder">等待处理...</div>';
        
    } catch (error) {
        console.error('清空失败:', error);
        alert('清空失败: ' + error.message);
    }
}

async function newSession() {
    if (!confirm('确定要开始新会话吗？当前会话的所有数据将保留，但不再显示。')) return;
    
    // 停止轮询
    if (state.pollingInterval) {
        clearInterval(state.pollingInterval);
        state.pollingInterval = null;
    }
    
    // 清除会话
    state.sessionId = null;
    state.tables = [];
    localStorage.removeItem('sessionId');
    
    // 清空界面
    elements.processStatus.style.display = 'none';
    elements.knowledgeSection.style.display = 'none';
    elements.statusList.innerHTML = '';
    elements.tablesGrid.innerHTML = '';
    elements.consoleBody.innerHTML = '<div class="console-placeholder">等待处理...</div>';
}

// 将函数暴露到全局作用域（供 HTML onclick 调用）
window.deleteFile = deleteFile;
window.cancelProcessing = cancelProcessing;
window.deleteTable = deleteTable;
window.clearAll = clearAll;
window.newSession = newSession;

async function loadKnowledgeBase() {
    if (!state.sessionId) return;
    
    try {
        const result = await apiCall(`/knowledge/${state.sessionId}`);
        state.tables = result.tables;
        
        if (result.tables.length > 0) {
            elements.knowledgeSection.style.display = 'block';
            renderTablesGrid(result.tables);
            // 更新对话侧边栏
            updateChatSidebar();
        }
    } catch (error) {
        console.error('加载知识库失败:', error);
    }
}

function renderTablesGrid(tables) {
    elements.tablesGrid.innerHTML = tables.map(table => {
        const description = table.table_description?.description || '数据表';
        const dimensions = table.columns.filter(c => c.is_dimension).slice(0, 3);
        const metrics = table.columns.filter(c => c.is_metric).slice(0, 3);
        
        return `
            <div class="table-card" data-table-id="${table.table_id}">
                <div class="table-card-header">
                    <span class="table-card-icon">📋</span>
                    <div class="table-card-title">
                        <h4>${table.table_name}</h4>
                        <span>${table.file_name}</span>
                    </div>
                </div>
                <div class="table-card-desc">${description}</div>
                <div class="table-card-stats">
                    <div class="stat-item">
                        <span class="stat-label">行数</span>
                        <span class="stat-value">${formatNumber(table.row_count)}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">列数</span>
                        <span class="stat-value">${table.column_count}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">大小</span>
                        <span class="stat-value">${table.statistics?.memory_usage_mb?.toFixed(1) || '-'} MB</span>
                    </div>
                </div>
                <div class="table-card-footer">
                    <div class="table-card-tags">
                        ${dimensions.map(c => `<span class="tag dimension">${c.name}</span>`).join('')}
                        ${metrics.map(c => `<span class="tag metric">${c.name}</span>`).join('')}
                    </div>
                    <button class="btn-icon danger table-delete-btn" onclick="event.stopPropagation(); deleteTable('${table.table_id}')" title="删除知识库">
                        🗑️
                    </button>
                </div>
            </div>
        `;
    }).join('');
    
    // 绑定点击事件
    document.querySelectorAll('.table-card').forEach(card => {
        card.addEventListener('click', (e) => {
            // 如果点击的是删除按钮，不触发详情
            if (e.target.closest('.table-delete-btn')) return;
            const tableId = card.dataset.tableId;
            showTableDetail(tableId);
        });
    });
}

function showTableDetail(tableId) {
    const table = state.tables.find(t => t.table_id === tableId);
    if (!table) return;
    
    state.currentTable = table;
    elements.modalTitle.textContent = `📋 ${table.table_name}`;
    
    // 渲染详情内容
    const desc = table.table_description || {};
    const suggestedAnalyses = desc.suggested_analyses || [];
    
    elements.modalBody.innerHTML = `
        <!-- 表描述 -->
        <div class="detail-section">
            <h4>📝 表描述</h4>
            <div class="detail-description">
                ${desc.description || '暂无描述'}
                ${suggestedAnalyses.length > 0 ? `
                    <p style="margin-top: 0.75rem; color: var(--text-secondary);">
                        <strong>建议分析：</strong>${suggestedAnalyses.join('、')}
                    </p>
                ` : ''}
            </div>
        </div>
        
        <!-- 字段列表 -->
        <div class="detail-section">
            <h4>📊 字段信息 (${table.columns.length} 个字段)</h4>
            <table class="columns-table">
                <thead>
                    <tr>
                        <th>字段名</th>
                        <th>类型</th>
                        <th>描述</th>
                        <th>空值率</th>
                        <th>样本值</th>
                    </tr>
                </thead>
                <tbody>
                    ${table.columns.map(col => `
                        <tr>
                            <td><strong>${col.name}</strong></td>
                            <td>
                                <span class="type-badge ${col.is_dimension ? 'dimension' : col.is_metric ? 'metric' : col.semantic_type === 'id' ? 'id' : ''}">
                                    ${col.semantic_type}
                                </span>
                            </td>
                            <td>${col.description || '-'}</td>
                            <td>${(col.null_ratio * 100).toFixed(1)}%</td>
                            <td>
                                <div class="sample-values">
                                    ${(col.sample_values || []).slice(0, 3).map(v => 
                                        `<span class="sample-value" title="${v}">${v}</span>`
                                    ).join('')}
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
        
        <!-- 样本数据 -->
        <div class="detail-section">
            <h4>📄 样本数据</h4>
            <table class="sample-data-table">
                <thead>
                    <tr>
                        ${table.columns.slice(0, 8).map(c => `<th>${c.name}</th>`).join('')}
                        ${table.columns.length > 8 ? '<th>...</th>' : ''}
                    </tr>
                </thead>
                <tbody>
                    ${(table.sample_data || []).map(row => `
                        <tr>
                            ${table.columns.slice(0, 8).map(c => 
                                `<td title="${row[c.name] ?? ''}">${row[c.name] ?? '-'}</td>`
                            ).join('')}
                            ${table.columns.length > 8 ? '<td>...</td>' : ''}
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
    
    elements.tableModal.classList.add('active');
}

function closeTableModal() {
    elements.tableModal.classList.remove('active');
    state.currentTable = null;
}

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}

// ============ 对话管理 ============
function addMessage(role, content, extra = null) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    // 处理内容中的 SQL 代码块
    let formattedContent = formatMessageContent(content);
    
    // 额外内容（如 SQL 结果、分析等）
    let extraHtml = '';
    if (extra) {
        if (extra.sql) {
            extraHtml += `
                <div class="message-sql">
                    <div class="sql-header">📊 执行的 SQL</div>
                    <pre><code>${escapeHtml(extra.sql)}</code></pre>
                </div>
            `;
        }
        if (extra.data) {
            extraHtml += renderQueryResult(extra.data);
        }
        if (extra.analysis) {
            extraHtml += `
                <div class="message-analysis">
                    <div class="analysis-header">💡 数据分析</div>
                    <div class="analysis-content">${formatMessageContent(extra.analysis)}</div>
                </div>
            `;
        }
        if (extra.error) {
            extraHtml += `
                <div class="message-error">
                    ❌ ${escapeHtml(extra.error)}
                </div>
            `;
        }
    }
    
    messageDiv.innerHTML = `
        <div class="message-avatar">${role === 'user' ? '👤' : '🤖'}</div>
        <div class="message-content">
            ${formattedContent}
            ${extraHtml}
        </div>
    `;
    
    // 移除欢迎消息
    const welcome = elements.chatMessages.querySelector('.welcome-message');
    if (welcome) welcome.remove();
    
    elements.chatMessages.appendChild(messageDiv);
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    
    state.messages.push({ role, content });
}

function formatMessageContent(content) {
    if (!content) return '';
    
    // 处理 SQL 代码块
    content = content.replace(/```sql\s*([\s\S]*?)```/gi, (match, sql) => {
        return `<pre class="code-block sql"><code>${escapeHtml(sql.trim())}</code></pre>`;
    });
    
    // 处理其他代码块
    content = content.replace(/```(\w*)\s*([\s\S]*?)```/gi, (match, lang, code) => {
        return `<pre class="code-block ${lang}"><code>${escapeHtml(code.trim())}</code></pre>`;
    });
    
    // 处理行内代码
    content = content.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    
    // 处理换行
    content = content.replace(/\n/g, '<br>');
    
    return content;
}

function renderQueryResult(data) {
    if (!data || !data.data || data.data.length === 0) {
        return '<div class="query-result empty">查询无结果</div>';
    }
    
    const columns = data.columns || Object.keys(data.data[0]);
    const rows = data.data.slice(0, 20); // 最多显示20行
    
    let html = `
        <div class="query-result">
            <div class="result-header">
                📋 查询结果 (${data.row_count} 行${data.truncated ? '，已截断' : ''})
            </div>
            <div class="result-table-container">
                <table class="result-table">
                    <thead>
                        <tr>
                            ${columns.map(col => `<th>${escapeHtml(String(col))}</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => `
                            <tr>
                                ${columns.map(col => {
                                    const val = row[col];
                                    const displayVal = val === null || val === undefined ? '-' : String(val);
                                    return `<td title="${escapeHtml(displayVal)}">${escapeHtml(displayVal.substring(0, 50))}</td>`;
                                }).join('')}
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            ${data.truncated ? `<div class="result-footer">显示前 ${rows.length} 行，共 ${data.total_count} 行</div>` : ''}
        </div>
    `;
    
    return html;
}

function escapeHtml(text) {
    if (typeof text !== 'string') text = String(text);
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function sendMessage() {
    const content = elements.chatInput.value.trim();
    if (!content || state.isLoading) return;
    
    // 检查是否有会话
    if (!state.sessionId) {
        addMessage('assistant', '请先在「数据」页面上传 CSV 文件，然后再开始对话。', {
            error: '未找到数据会话'
        });
        return;
    }
    
    // 添加用户消息
    addMessage('user', content);
    elements.chatInput.value = '';
    elements.chatInput.style.height = 'auto';
    
    // 发送请求
    state.isLoading = true;
    elements.sendBtn.disabled = true;
    elements.sendBtn.innerHTML = '<span class="loading"></span>';
    
    try {
        // 使用流式 API
        await sendMessageStream(content);
    } catch (error) {
        addMessage('assistant', `发生错误: ${error.message}`, {
            error: error.message
        });
    } finally {
        state.isLoading = false;
        elements.sendBtn.disabled = false;
        elements.sendBtn.innerHTML = '<span>发送</span>';
    }
}

async function sendMessageStream(content) {
    // 创建助手消息容器
    const messageDiv = createStreamingMessage();
    
    // 状态追踪
    const streamState = {
        thinking: '',
        content: '',
        sql: null,
        data: null,
        analysis: '',
        isThinking: false,
        isAnalyzing: false,
    };
    
    // 构建请求体
    const requestBody = {
        session_id: state.sessionId,
        message: content,
        history: state.messages.slice(-10).map(m => ({ role: m.role, content: m.content })),
        stream: true,
    };
    
    // 检查是否是 Clarification 回复
    if (state.pendingClarification) {
        console.log('[Clarification] 发送用户回复');
        console.log('  original_request:', state.pendingClarification.original_request?.substring(0, 50));
        console.log('  has messages_context:', !!state.pendingClarification.messages_context);
        console.log('  tool_call_id:', state.pendingClarification.tool_call_id);
        
        requestBody.clarification_response = content;
        requestBody.original_request = state.pendingClarification.original_request;
        requestBody.messages_context = state.pendingClarification.messages_context;  // 传递 LLM 对话上下文
        requestBody.tool_call_id = state.pendingClarification.tool_call_id;  // 传递 tool_call_id
        
        // 清除 pending 状态
        state.pendingClarification = null;
        // 恢复输入框提示
        updateInputPlaceholder();
    }
    
    const response = await fetch(`${API_BASE}/chat/data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
    });
    
    if (!response.ok) {
        throw new Error('请求失败');
    }
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        
        // SSE 格式：消息以 \n\n 分隔
        const messages = buffer.split('\n\n');
        // 最后一个可能不完整，保留到下次处理
        buffer = messages.pop() || '';
        
        for (const message of messages) {
            if (!message.trim()) continue;
            
            // 处理多行消息（SSE 可能有多个 data: 行）
            const lines = message.split('\n');
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                
                const data = line.slice(6);
                if (data === '[DONE]') continue;
                
                try {
                    const event = JSON.parse(data);
                    console.log('[SSE] 事件:', event.type, event.type === 'complete' ? '(报告完成!)' : '');
                    handleStreamEvent(event, messageDiv, streamState);
                } catch (e) {
                    console.error('[SSE] Parse error:', e, 'data:', data.substring(0, 200));
                }
            }
        }
    }
    
    // 最终更新消息状态
    state.messages.push({ role: 'assistant', content: streamState.content });
}

function createStreamingMessage() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    messageDiv.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-content">
            <div class="thinking-section" style="display: none;">
                <div class="thinking-header">
                    <span class="thinking-icon">💭</span>
                    <span>思考中...</span>
                    <button class="thinking-toggle" onclick="toggleThinking(this)">展开</button>
                </div>
                <div class="thinking-content" style="display: none;"></div>
            </div>
            <div class="content-section"></div>
            <div class="sql-section" style="display: none;"></div>
            <div class="data-section" style="display: none;"></div>
            <div class="analysis-section" style="display: none;"></div>
            <div class="error-section" style="display: none;"></div>
        </div>
    `;
    
    // 移除欢迎消息
    const welcome = elements.chatMessages.querySelector('.welcome-message');
    if (welcome) welcome.remove();
    
    elements.chatMessages.appendChild(messageDiv);
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    
    return messageDiv;
}

function handleStreamEvent(event, messageDiv, streamState) {
    const thinkingSection = messageDiv.querySelector('.thinking-section');
    const thinkingContent = messageDiv.querySelector('.thinking-content');
    const contentSection = messageDiv.querySelector('.content-section');
    const sqlSection = messageDiv.querySelector('.sql-section');
    const dataSection = messageDiv.querySelector('.data-section');
    const analysisSection = messageDiv.querySelector('.analysis-section');
    const errorSection = messageDiv.querySelector('.error-section');
    
    // 确保报告区域存在
    let reportSection = messageDiv.querySelector('.report-section');
    if (!reportSection) {
        reportSection = document.createElement('div');
        reportSection.className = 'report-section';
        reportSection.style.display = 'none';
        messageDiv.querySelector('.message-content').appendChild(reportSection);
    }
    
    switch (event.type) {
        // ========== Agent 事件 ==========
        case 'agent_event':
            handleAgentEvent(event, reportSection);
            break;
        
        // ========== 意图识别 ==========
        case 'intent':
            if (event.intent === 'report') {
                contentSection.innerHTML = `
                    <div class="intent-indicator report">
                        📊 ${event.message || '检测到报告生成需求，开始规划...'}
                    </div>
                `;
                // 初始化 Agent 监控面板
                initAgentMonitor(reportSection);
            }
            scrollToBottom();
            break;
        
        // ========== Clarification 处理 ==========
        case 'clarification':
            const rewrittenRequest = event.rewritten_request || '';
            const originalIntent = event.original_intent || '';
            const originalRequest = event.original_request || '';
            const messagesContext = event.messages_context || null;
            const toolCallId = event.tool_call_id || null;
            
            console.log('[Clarification] 收到需求改写');
            console.log('  rewritten_request:', rewrittenRequest?.substring(0, 100));
            console.log('  original_request:', originalRequest?.substring(0, 50));
            console.log('  has messages_context:', !!messagesContext);
            console.log('  tool_call_id:', toolCallId);
            
            // 保存 Clarification 状态（包含完整上下文）
            state.pendingClarification = {
                rewritten_request: rewrittenRequest,
                original_intent: originalIntent,
                original_request: originalRequest,
                messages_context: messagesContext,
                tool_call_id: toolCallId,
            };
            
            // 生成唯一ID用于文本框
            const clarificationId = `clarification-${Date.now()}`;
            
            contentSection.innerHTML = `
                <div class="clarification-box">
                    <div class="clarification-header">
                        ✨ 已为您优化分析请求
                    </div>
                    ${originalIntent ? `<p class="clarification-intent">📋 <strong>理解：</strong>${escapeHtml(originalIntent)}</p>` : ''}
                    <div class="clarification-editor-container">
                        <label class="clarification-label">请确认或修改以下分析请求：</label>
                        <textarea id="${clarificationId}" class="clarification-editor" rows="15">${escapeHtml(rewrittenRequest)}</textarea>
                    </div>
                    <div class="clarification-actions">
                        <button class="btn-secondary" onclick="cancelClarification()">取消</button>
                        <button class="btn-primary" onclick="confirmClarification('${clarificationId}')">✓ 确认并继续</button>
                    </div>
                </div>
            `;
            
            streamState.content = '[等待用户确认]';
            scrollToBottom();
            break;
        
        // ========== 报告生成事件 ==========
        case 'report_created':
            // 保存 report_id 用于监控
            state.currentReportId = event.report_id;
            
            reportSection.style.display = 'block';
            reportSection.innerHTML = `
                <div class="report-progress-inline">
                    <div class="progress-header">
                        <span class="progress-icon">📝</span>
                        <span class="progress-text">报告创建成功，开始生成...</span>
                        <span class="progress-spinner"></span>
                    </div>
                    <div class="progress-actions">
                        <button class="monitor-open-btn" onclick="openAgentMonitor()">
                            🖥️ 打开监控窗口
                        </button>
                    </div>
                    <div class="progress-log-inline"></div>
                    <div class="progress-hint">
                        💡 提示：报告生成需要 3-5 分钟，请耐心等待。正在调用多个 AI Agent 进行深度分析...
                    </div>
                </div>
            `;
            scrollToBottom();
            break;
        
        case 'status':
            const logContainer = reportSection.querySelector('.progress-log-inline');
            if (logContainer) {
                const logItem = document.createElement('div');
                logItem.className = 'log-item';
                logItem.innerHTML = `⏳ ${escapeHtml(event.message)}`;
                logContainer.appendChild(logItem);
            }
            // 更新状态文字
            const progressText = reportSection.querySelector('.progress-text');
            if (progressText) {
                progressText.textContent = event.message;
            }
            scrollToBottom();
            break;
        
        case 'outline':
            const outlineLog = reportSection.querySelector('.progress-log-inline');
            if (outlineLog) {
                const logItem = document.createElement('div');
                logItem.className = 'log-item success';
                const sectionCount = event.data?.sections?.length || 0;
                logItem.innerHTML = `✅ 大纲生成完成，共 ${sectionCount} 个章节`;
                outlineLog.appendChild(logItem);
            }
            scrollToBottom();
            break;
        
        case 'section_start':
            const sectionStartLog = reportSection.querySelector('.progress-log-inline');
            if (sectionStartLog) {
                const logItem = document.createElement('div');
                logItem.className = 'log-item';
                logItem.innerHTML = `🔄 正在研究: ${escapeHtml(event.title || '')} (${event.index + 1}/${event.total})`;
                sectionStartLog.appendChild(logItem);
            }
            scrollToBottom();
            break;
        
        case 'heartbeat':
            // 心跳事件 - 更新进度提示
            const hintDiv = reportSection.querySelector('.progress-hint');
            if (hintDiv) {
                hintDiv.innerHTML = `💓 ${escapeHtml(event.message || '处理中...')}`;
            }
            // 更新状态文字
            const progressTextHb = reportSection.querySelector('.progress-text');
            if (progressTextHb) {
                progressTextHb.textContent = `已完成 ${event.completed}/${event.total} 章节`;
            }
            break;
        
        case 'section_complete':
            const sectionLog = reportSection.querySelector('.progress-log-inline');
            if (sectionLog) {
                const logItem = document.createElement('div');
                logItem.className = 'log-item success';
                logItem.innerHTML = `✅ 章节完成: ${escapeHtml(event.section?.name || '')} (${event.index + 1}/${event.total})`;
                sectionLog.appendChild(logItem);
            }
            scrollToBottom();
            break;
        
        case 'complete':
            // 报告生成完成，保存报告并显示查看按钮
            console.log('[Report] 收到 complete 事件');
            console.log('[Report] event:', JSON.stringify(event).substring(0, 500));
            
            const report = event.report;
            if (!report) {
                console.error('[Report] 错误: event.report 为空!');
                reportSection.style.display = 'block';
                reportSection.innerHTML = `
                    <div class="report-error">
                        <p>❌ 报告数据为空</p>
                    </div>
                `;
                break;
            }
            
            console.log('[Report] 报告:', report.title, report.report_id);
            state.currentReport = report;
            
            // 保存报告到本地存储
            try {
                saveReportToStorage(report);
                console.log('[Report] 保存成功');
            } catch (e) {
                console.error('[Report] 保存失败:', e);
            }
            
            // 显示报告区域
            reportSection.style.display = 'block';
            
            // 显示完成消息和查看按钮
            const reportTitle = report.title || '数据分析报告';
            const reportSummary = report.summary || '';
            const sectionCount = report.sections?.length || 0;
            const createdAt = report.created_at ? new Date(report.created_at).toLocaleString('zh-CN') : '未知时间';
            const reportId = report.report_id || '';
            
            reportSection.innerHTML = `
                <div class="report-complete-card">
                    <div class="report-complete-icon">🎉</div>
                    <div class="report-complete-info">
                        <h3 class="report-complete-title">${escapeHtml(reportTitle)}</h3>
                        <p class="report-complete-summary">${escapeHtml(reportSummary.substring(0, 150))}${reportSummary.length > 150 ? '...' : ''}</p>
                        <div class="report-complete-meta">
                            <span>📊 ${sectionCount} 个章节</span>
                            <span>⏰ ${createdAt}</span>
                        </div>
                    </div>
                    <div class="report-complete-actions">
                        <button class="btn-view-report" onclick="viewReport('${escapeHtml(reportId)}')">
                            📖 查看完整报告
                        </button>
                    </div>
                </div>
            `;
            console.log('[Report] UI 渲染完成');
            scrollToBottom();
            break;
        
        // ========== 原有的对话事件 ==========
        case 'thinking_start':
            streamState.isThinking = true;
            thinkingSection.style.display = 'block';
            break;
            
        case 'thinking':
            streamState.thinking += event.content;
            thinkingContent.innerHTML = formatMessageContent(streamState.thinking);
            scrollToBottom();
            break;
            
        case 'thinking_end':
            streamState.isThinking = false;
            thinkingSection.querySelector('.thinking-header span:nth-child(2)').textContent = '思考完成';
            break;
            
        case 'content':
            streamState.content += event.content;
            contentSection.innerHTML = formatMessageContent(streamState.content);
            scrollToBottom();
            break;
            
        case 'sql':
            streamState.sql = event.sql;
            sqlSection.style.display = 'block';
            sqlSection.innerHTML = `
                <div class="message-sql">
                    <div class="sql-header">📊 执行的 SQL</div>
                    <pre><code>${escapeHtml(event.sql)}</code></pre>
                </div>
            `;
            scrollToBottom();
            break;
            
        case 'sql_executing':
            const sqlHeader = sqlSection.querySelector('.sql-header');
            if (sqlHeader) {
                sqlHeader.innerHTML = '📊 执行的 SQL <span class="loading-inline"></span>';
            }
            break;
            
        case 'data':
            streamState.data = event.data;
            dataSection.style.display = 'block';
            dataSection.innerHTML = renderQueryResult(event.data);
            const sqlHeaderDone = sqlSection.querySelector('.sql-header');
            if (sqlHeaderDone) {
                sqlHeaderDone.innerHTML = '📊 执行的 SQL ✅';
            }
            scrollToBottom();
            break;
            
        case 'analysis_start':
            streamState.isAnalyzing = true;
            analysisSection.style.display = 'block';
            analysisSection.innerHTML = `
                <div class="message-analysis">
                    <div class="analysis-header">💡 数据分析 <span class="loading-inline"></span></div>
                    <div class="analysis-content"></div>
                </div>
            `;
            scrollToBottom();
            break;
            
        case 'analysis':
            streamState.analysis += event.content;
            const analysisContent = analysisSection.querySelector('.analysis-content');
            if (analysisContent) {
                analysisContent.innerHTML = formatMessageContent(streamState.analysis);
            }
            scrollToBottom();
            break;
            
        case 'analysis_end':
            streamState.isAnalyzing = false;
            const analysisHeader = analysisSection.querySelector('.analysis-header');
            if (analysisHeader) {
                analysisHeader.innerHTML = '💡 数据分析';
            }
            break;
            
        case 'error':
            errorSection.style.display = 'block';
            errorSection.innerHTML = `<div class="message-error">❌ ${escapeHtml(event.error || event.message || '未知错误')}</div>`;
            scrollToBottom();
            break;
            
        case 'done':
            // 完成
            break;
    }
}

/**
 * 在对话中渲染报告
 */
function renderReportInChat(report) {
    if (!report) return '<p>报告生成失败</p>';
    
    let html = `
        <div class="report-in-chat">
            <div class="report-header-inline">
                <h3>📊 ${escapeHtml(report.title || '数据分析报告')}</h3>
                <p class="report-summary-inline">${escapeHtml(report.summary || '')}</p>
            </div>
            <div class="report-sections-inline">
    `;
    
    for (const section of report.sections || []) {
        html += renderSection(section);
    }
    
    html += `
            </div>
            <div class="report-actions-inline">
                <button class="btn btn-sm" onclick="exportCurrentReport()">📥 导出报告</button>
            </div>
        </div>
    `;
    
    return html;
}

// 导出当前报告
window.exportCurrentReport = function() {
    if (state.currentReport) {
        exportReport();
    }
};

function toggleThinking(btn) {
    const thinkingSection = btn.closest('.thinking-section');
    const thinkingContent = thinkingSection.querySelector('.thinking-content');
    const isVisible = thinkingContent.style.display !== 'none';
    
    thinkingContent.style.display = isVisible ? 'none' : 'block';
    btn.textContent = isVisible ? '展开' : '收起';
}

function scrollToBottom() {
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

/**
 * 更新输入框提示文字
 */
function updateInputPlaceholder() {
    if (!elements.chatInput) return;
    
    if (state.pendingClarification) {
        elements.chatInput.placeholder = '💬 请回复上述问题，以便继续生成报告...';
        elements.chatInput.classList.add('clarification-mode');
        
        // 添加提示条
        let hint = document.querySelector('.clarification-mode-hint');
        if (!hint) {
            hint = document.createElement('div');
            hint.className = 'clarification-mode-hint';
            hint.innerHTML = '📋 正在等待您的回复以继续报告生成...';
            elements.chatInput.parentElement.insertBefore(hint, elements.chatInput);
        }
    } else {
        elements.chatInput.placeholder = '输入您的问题，按 Enter 发送...';
        elements.chatInput.classList.remove('clarification-mode');
        
        // 移除提示条
        const hint = document.querySelector('.clarification-mode-hint');
        if (hint) hint.remove();
    }
}

/**
 * 确认 Clarification 改写内容
 */
async function confirmClarification(textareaId) {
    const textarea = document.getElementById(textareaId);
    if (!textarea || !state.pendingClarification) return;
    
    const confirmedContent = textarea.value.trim();
    if (!confirmedContent) {
        alert('请输入分析请求内容');
        return;
    }
    
    console.log('[Clarification] 用户确认改写内容');
    
    // 添加用户确认消息到聊天
    addMessage('user', '✓ 确认分析请求');
    
    // 发送确认的内容
    const requestBody = {
        session_id: state.sessionId,
        message: confirmedContent,
        clarification_response: confirmedContent,
        original_request: state.pendingClarification.original_request,
        messages_context: state.pendingClarification.messages_context,
        tool_call_id: state.pendingClarification.tool_call_id,
        stream: true,
    };
    
    // 清除 pending 状态
    state.pendingClarification = null;
    
    // 发送请求
    state.isLoading = true;
    
    try {
        const messageDiv = createStreamingMessage();
        const streamState = {
            thinking: '',
            content: '',
            sql: null,
            data: null,
            analysis: '',
            isThinking: false,
            isAnalyzing: false,
        };
        
        const response = await fetch(`${API_BASE}/chat/data`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
        });
        
        if (!response.ok) throw new Error('请求失败');
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            
            // SSE 格式：消息以 \n\n 分隔
            const messages = buffer.split('\n\n');
            buffer = messages.pop() || '';
            
            for (const message of messages) {
                if (!message.trim()) continue;
                
                const lines = message.split('\n');
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    
                    const data = line.slice(6);
                    if (data === '[DONE]') continue;
                    
                    try {
                        const event = JSON.parse(data);
                        console.log('[SSE-2] 事件:', event.type, event.type === 'complete' ? '(报告完成!)' : '');
                        handleStreamEvent(event, messageDiv, streamState);
                    } catch (e) {
                        console.error('[SSE-2] 解析事件失败:', e, 'data:', data.substring(0, 200));
                    }
                }
            }
        }
        
        // 保存最终消息
        if (streamState.content) {
            state.messages.push({ role: 'assistant', content: streamState.content });
        }
        
    } catch (error) {
        console.error('确认失败:', error);
        addMessage('assistant', `❌ 确认失败: ${error.message}`);
    } finally {
        state.isLoading = false;
    }
}

/**
 * 取消 Clarification
 */
function cancelClarification() {
    state.pendingClarification = null;
    addMessage('assistant', '已取消报告生成。您可以重新提出问题。');
}

/**
 * 保存报告到本地存储
 */
function saveReportToStorage(report) {
    try {
        console.log('[Report] 准备保存报告:', report.report_id, report.title);
        const reports = JSON.parse(localStorage.getItem('reports') || '{}');
        reports[report.report_id] = report;
        localStorage.setItem('reports', JSON.stringify(reports));
        console.log('[Report] 保存成功，当前报告数量:', Object.keys(reports).length);
        console.log('[Report] 报告 IDs:', Object.keys(reports));
    } catch (e) {
        console.error('保存报告失败:', e);
    }
}

/**
 * 从本地存储获取报告
 */
function getReportFromStorage(reportId) {
    try {
        const reports = JSON.parse(localStorage.getItem('reports') || '{}');
        return reports[reportId] || null;
    } catch (e) {
        console.error('获取报告失败:', e);
        return null;
    }
}

/**
 * 查看报告（打开报告页面）
 */
function viewReport(reportId) {
    // 将报告ID存入 sessionStorage 供报告页面读取
    sessionStorage.setItem('currentReportId', reportId);
    // 打开报告页面
    window.open('report.html', '_blank');
}

// 暴露到全局
window.toggleThinking = toggleThinking;
window.confirmClarification = confirmClarification;
window.cancelClarification = cancelClarification;
window.viewReport = viewReport;

async function loadSuggestedQuestions() {
    if (!state.sessionId || state.tables.length === 0) return;
    
    try {
        const result = await apiCall(`/chat/suggest/${state.sessionId}?limit=5`);
        renderSuggestedQuestions(result.questions);
    } catch (error) {
        console.error('加载推荐问题失败:', error);
    }
}

function renderSuggestedQuestions(questions) {
    if (!questions || questions.length === 0) return;
    
    const container = elements.suggestedQuestions;
    if (!container) return;
    
    // 隐藏提示，显示推荐问题
    if (elements.welcomeHint) {
        elements.welcomeHint.style.display = 'none';
    }
    
    container.style.display = 'block';
    container.innerHTML = `
        <p>💡 您可以试着问我：</p>
        <div class="question-list">
            ${questions.map(q => `
                <button class="suggested-question" onclick="askQuestion('${escapeHtml(q).replace(/'/g, "\\'")}')">
                    ${escapeHtml(q)}
                </button>
            `).join('')}
        </div>
    `;
}

function askQuestion(question) {
    elements.chatInput.value = question;
    sendMessage();
}

function updateChatSidebar() {
    if (!elements.sidebarContent) return;
    
    if (state.tables.length === 0) {
        elements.sidebarContent.innerHTML = `
            <div class="no-data-hint">
                <p>暂无数据</p>
                <p class="hint">请先在「数据」页面上传文件</p>
            </div>
        `;
        return;
    }
    
    elements.sidebarContent.innerHTML = state.tables.map(table => {
        const desc = table.table_description?.description || '数据表';
        const dims = table.columns.filter(c => c.is_dimension).length;
        const metrics = table.columns.filter(c => c.is_metric).length;
        
        return `
            <div class="sidebar-table-item" onclick="showTableDetail('${table.table_id}')">
                <div class="sidebar-table-name">📋 ${table.table_name}</div>
                <div class="sidebar-table-info">
                    ${formatNumber(table.row_count)} 行 · ${table.column_count} 列
                </div>
                <div class="sidebar-table-info">
                    维度 ${dims} · 指标 ${metrics}
                </div>
            </div>
        `;
    }).join('');
}

function toggleSidebar() {
    if (!elements.chatSidebar) return;
    
    const isCollapsed = elements.chatSidebar.classList.toggle('collapsed');
    if (elements.toggleSidebar) {
        elements.toggleSidebar.textContent = isCollapsed ? '▶' : '◀';
    }
}

function updateModelIndicator() {
    if (!elements.modelIndicator || !state.config) return;
    
    const model = state.config.default?.model || 'unknown';
    elements.modelIndicator.textContent = `模型: ${model}`;
}

// 暴露到全局
window.askQuestion = askQuestion;
window.toggleSidebar = toggleSidebar;
window.showTableDetail = showTableDetail;

// ============ 事件绑定 ============
function bindEvents() {
    // 导航切换
    elements.navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            
            elements.navBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            elements.tabContents.forEach(content => {
                content.classList.remove('active');
                if (content.id === `tab-${tab}`) {
                    content.classList.add('active');
                }
            });
        });
    });
    
    // 文件上传
    elements.selectFilesBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        elements.fileInput.click();
    });
    
    elements.uploadArea.addEventListener('click', () => {
        elements.fileInput.click();
    });
    
    elements.fileInput.addEventListener('change', (e) => {
        uploadFiles(e.target.files);
        e.target.value = ''; // 清空以便再次选择同样的文件
    });
    
    // 拖拽上传
    elements.uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        elements.uploadArea.classList.add('dragover');
    });
    
    elements.uploadArea.addEventListener('dragleave', () => {
        elements.uploadArea.classList.remove('dragover');
    });
    
    elements.uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        elements.uploadArea.classList.remove('dragover');
        uploadFiles(e.dataTransfer.files);
    });
    
    // 模态框
    elements.closeModal.addEventListener('click', closeTableModal);
    
    // 控制台面板
    elements.toggleConsole.addEventListener('click', toggleConsolePanel);
    elements.closeConsole.addEventListener('click', () => {
        elements.consolePanel.style.display = 'none';
        elements.toggleConsole.textContent = '📋 控制台';
    });
    
    // 清空全部
    elements.clearAllBtn.addEventListener('click', clearAll);
    elements.tableModal.addEventListener('click', (e) => {
        if (e.target === elements.tableModal) {
            closeTableModal();
        }
    });
    
    // API Key 显示/隐藏
    elements.toggleApiKey.addEventListener('click', () => {
        const type = elements.apiKey.type === 'password' ? 'text' : 'password';
        elements.apiKey.type = type;
        elements.toggleApiKey.textContent = type === 'password' ? '👁' : '🙈';
    });
    
    // Temperature 滑块
    elements.temperature.addEventListener('input', () => {
        elements.temperatureValue.textContent = elements.temperature.value;
    });
    
    // 配置操作
    elements.testConnection.addEventListener('click', testConnection);
    elements.saveConfig.addEventListener('click', saveConfig);
    elements.resetConfig.addEventListener('click', resetConfig);
    
    // 对话
    elements.sendBtn.addEventListener('click', sendMessage);
    elements.chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // 自动调整输入框高度
    elements.chatInput.addEventListener('input', () => {
        elements.chatInput.style.height = 'auto';
        elements.chatInput.style.height = Math.min(elements.chatInput.scrollHeight, 150) + 'px';
    });
    
    // ESC 关闭模态框
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && elements.tableModal.classList.contains('active')) {
            closeTableModal();
        }
    });
}

// ============ 初始化 ============
async function init() {
    bindEvents();
    await loadConfig();
    updateModelIndicator();
    
    // 如果有会话ID，尝试加载知识库
    if (state.sessionId) {
        try {
            await loadKnowledgeBase();
            // 如果有表，显示知识库区域
            if (state.tables.length > 0) {
                elements.knowledgeSection.style.display = 'block';
                // 更新侧边栏
                updateChatSidebar();
                // 加载推荐问题
                await loadSuggestedQuestions();
            }
        } catch (error) {
            console.log('加载会话失败，可能是新会话');
            state.sessionId = null;
            localStorage.removeItem('sessionId');
        }
    }
}

// 侧边栏切换事件
if (elements.toggleSidebar) {
    elements.toggleSidebar.addEventListener('click', toggleSidebar);
}

// ============ 报告功能 ============

// 报告事件绑定
if (elements.generateReportBtn) {
    elements.generateReportBtn.addEventListener('click', generateReport);
}
if (elements.closeReportBtn) {
    elements.closeReportBtn.addEventListener('click', closeReportPreview);
}
if (elements.exportReportBtn) {
    elements.exportReportBtn.addEventListener('click', exportReport);
}

async function generateReport() {
    const request = elements.reportRequest?.value?.trim();
    if (!request) {
        alert('请输入报告需求描述');
        return;
    }
    
    if (!state.sessionId || state.tables.length === 0) {
        alert('请先在「数据」页面上传数据');
        return;
    }
    
    state.isGeneratingReport = true;
    elements.generateReportBtn.disabled = true;
    elements.generateReportBtn.innerHTML = '<span class="btn-icon">⏳</span> 生成中...';
    
    // 显示进度
    elements.reportProgress.style.display = 'block';
    elements.reportPreview.style.display = 'none';
    elements.progressLog.innerHTML = '';
    elements.reportProgressBar.style.width = '0%';
    
    try {
        const response = await fetch(`${API_BASE}/report/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: state.sessionId,
                request: request,
                stream: true,
            }),
        });
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let sectionCount = 0;
        let totalSections = 1;
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6);
                if (data === '[DONE]') continue;
                
                try {
                    const chunk = JSON.parse(data);
                    handleReportChunk(chunk, { sectionCount, totalSections });
                    
                    if (chunk.type === 'outline') {
                        totalSections = chunk.data?.sections?.length || 1;
                    }
                    if (chunk.type === 'section_complete') {
                        sectionCount++;
                        const progress = Math.round((sectionCount / totalSections) * 100);
                        elements.reportProgressBar.style.width = `${progress}%`;
                    }
                } catch (e) {
                    console.error('解析报告 chunk 失败:', e);
                }
            }
        }
        
    } catch (error) {
        console.error('生成报告失败:', error);
        addProgressLog('❌ 生成失败: ' + error.message, 'error');
    } finally {
        state.isGeneratingReport = false;
        elements.generateReportBtn.disabled = false;
        elements.generateReportBtn.innerHTML = '<span class="btn-icon">✨</span> 生成报告';
    }
}

function handleReportChunk(chunk, context) {
    const type = chunk.type;
    
    switch (type) {
        case 'status':
            elements.progressStatus.textContent = chunk.message;
            addProgressLog('📝 ' + chunk.message);
            break;
            
        case 'report_created':
            addProgressLog('✅ 报告创建成功');
            break;
            
        case 'outline':
            addProgressLog('📋 大纲生成完成，共 ' + (chunk.data?.sections?.length || 0) + ' 个章节');
            break;
            
        case 'section_start':
            addProgressLog(`📝 正在生成: ${chunk.title} (${chunk.index + 1}/${chunk.total})`);
            break;
            
        case 'sql_executed':
            addProgressLog(`🔍 SQL 执行完成，${chunk.row_count} 条记录`);
            break;
            
        case 'section_complete':
            addProgressLog(`✅ 章节完成: ${chunk.section?.title}`);
            break;
            
        case 'complete':
            addProgressLog('🎉 报告生成完成！', 'success');
            state.currentReport = chunk.report;
            renderReportPreview(chunk.report);
            loadReportHistory();
            break;
            
        case 'error':
            addProgressLog('❌ 错误: ' + chunk.message, 'error');
            break;
    }
}

function addProgressLog(message, type = '') {
    const item = document.createElement('div');
    item.className = `progress-log-item ${type}`;
    item.textContent = message;
    elements.progressLog.appendChild(item);
    elements.progressLog.scrollTop = elements.progressLog.scrollHeight;
}

function renderReportPreview(report) {
    elements.reportProgress.style.display = 'none';
    elements.reportPreview.style.display = 'block';
    
    elements.reportTitle.textContent = report.title || '数据分析报告';
    elements.reportSummary.textContent = report.summary || '';
    
    let sectionsHtml = '';
    
    for (const section of report.sections || []) {
        sectionsHtml += renderSection(section);
    }
    
    elements.reportContent.innerHTML = sectionsHtml;
}

/**
 * 渲染单个章节（新的 Section/Discovery 结构）
 */
function renderSection(section) {
    let html = `
        <div class="report-section" id="section-${section.section_id || ''}">
            <h2 class="section-title">${escapeHtml(section.name || '')}</h2>
            <div class="section-discoveries">
    `;
    
    // 渲染每个 discovery
    for (const disc of section.discoveries || []) {
        html += renderDiscovery(disc);
    }
    
    // 渲染结论
    if (section.conclusion) {
        html += `
            <div class="section-conclusion">
                <h3>📋 结论与建议</h3>
                <div class="conclusion-content">
                    ${renderMarkdownEnhanced(section.conclusion)}
                </div>
            </div>
        `;
    }
    
    html += `
            </div>
        </div>
    `;
    
    return html;
}

/**
 * 渲染单个发现（Discovery）
 */
function renderDiscovery(discovery) {
    // 渲染 insight，替换图表占位符
    let insightHtml = renderMarkdownEnhanced(discovery.insight || '');
    
    // 替换 {{CHART:chart_id}} 占位符为图表容器
    for (const chart of discovery.charts || []) {
        const placeholder = `{{CHART:${chart.chart_id}}}`;
        const chartHtml = renderChartEnhanced(chart);
        insightHtml = insightHtml.replace(placeholder, chartHtml);
        // 也尝试 HTML 转义版本
        insightHtml = insightHtml.replace(
            escapeHtml(placeholder), 
            chartHtml
        );
    }
    
    // 如果有未被替换的图表，追加到末尾
    let remainingCharts = '';
    for (const chart of discovery.charts || []) {
        if (!insightHtml.includes(`id="chart-${chart.chart_id}"`)) {
            remainingCharts += renderChartEnhanced(chart);
        }
    }
    
    return `
        <div class="discovery" id="${discovery.discovery_id || ''}">
            <h3 class="discovery-title">${escapeHtml(discovery.title || '')}</h3>
            <div class="discovery-insight">
                ${insightHtml}
                ${remainingCharts}
            </div>
            ${discovery.data_interpretation ? `
                <p class="discovery-interpretation">
                    💡 ${escapeHtml(discovery.data_interpretation)}
                </p>
            ` : ''}
        </div>
    `;
}

/**
 * 增强版 Markdown 渲染
 */
function renderMarkdownEnhanced(text) {
    if (!text) return '';
    
    // 先彻底清理 HTML 和 URL
    let html = cleanHtmlAndUrls(text);
    
    // 表格处理（改进版）
    html = html.replace(/\n\|(.+)\|\n\|[-:\s|]+\|\n((?:\|.+\|\n?)+)/g, (match, header, body) => {
        const headers = header.split('|').filter(h => h.trim());
        const rows = body.trim().split('\n').map(row => 
            row.split('|').filter(c => c !== '').map(c => c.trim())
        );
        
        return `
            <table class="md-table">
                <thead>
                    <tr>${headers.map(h => `<th>${h.trim()}</th>`).join('')}</tr>
                </thead>
                <tbody>
                    ${rows.map(row => 
                        `<tr>${row.map(c => `<td>${c}</td>`).join('')}</tr>`
                    ).join('')}
                </tbody>
            </table>
        `;
    });
    
    // 标题
    html = html.replace(/^### (.*$)/gm, '<h4 class="md-h4">$1</h4>');
    html = html.replace(/^## (.*$)/gm, '<h3 class="md-h3">$1</h3>');
    html = html.replace(/^# (.*$)/gm, '<h2 class="md-h2">$1</h2>');
    
    // 粗体和斜体
    html = html.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    
    // 列表
    html = html.replace(/^\s*- (.*$)/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`);
    
    // 数字列表
    html = html.replace(/^\s*\d+\. (.*$)/gm, '<li>$1</li>');
    
    // 代码块
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre class="code-block ${lang}"><code>${escapeHtml(code.trim())}</code></pre>`;
    });
    
    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    
    // 段落（简化处理）
    html = html.replace(/\n\n/g, '</p><p>');
    
    // 换行
    html = html.replace(/\n/g, '<br>');
    
    // 包装
    if (!html.startsWith('<')) {
        html = '<p>' + html + '</p>';
    }
    
    // 清理
    html = html.replace(/<p><\/p>/g, '');
    html = html.replace(/<p>(<[hupolt])/gi, '$1');
    html = html.replace(/(<\/[hupolt].*?>)<\/p>/gi, '$1');
    html = html.replace(/<br><br>/g, '</p><p>');
    
    return html;
}

/**
 * 增强版图表渲染
 */
function renderChartEnhanced(chart) {
    if (chart.error) {
        return `
            <div class="chart-container chart-error-container">
                <div class="chart-error-message">
                    ⚠️ 图表生成失败: ${escapeHtml(chart.error)}
                </div>
                ${chart.purpose ? `<p class="chart-purpose">目的: ${escapeHtml(chart.purpose)}</p>` : ''}
            </div>
        `;
    }
    
    const data = chart.rendered_data || [];
    if (data.length === 0) {
        return `
            <div class="chart-container">
                <div class="chart-title">${escapeHtml(chart.title || '图表')}</div>
                <p class="no-data">暂无数据</p>
            </div>
        `;
    }
    
    const chartType = chart.chart_type || 'bar';
    const title = chart.title || chart.purpose || '图表';
    
    return `
        <div class="chart-container" id="chart-${chart.chart_id}">
            <div class="chart-title">${escapeHtml(title)}</div>
            <div class="chart-body">
                ${renderChartByTypeEnhanced(chartType, chart, data)}
            </div>
        </div>
    `;
}

function renderChartByTypeEnhanced(type, config, data) {
    const dataSources = config.data_sources || [];
    
    if (dataSources.length === 0) {
        // 尝试自动推断
        return renderAutoChart(data);
    }
    
    const ds = dataSources[0];
    const xAxis = ds.x_axis;
    const yAxis = ds.y_axis || [];
    
    if (!xAxis || yAxis.length === 0) {
        return renderAutoChart(data);
    }
    
    switch (type) {
        case 'pie':
            return renderPieChartEnhanced(data, xAxis, yAxis[0]);
        case 'line':
            return renderLineChart(data, xAxis, yAxis);
        case 'dual_axis_mixed':
            return renderDualAxisChart(config, data);
        case 'bar':
        default:
            return renderBarChartEnhanced(data, xAxis, yAxis);
    }
}

function renderAutoChart(data) {
    if (data.length === 0) return '<p class="no-data">暂无数据</p>';
    
    // 自动检测字段
    const sample = data[0];
    const fields = Object.keys(sample);
    
    let labelField = null;
    let valueField = null;
    
    for (const field of fields) {
        const value = sample[field];
        if (typeof value === 'number' || !isNaN(parseFloat(value))) {
            if (!valueField) valueField = field;
        } else {
            if (!labelField) labelField = field;
        }
    }
    
    if (!labelField) labelField = fields[0];
    if (!valueField) valueField = fields[1] || fields[0];
    
    return renderBarChartEnhanced(data, labelField, [valueField]);
}

function renderBarChartEnhanced(data, xAxis, yAxis) {
    const yField = yAxis[0];
    const maxValue = Math.max(...data.map(d => parseFloat(d[yField]) || 0), 1);
    const displayData = data.slice(0, 12);
    
    return `
        <div class="simple-bar-chart">
            ${displayData.map(d => {
                const label = String(d[xAxis] || '').slice(0, 25);
                const value = parseFloat(d[yField]) || 0;
                const percent = (value / maxValue * 100).toFixed(1);
                
                return `
                    <div class="bar-item">
                        <div class="bar-label" title="${escapeHtml(String(d[xAxis]))}">${escapeHtml(label)}</div>
                        <div class="bar-track">
                            <div class="bar-fill" style="width: ${percent}%"></div>
                            <span class="bar-value">${formatNumber(value)}</span>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
        ${data.length > 12 ? `<p class="chart-more">显示前 12 条，共 ${data.length} 条</p>` : ''}
    `;
}

function renderPieChartEnhanced(data, labelField, valueField) {
    const displayData = data.slice(0, 8);
    const total = displayData.reduce((sum, d) => sum + (parseFloat(d[valueField]) || 0), 0);
    const colors = ['#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6'];
    
    let cumulativePercent = 0;
    const segments = displayData.map((d, i) => {
        const value = parseFloat(d[valueField]) || 0;
        const percent = total > 0 ? (value / total) * 100 : 0;
        const start = cumulativePercent;
        cumulativePercent += percent;
        return {
            label: d[labelField],
            value,
            percent,
            start,
            end: cumulativePercent,
            color: colors[i % colors.length],
        };
    });
    
    const gradientParts = segments.map(s => `${s.color} ${s.start}% ${s.end}%`).join(', ');
    
    return `
        <div class="simple-pie-chart">
            <div class="pie-visual" style="background: conic-gradient(${gradientParts})"></div>
            <div class="pie-legend">
                ${segments.map(s => `
                    <div class="legend-item">
                        <div class="legend-color" style="background: ${s.color}"></div>
                        <span class="legend-label">${escapeHtml(String(s.label))}</span>
                        <span class="legend-value">${formatNumber(s.value)} (${s.percent.toFixed(1)}%)</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function renderLineChart(data, xAxis, yAxis) {
    // 简化的折线图（使用柱状图样式但更细）
    const yField = yAxis[0];
    const maxValue = Math.max(...data.map(d => parseFloat(d[yField]) || 0), 1);
    const displayData = data.slice(0, 15);
    
    return `
        <div class="simple-line-chart">
            <div class="line-chart-area">
                ${displayData.map((d, i) => {
                    const value = parseFloat(d[yField]) || 0;
                    const height = (value / maxValue * 100).toFixed(1);
                    const label = String(d[xAxis] || '').slice(0, 10);
                    
                    return `
                        <div class="line-point" style="height: ${height}%;" title="${escapeHtml(label)}: ${formatNumber(value)}">
                            <span class="point-dot"></span>
                        </div>
                    `;
                }).join('')}
            </div>
            <div class="line-x-axis">
                ${displayData.map(d => `
                    <span class="x-label">${escapeHtml(String(d[xAxis] || '').slice(0, 6))}</span>
                `).join('')}
            </div>
        </div>
    `;
}

function renderDualAxisChart(config, data) {
    // 双轴图表简化为柱状图+数值显示
    const dataSources = config.data_sources || [];
    if (dataSources.length < 2) {
        return renderAutoChart(data);
    }
    
    const primary = dataSources.find(ds => ds.axis === 'primary') || dataSources[0];
    const secondary = dataSources.find(ds => ds.axis === 'secondary') || dataSources[1];
    
    const xAxis = primary.x_axis;
    const primaryY = primary.y_axis?.[0];
    const secondaryY = secondary.y_axis?.[0];
    
    if (!xAxis || !primaryY) {
        return renderAutoChart(data);
    }
    
    const displayData = data.slice(0, 10);
    const maxPrimary = Math.max(...displayData.map(d => parseFloat(d[primaryY]) || 0), 1);
    
    return `
        <div class="dual-axis-chart">
            <div class="dual-legend">
                <span class="legend-primary">■ ${escapeHtml(primaryY)}</span>
                ${secondaryY ? `<span class="legend-secondary">● ${escapeHtml(secondaryY)}</span>` : ''}
            </div>
            <div class="simple-bar-chart">
                ${displayData.map(d => {
                    const label = String(d[xAxis] || '').slice(0, 20);
                    const primaryVal = parseFloat(d[primaryY]) || 0;
                    const secondaryVal = secondaryY ? (parseFloat(d[secondaryY]) || 0) : null;
                    const percent = (primaryVal / maxPrimary * 100).toFixed(1);
                    
                    return `
                        <div class="bar-item dual">
                            <div class="bar-label" title="${escapeHtml(String(d[xAxis]))}">${escapeHtml(label)}</div>
                            <div class="bar-track">
                                <div class="bar-fill" style="width: ${percent}%"></div>
                                <span class="bar-value">${formatNumber(primaryVal)}</span>
                                ${secondaryVal !== null ? `<span class="bar-secondary">${formatNumber(secondaryVal)}</span>` : ''}
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
        </div>
    `;
}

/**
 * 修复 Markdown 表格格式问题
 * 1. 合并被意外换行打断的表格行
 * 2. 确保表格前后有空行
 */
function fixMarkdownTables(text) {
    if (!text) return '';
    
    const lines = text.split('\n');
    const merged = [];
    let i = 0;
    
    // 找到分隔行来确定表格应有的列数
    let expectedCols = 0;
    for (const line of lines) {
        const trimmed = line.trim();
        if (/^\|[-:\s|]+\|$/.test(trimmed)) {
            expectedCols = (trimmed.match(/\|/g) || []).length - 1;
            break;
        }
    }
    
    while (i < lines.length) {
        const line = lines[i];
        const trimmed = line.trim();
        
        // 处理孤立的 | xxx | 格式（通常是被分割的单元格）
        // 例如: "| 高 |" 需要和前一行合并
        if (/^\|\s*[^|]+\s*\|$/.test(trimmed) && merged.length > 0) {
            const cellCount = (trimmed.match(/\|/g) || []).length - 1;
            // 这是一个单独的单元格（如 "| 高 |"），需要和前一行合并
            if (cellCount === 1 && !trimmed.includes('---')) {
                const prevLine = merged[merged.length - 1].trim();
                // 如果前一行不以 | 结尾，说明是不完整的表格行
                if (!prevLine.endsWith('|') && prevLine.length > 0) {
                    // 合并到前一行
                    merged[merged.length - 1] = prevLine + ' ' + trimmed;
                    i++;
                    continue;
                }
            }
        }
        
        // 检测是否是表格片段（以 | 开头）
        if (trimmed.startsWith('|') && expectedCols > 0) {
            // 分隔行直接保留
            if (/^\|[-:\s|]+\|$/.test(trimmed)) {
                merged.push(trimmed);
                i++;
                continue;
            }
            
            // 检查行是否完整（以 | 结尾且列数正确）
            const isComplete = trimmed.endsWith('|') && 
                               (trimmed.match(/\|/g) || []).length - 1 === expectedCols;
            
            if (isComplete) {
                merged.push(trimmed);
                i++;
                continue;
            }
            
            // 行不完整，尝试合并后续内容
            let combined = trimmed;
            let j = i + 1;
            
            while (j < lines.length) {
                const nextLine = lines[j].trim();
                
                // 跳过空行
                if (nextLine === '') {
                    j++;
                    continue;
                }
                
                // 如果遇到分隔行，停止合并
                if (/^\|[-:\s|]+\|$/.test(nextLine)) {
                    break;
                }
                
                // 如果下一行以 | 开头，尝试合并
                if (nextLine.startsWith('|')) {
                    if (combined.endsWith('|')) {
                        // 当前行以 | 结尾，去掉它再连接
                        combined = combined.slice(0, -1).trimEnd() + ' ' + nextLine.slice(1).trimStart();
                    } else {
                        // 当前行不以 | 结尾，保留下一行的 | 作为分隔符
                        combined = combined.trimEnd() + ' ' + nextLine.trimStart();
                    }
                    j++;
                    
                    // 检查合并后是否完整
                    if (combined.endsWith('|') && 
                        (combined.match(/\|/g) || []).length - 1 === expectedCols) {
                        break;
                    }
                } else {
                    // 非 | 开头的内容，也尝试合并（可能是被断开的单元格内容）
                    combined = combined.trimEnd() + ' ' + nextLine.trimStart();
                    j++;
                }
            }
            
            merged.push(combined);
            i = j;
            continue;
        }
        
        // 处理不以 | 开头但后面紧跟 | xxx | 的情况
        // 例如: "2026年将住房支出占比压降...	" 后面跟着 "| 高 |"
        if (i + 1 < lines.length) {
            const nextTrimmed = lines[i + 1].trim();
            if (/^\|\s*[^|]+\s*\|$/.test(nextTrimmed) && !nextTrimmed.includes('---')) {
                // 检查当前行是否像表格内容（不是完整的表格行）
                if (!trimmed.startsWith('|') && !trimmed.endsWith('|') && trimmed.length > 0) {
                    // 合并当前行和下一行
                    merged.push(trimmed + ' ' + nextTrimmed);
                    i += 2;
                    continue;
                }
            }
        }
        
        merged.push(line);
        i++;
    }
    
    let fixed = merged.join('\n');
    
    // 确保表格前后有空行
    fixed = fixed.replace(/([。！？.!?])[ \t]*(\|)/g, '$1\n\n$2');
    fixed = fixed.replace(/([^\n|])[ \t]*\n(\|[^\n]+\|)\n(\|[-:\s|]+\|)/g, '$1\n\n$2\n$3');
    fixed = fixed.replace(/(\|[^\n]+\|)\n([^|\s\n])/g, '$1\n\n$2');
    
    return fixed;
}

/**
 * 彻底清理文本中的 HTML 和 URL
 */
function cleanHtmlAndUrls(text) {
    if (!text) return '';
    
    let cleaned = text
        // 1. 移除完整的 <a> 标签及其内容（处理嵌套情况）
        .replace(/<a\s+[^>]*>[\s\S]*?<\/a>/gi, '')
        // 2. 移除所有未闭合的 <a> 开标签（关键！防止后续内容变成链接）
        .replace(/<a\s+[^>]*>/gi, '')
        // 3. 移除闭合的 </a> 标签
        .replace(/<\/a>/gi, '')
        // 4. 移除其他常见 HTML 标签
        .replace(/<(strong|b|i|em|u|span|div|p|br|ul|li|ol|h[1-6])[^>]*>/gi, '')
        .replace(/<\/(strong|b|i|em|u|span|div|p|br|ul|li|ol|h[1-6])>/gi, '')
        // 5. 移除任何剩余的 HTML 开标签
        .replace(/<[a-zA-Z][^>]*>/g, '')
        // 6. 移除任何剩余的 HTML 闭标签
        .replace(/<\/[a-zA-Z]+>/g, '')
        
        // URL 清理
        // Steam linkfilter URLs
        .replace(/https?:\/\/steamcommunity\.com\/linkfilter\/\?url=[^\s<>"'\]]+/gi, '')
        // file:/// URLs
        .replace(/file:\/\/\/[^\s<>)"\]]+/gi, '')
        // 普通 URLs
        .replace(/https?:\/\/[^\s<>\[\]()'"]+/g, '')
        // Markdown 链接语法
        .replace(/\[([^\]]*)\]\([^)]+\)/g, '$1')
        // 引号包裹的 URLs
        .replace(/"(https?:\/\/[^"]+)"/g, '')
        .replace(/'(https?:\/\/[^']+)'/g, '')
        // URL 编码字符
        .replace(/%22/g, '')
        .replace(/%27/g, '')
        
        // HTML 实体
        .replace(/&[a-zA-Z]+;/g, ' ')
        .replace(/&#\d+;/g, ' ')
        
        // 清理多余空格（保留单个换行，合并多个换行为两个）
        .replace(/[ \t]+/g, ' ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
    
    return cleaned;
}

function renderMarkdown(text) {
    if (!text) return '';
    
    // 1. 先彻底清理 HTML 和 URL
    let cleanedText = cleanHtmlAndUrls(text);
    
    // 2. 修复表格格式问题
    cleanedText = fixMarkdownTables(cleanedText);
    
    // 简单的 Markdown 渲染
    return cleanedText
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        .replace(/^### (.*$)/gm, '<h4>$1</h4>')
        .replace(/^## (.*$)/gm, '<h3>$1</h3>')
        .replace(/^# (.*$)/gm, '<h2>$1</h2>')
        .replace(/^- (.*$)/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/^(.+)$/gm, '<p>$1</p>')
        .replace(/<p><\/p>/g, '');
}

function renderSectionCharts(charts) {
    if (!charts || charts.length === 0) return '';
    
    let html = '';
    for (const chart of charts) {
        html += `
            <div class="chart-container">
                <div class="chart-title">${escapeHtml(chart.title || '图表')}</div>
                <div class="chart-canvas">
                    ${renderSimpleChart(chart)}
                </div>
            </div>
        `;
    }
    return html;
}

function renderSimpleChart(chart) {
    const data = chart.rendered_data || [];
    if (data.length === 0) return '<p>暂无数据</p>';
    
    const chartType = chart.chart_type || 'bar';
    const dataSources = chart.data_sources || [];
    
    if (dataSources.length === 0) return '<p>图表配置不完整</p>';
    
    const ds = dataSources[0];
    const xAxis = ds.x_axis;
    const yAxis = ds.y_axis?.[0];
    
    if (!xAxis || !yAxis) return '<p>图表轴配置不完整</p>';
    
    // 获取数据
    const chartData = data.slice(0, 10).map(row => ({
        label: String(row[xAxis] || ''),
        value: parseFloat(row[yAxis]) || 0,
    }));
    
    const maxValue = Math.max(...chartData.map(d => d.value), 1);
    
    if (chartType === 'pie') {
        return renderPieChart(chartData);
    }
    
    // 默认柱状图
    return `
        <div class="simple-bar-chart">
            ${chartData.map(d => `
                <div class="bar-item">
                    <div class="bar-label" title="${escapeHtml(d.label)}">${escapeHtml(d.label.slice(0, 15))}</div>
                    <div class="bar-track">
                        <div class="bar-fill" style="width: ${(d.value / maxValue * 100).toFixed(1)}%">
                            ${formatNumber(d.value)}
                        </div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function renderPieChart(data) {
    const total = data.reduce((sum, d) => sum + d.value, 0);
    const colors = ['#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6'];
    
    let cumulativePercent = 0;
    const gradientParts = data.map((d, i) => {
        const percent = (d.value / total) * 100;
        const start = cumulativePercent;
        cumulativePercent += percent;
        return `${colors[i % colors.length]} ${start}% ${cumulativePercent}%`;
    });
    
    return `
        <div class="simple-pie-chart">
            <div class="pie-visual" style="background: conic-gradient(${gradientParts.join(', ')})"></div>
            <div class="pie-legend">
                ${data.map((d, i) => `
                    <div class="legend-item">
                        <div class="legend-color" style="background: ${colors[i % colors.length]}"></div>
                        <span>${escapeHtml(d.label)}: ${formatNumber(d.value)} (${((d.value / total) * 100).toFixed(1)}%)</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function renderSectionTables(tables) {
    if (!tables || tables.length === 0) return '';
    
    let html = '';
    for (const table of tables) {
        const data = table.data || [];
        if (data.length === 0) continue;
        
        const columns = Object.keys(data[0]);
        
        html += `
            <div class="section-table">
                <table>
                    <thead>
                        <tr>
                            ${columns.map(col => `<th>${escapeHtml(col)}</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        ${data.slice(0, 10).map(row => `
                            <tr>
                                ${columns.map(col => `<td>${escapeHtml(String(row[col] ?? ''))}</td>`).join('')}
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
                ${data.length > 10 ? `<p class="result-footer">显示前 10 条，共 ${table.row_count || data.length} 条</p>` : ''}
            </div>
        `;
    }
    return html;
}

function closeReportPreview() {
    elements.reportPreview.style.display = 'none';
    elements.reportProgress.style.display = 'none';
    state.currentReport = null;
}

function exportReport() {
    if (!state.currentReport) return;
    
    const report = state.currentReport;
    let markdown = `# ${report.title}\n\n`;
    markdown += `> ${report.summary}\n\n`;
    markdown += `生成时间: ${new Date(report.created_at).toLocaleString()}\n\n---\n\n`;
    
    for (const section of report.sections || []) {
        markdown += `## ${section.title}\n\n`;
        markdown += section.content + '\n\n';
        
        // 表格数据
        for (const table of section.tables || []) {
            if (table.data && table.data.length > 0) {
                const columns = Object.keys(table.data[0]);
                markdown += `| ${columns.join(' | ')} |\n`;
                markdown += `| ${columns.map(() => '---').join(' | ')} |\n`;
                for (const row of table.data.slice(0, 20)) {
                    markdown += `| ${columns.map(c => row[c] ?? '').join(' | ')} |\n`;
                }
                markdown += '\n';
            }
        }
        
        markdown += '---\n\n';
    }
    
    // 下载文件
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${report.title || '报告'}_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
}

async function loadReportHistory() {
    if (!state.sessionId) return;
    
    try {
        const result = await apiCall(`/report/list/${state.sessionId}`);
        state.reports = result.reports || [];
        renderReportHistory();
    } catch (error) {
        console.error('加载报告历史失败:', error);
    }
}

function renderReportHistory() {
    if (!elements.reportList) return;
    
    if (state.reports.length === 0) {
        elements.reportList.innerHTML = '<p class="no-reports">暂无历史报告</p>';
        return;
    }
    
    elements.reportList.innerHTML = state.reports.map(report => `
        <div class="report-item" onclick="viewReport('${report.report_id}')">
            <div class="report-item-info">
                <div class="report-item-title">${escapeHtml(report.title)}</div>
                <div class="report-item-meta">
                    ${new Date(report.created_at).toLocaleString()} · ${report.section_count} 个章节
                </div>
            </div>
            <span class="report-item-status ${report.status}">${
                report.status === 'completed' ? '已完成' : 
                report.status === 'generating' ? '生成中' : 
                report.status === 'error' ? '失败' : '草稿'
            }</span>
            <div class="report-item-actions">
                <button onclick="event.stopPropagation(); deleteReport('${report.report_id}')">🗑️</button>
            </div>
        </div>
    `).join('');
}

async function deleteReport(reportId) {
    if (!confirm('确定要删除这个报告吗？')) return;
    
    try {
        await apiCall(`/report/${reportId}`, { method: 'DELETE' });
        // 同时从 localStorage 删除
        const reports = JSON.parse(localStorage.getItem('reports') || '{}');
        delete reports[reportId];
        localStorage.setItem('reports', JSON.stringify(reports));
        await loadReportHistory();
    } catch (error) {
        console.error('删除报告失败:', error);
        alert('删除失败: ' + error.message);
    }
}

// 暴露到全局（viewReport 已在前面定义并暴露）
window.deleteReport = deleteReport;

// ============ Agent 监控系统 ============

// Agent 类型配置
const AGENT_CONFIG = {
    router: { color: '#3b82f6', icon: '🔵', label: 'Router' },
    center: { color: '#22c55e', icon: '🟢', label: 'Center' },
    research: { color: '#8b5cf6', icon: '🟣', label: 'Research' },
    nl2sql: { color: '#eab308', icon: '🟡', label: 'NL2SQL' },
    chart: { color: '#f97316', icon: '🟠', label: 'Chart' },
    summary: { color: '#ef4444', icon: '🔴', label: 'Summary' },
    data: { color: '#6b7280', icon: '⚪', label: 'Data' },
};

// 事件类型配置
const EVENT_CONFIG = {
    start: { color: '#22c55e', icon: '▶️' },
    request: { color: '#58a6ff', icon: '📤' },
    chunk: { color: '#7ee787', icon: '📥' },
    response: { color: '#3fb950', icon: '✅' },
    tool_call: { color: '#d2a8ff', icon: '🔧' },
    tool_result: { color: '#a5d6ff', icon: '📋' },
    complete: { color: '#22c55e', icon: '✅' },
    error: { color: '#f85149', icon: '❌' },
};

/**
 * 初始化 Agent 监控面板 - 简化版，显示打开独立监控窗口的按钮
 */
function initAgentMonitor(container) {
    // 重置状态
    state.agentMonitor.agents = {};
    
    // 创建简化的监控提示
    const monitorHtml = `
        <div class="agent-monitor-simple" id="agentMonitor">
            <div class="monitor-simple-header">
                <span class="monitor-icon">🖥️</span>
                <span>Agent 执行中...</span>
                <button class="monitor-open-btn" onclick="openAgentMonitor()">
                    打开监控窗口
                </button>
            </div>
            <div class="monitor-simple-status" id="agentStatus">
                <span class="status-dot running"></span>
                <span id="agentStatusText">正在初始化...</span>
            </div>
        </div>
    `;
    
    // 插入到容器开头
    container.insertAdjacentHTML('afterbegin', monitorHtml);
    container.style.display = 'block';
}

/**
 * 打开独立的 Agent 监控窗口
 */
function openAgentMonitor() {
    // 使用正确的变量名：state.sessionId 或 localStorage 中的 sessionId
    const sessionId = state.sessionId || localStorage.getItem('sessionId') || '';
    if (!sessionId) {
        alert('请先发送一条消息开始对话');
        return;
    }
    console.log('[Monitor] 打开监控窗口, session_id:', sessionId);
    const monitorUrl = `monitor.html?session=${sessionId}`;
    window.open(monitorUrl, 'AgentMonitor', 'width=1200,height=800,menubar=no,toolbar=no,resizable=yes,scrollbars=yes');
}

// 暴露到全局
window.openAgentMonitor = openAgentMonitor;

/**
 * 处理 Agent 事件 - 简化版，只更新状态文本
 */
function handleAgentEvent(event, container) {
    const { agent_id, agent_type, agent_label, event_type, timestamp, data } = event;
    
    // 确保监控面板存在
    const monitor = document.getElementById('agentMonitor');
    if (!monitor) {
        initAgentMonitor(container);
    }
    
    // 更新状态文本
    const statusText = document.getElementById('agentStatusText');
    if (statusText) {
        const typeLabels = {
            'center': 'Center Agent',
            'research': 'Researcher',
            'nl2sql': 'NL2SQL',
            'chart': 'Chart Agent',
            'summary': 'Summary Agent',
        };
        const typeName = typeLabels[agent_type] || agent_type;
        
        if (event_type === 'start') {
            statusText.textContent = `${typeName}: ${agent_label}`;
        } else if (event_type === 'complete') {
            statusText.textContent = `${typeName} 完成`;
        } else if (event_type === 'error') {
            statusText.textContent = `${typeName} 出错`;
        } else if (event_type === 'chunk') {
            // 显示流式输出进度
            const chunkLen = data?.content?.length || 0;
            if (chunkLen > 0) {
                statusText.textContent = `${typeName}: 接收数据中... (+${chunkLen}字符)`;
            }
        }
    }
    
    // 更新状态点
    const statusDot = document.querySelector('.status-dot');
    if (statusDot) {
        statusDot.className = 'status-dot';
        if (event_type === 'error') {
            statusDot.classList.add('error');
        } else if (event_type === 'complete') {
            statusDot.classList.add('complete');
        } else {
            statusDot.classList.add('running');
        }
    }
    
    // 在控制台打印详细日志
    console.log(`[Agent] ${agent_type}/${agent_id} - ${event_type}:`, data);
}

/**
 * 创建 Agent 终端窗口
 */
function createAgentTerminal(agentId, agentType, agentLabel) {
    const grid = document.getElementById('agentGrid');
    if (!grid) return;
    
    const config = AGENT_CONFIG[agentType] || AGENT_CONFIG.data;
    
    const terminalHtml = `
        <div class="agent-terminal" id="terminal_${agentId}" data-agent-id="${agentId}">
            <div class="terminal-header" style="border-left-color: ${config.color}">
                <span class="terminal-icon">${config.icon}</span>
                <span class="terminal-title">${escapeHtml(agentLabel)}</span>
                <span class="terminal-status running">●</span>
                <div class="terminal-actions">
                    <button class="terminal-btn" onclick="toggleTerminal('${agentId}')" title="展开/收起">▼</button>
                    <button class="terminal-btn" onclick="copyTerminalLogs('${agentId}')" title="复制日志">📋</button>
                </div>
            </div>
            <div class="terminal-body">
                <div class="terminal-logs" id="logs_${agentId}">
                    <!-- 日志将动态添加 -->
                </div>
            </div>
        </div>
    `;
    
    grid.insertAdjacentHTML('beforeend', terminalHtml);
}

/**
 * 追加 Agent 日志
 */
function appendAgentLog(agentId, logEntry) {
    const logsContainer = document.getElementById(`logs_${agentId}`);
    if (!logsContainer) return;
    
    const eventConfig = EVENT_CONFIG[logEntry.type] || { color: '#6b7280', icon: '•' };
    
    // chunk 类型特殊处理：追加到现有的 chunk-stream 区域
    if (logEntry.type === 'chunk') {
        let streamDiv = logsContainer.querySelector('.chunk-stream');
        if (!streamDiv) {
            // 创建 chunk 流容器
            const streamHtml = `
                <div class="log-entry log-chunk">
                    <span class="log-time">${logEntry.timestamp}</span>
                    <span class="log-icon" style="color: #7ee787">📥</span>
                    <span class="log-type">STREAM</span>
                    <div class="log-data chunk-stream"></div>
                </div>
            `;
            logsContainer.insertAdjacentHTML('beforeend', streamHtml);
            streamDiv = logsContainer.querySelector('.chunk-stream');
        }
        // 追加 chunk 内容
        const chunkType = logEntry.data?.type || 'content';
        const chunkClass = chunkType === 'thinking' ? 'chunk-thinking' : 'chunk-content';
        streamDiv.insertAdjacentHTML('beforeend', `<span class="${chunkClass}">${escapeHtml(logEntry.data?.content || '')}</span>`);
        logsContainer.scrollTop = logsContainer.scrollHeight;
        return;
    }
    
    // response 类型时，清除 chunk-stream（因为响应已完成）
    if (logEntry.type === 'response') {
        const streamEntry = logsContainer.querySelector('.log-entry.log-chunk');
        if (streamEntry) {
            streamEntry.remove();
        }
    }
    
    let dataHtml = '';
    if (logEntry.data) {
        if (logEntry.type === 'request') {
            const msgCount = logEntry.data.messages_count || 0;
            const messages = logEntry.data.messages || [];
            // 显示完整消息列表（可折叠）
            dataHtml = `
                <div class="log-data log-data-expandable">
                    <div class="log-summary" onclick="toggleLogData(this)">
                        📨 消息数: ${msgCount} <span class="expand-hint">[点击展开]</span>
                    </div>
                    <div class="log-messages-list" style="display: none;">
                        ${messages.map(m => `
                            <div class="log-message log-role-${m.role}">
                                <div class="msg-role">${m.role}:</div>
                                <pre class="msg-content-full">${escapeHtml(m.content || '')}</pre>
                                ${m.tool_calls ? `<div class="msg-tools">工具调用: ${m.tool_calls.join(', ')}</div>` : ''}
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        } else if (logEntry.type === 'response') {
            const content = logEntry.data.content || '';
            const tools = logEntry.data.tool_calls || [];
            dataHtml = `
                <div class="log-data log-data-expandable">
                    <div class="log-summary" onclick="toggleLogData(this)">
                        ✅ 响应完成 ${content ? `(${content.length}字)` : ''} ${tools.length > 0 ? `| 工具: ${tools.map(t => t.name).join(', ')}` : ''} <span class="expand-hint">[点击展开]</span>
                    </div>
                    <div class="log-messages-list" style="display: none;">
                        ${content ? `<pre class="log-content-full">${escapeHtml(content)}</pre>` : '<div class="log-empty">无文本内容</div>'}
                        ${tools.map(t => `
                            <div class="log-tool-detail">
                                <div class="tool-name">🔧 ${t.name}</div>
                                <pre class="tool-args">${escapeHtml(t.arguments || '')}</pre>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        } else if (logEntry.type === 'tool_call') {
            const argsStr = JSON.stringify(logEntry.data.arguments || {}, null, 2);
            dataHtml = `
                <div class="log-data log-data-expandable">
                    <div class="log-summary" onclick="toggleLogData(this)">
                        🔧 ${logEntry.data.name} <span class="expand-hint">[点击展开]</span>
                    </div>
                    <div class="log-messages-list" style="display: none;">
                        <pre class="log-args-full">${escapeHtml(argsStr)}</pre>
                    </div>
                </div>
            `;
        } else if (logEntry.type === 'tool_result') {
            dataHtml = `
                <div class="log-data">
                    <div class="log-result">${escapeHtml(logEntry.data.summary || '')}</div>
                </div>
            `;
        } else if (logEntry.data.section_title || logEntry.data.section_name) {
            dataHtml = `<div class="log-data">${escapeHtml(logEntry.data.section_title || logEntry.data.section_name || '')}</div>`;
        }
    }
    
    const logHtml = `
        <div class="log-entry log-${logEntry.type}">
            <span class="log-time">${logEntry.timestamp}</span>
            <span class="log-icon" style="color: ${eventConfig.color}">${eventConfig.icon}</span>
            <span class="log-type">${logEntry.type.toUpperCase()}</span>
            ${dataHtml}
        </div>
    `;
    
    logsContainer.insertAdjacentHTML('beforeend', logHtml);
    
    // 自动滚动到底部
    logsContainer.scrollTop = logsContainer.scrollHeight;
    
    // 更新终端状态指示器
    const terminal = document.getElementById(`terminal_${agentId}`);
    if (terminal) {
        const statusDot = terminal.querySelector('.terminal-status');
        if (statusDot) {
            if (logEntry.type === 'complete') {
                statusDot.className = 'terminal-status complete';
            } else if (logEntry.type === 'error') {
                statusDot.className = 'terminal-status error';
            }
        }
    }
}

/**
 * 切换日志数据的展开/收起
 */
function toggleLogData(element) {
    const list = element.nextElementSibling;
    const hint = element.querySelector('.expand-hint');
    if (list) {
        if (list.style.display === 'none') {
            list.style.display = 'block';
            if (hint) hint.textContent = '[点击收起]';
        } else {
            list.style.display = 'none';
            if (hint) hint.textContent = '[点击展开]';
        }
    }
}

// 暴露到全局
window.toggleLogData = toggleLogData;

/**
 * 更新 Agent 流程图
 */
function updateAgentFlow() {
    const flow = document.getElementById('agentFlow');
    if (!flow) return;
    
    // 按类型分组统计
    const typeStats = {};
    Object.values(state.agentMonitor.agents).forEach(agent => {
        if (!typeStats[agent.type]) {
            typeStats[agent.type] = { running: 0, complete: 0, error: 0, total: 0 };
        }
        typeStats[agent.type].total++;
        typeStats[agent.type][agent.status]++;
    });
    
    // 定义流程顺序
    const flowOrder = ['router', 'center', 'research', 'nl2sql', 'chart', 'summary'];
    
    const flowHtml = flowOrder.map(type => {
        const config = AGENT_CONFIG[type];
        const stats = typeStats[type];
        if (!stats) return '';
        
        let statusClass = 'pending';
        if (stats.running > 0) statusClass = 'running';
        else if (stats.complete === stats.total) statusClass = 'complete';
        else if (stats.error > 0) statusClass = 'error';
        
        return `
            <div class="flow-step ${statusClass}">
                <span class="flow-icon" style="background: ${config.color}">${config.icon}</span>
                <span class="flow-label">${config.label}</span>
                ${stats.total > 1 ? `<span class="flow-count">${stats.complete}/${stats.total}</span>` : ''}
            </div>
        `;
    }).filter(Boolean).join('<span class="flow-arrow">→</span>');
    
    flow.innerHTML = flowHtml;
}

/**
 * 更新 Agent 流程状态
 */
function updateAgentFlowStatus(agentId, status) {
    updateAgentFlow();
}

/**
 * 更新网格布局
 */
function updateAgentGridLayout() {
    const grid = document.getElementById('agentGrid');
    if (!grid) return;
    
    grid.className = `agent-grid view-${state.agentMonitor.viewMode}`;
}

/**
 * 切换监控面板展开/收起
 */
function toggleAgentMonitor() {
    const body = document.getElementById('agentMonitorBody');
    const flow = document.getElementById('agentFlow');
    const btn = document.querySelector('.monitor-toggle-btn');
    
    if (!body) return;
    
    state.agentMonitor.expanded = !state.agentMonitor.expanded;
    
    if (state.agentMonitor.expanded) {
        body.style.display = 'block';
        flow.style.display = 'flex';
        btn.textContent = '▼';
    } else {
        body.style.display = 'none';
        flow.style.display = 'none';
        btn.textContent = '▲';
    }
}

/**
 * 切换终端展开/收起
 */
function toggleTerminal(agentId) {
    const terminal = document.getElementById(`terminal_${agentId}`);
    if (!terminal) return;
    
    terminal.classList.toggle('collapsed');
    const btn = terminal.querySelector('.terminal-actions .terminal-btn');
    if (btn) {
        btn.textContent = terminal.classList.contains('collapsed') ? '▲' : '▼';
    }
}

/**
 * 复制终端日志
 */
function copyTerminalLogs(agentId) {
    const agent = state.agentMonitor.agents[agentId];
    if (!agent) return;
    
    const logs = agent.logs.map(log => {
        return `[${log.timestamp}] ${log.type.toUpperCase()}: ${JSON.stringify(log.data)}`;
    }).join('\n');
    
    navigator.clipboard.writeText(logs).then(() => {
        alert('日志已复制到剪贴板');
    });
}

// 暴露到全局
window.toggleAgentMonitor = toggleAgentMonitor;
window.toggleTerminal = toggleTerminal;
window.copyTerminalLogs = copyTerminalLogs;

// 启动应用
init();

// 加载报告历史（如果有会话）
setTimeout(() => {
    if (state.sessionId) {
        loadReportHistory();
    }
}, 1000);
