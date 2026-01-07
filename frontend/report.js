/**
 * Chat2Excel 报告页面 JavaScript
 */

// ============ 状态 ============
let currentReport = null;

// ============ 辅助函数 ============

/**
 * 对图表数据进行排序（支持日期、数字、字符串）
 */
function sortChartData(data, xField) {
    if (!data || data.length === 0 || !xField) return data;
    
    // 复制数组避免修改原数据
    const sorted = [...data];
    
    // 检测数据类型
    const sampleValue = sorted[0][xField];
    
    // 判断是否是日期格式
    const isDateLike = typeof sampleValue === 'string' && (
        /^\d{4}[-/]\d{2}[-/]\d{2}/.test(sampleValue) ||  // 2020-01-01 或 2020/01/01
        /^\d{4}[-/]\d{2}$/.test(sampleValue) ||           // 2020-01 或 2020/01
        /^\d{4}$/.test(sampleValue)                       // 2020
    );
    
    // 判断是否是数字
    const isNumeric = typeof sampleValue === 'number' || 
                      (typeof sampleValue === 'string' && !isNaN(parseFloat(sampleValue)));
    
    sorted.sort((a, b) => {
        const valA = a[xField];
        const valB = b[xField];
        
        if (valA == null) return 1;
        if (valB == null) return -1;
        
        if (isDateLike) {
            // 日期排序
            const dateA = new Date(String(valA).replace(/\//g, '-'));
            const dateB = new Date(String(valB).replace(/\//g, '-'));
            return dateA - dateB;
        } else if (isNumeric) {
            // 数字排序
            return parseFloat(valA) - parseFloat(valB);
        } else {
            // 字符串排序
            return String(valA).localeCompare(String(valB));
        }
    });
    
    return sorted;
}

// ============ Tooltip 管理 ============
let tooltipEl = null;

function initTooltip() {
    if (tooltipEl) return;
    tooltipEl = document.createElement('div');
    tooltipEl.className = 'chart-tooltip';
    tooltipEl.style.display = 'none';
    document.body.appendChild(tooltipEl);
}

function showTooltip(e, content) {
    if (!tooltipEl) initTooltip();
    tooltipEl.innerHTML = content;
    tooltipEl.style.display = 'block';
    tooltipEl.classList.add('visible');
    
    // 位置调整
    const rect = tooltipEl.getBoundingClientRect();
    let x = e.clientX + 15;
    let y = e.clientY - 10;
    
    // 边界检测
    if (x + rect.width > window.innerWidth) {
        x = e.clientX - rect.width - 15;
    }
    if (y + rect.height > window.innerHeight) {
        y = e.clientY - rect.height - 10;
    }
    if (y < 0) y = 10;
    
    tooltipEl.style.left = x + 'px';
    tooltipEl.style.top = y + 'px';
}

function hideTooltip() {
    if (tooltipEl) {
        tooltipEl.classList.remove('visible');
        tooltipEl.style.display = 'none';
    }
}

// ============ 初始化 ============
document.addEventListener('DOMContentLoaded', () => {
    initTooltip();
    loadReport();
});

/**
 * 加载报告
 */
function loadReport() {
    const reportId = sessionStorage.getItem('currentReportId');
    
    console.log('[Report] 尝试加载报告, ID:', reportId);
    
    if (!reportId) {
        showError('未找到报告 ID');
        return;
    }
    
    // 从 localStorage 获取报告
    try {
        const reportsRaw = localStorage.getItem('reports');
        console.log('[Report] localStorage reports 原始值:', reportsRaw ? reportsRaw.substring(0, 100) + '...' : 'null');
        
        const reports = JSON.parse(reportsRaw || '{}');
        console.log('[Report] 解析后报告数量:', Object.keys(reports).length);
        console.log('[Report] 报告 IDs:', Object.keys(reports));
        
        const report = reports[reportId];
        
        if (!report) {
            console.error('[Report] 报告不存在, 请求的ID:', reportId);
            console.error('[Report] 可用的IDs:', Object.keys(reports));
            showError('报告不存在或已过期。请刷新聊天页面后重试。');
            return;
        }
        
        console.log('[Report] 成功找到报告:', report.title);
        currentReport = report;
        renderReport(report);
        
    } catch (e) {
        console.error('加载报告失败:', e);
        showError('加载报告失败: ' + e.message);
    }
}

/**
 * 显示错误
 */
function showError(message) {
    document.getElementById('reportContent').innerHTML = `
        <div class="error-state">
            <p>❌ ${message}</p>
            <button onclick="window.close()" class="btn-back">返回</button>
        </div>
    `;
}

/**
 * 渲染报告
 */
function renderReport(report) {
    const content = document.getElementById('reportContent');
    const toc = document.getElementById('toc');
    
    // 渲染标题区
    let html = `
        <div class="report-title-section">
            <h1 class="report-title">${escapeHtml(report.title || '数据分析报告')}</h1>
            <div class="report-meta">
                <span>📊 ${report.sections?.length || 0} 个章节</span>
                <span>📅 ${new Date(report.created_at).toLocaleDateString('zh-CN')}</span>
            </div>
            ${report.summary ? `<div class="report-summary">${escapeHtml(report.summary)}</div>` : ''}
        </div>
    `;
    
    // 渲染目录
    let tocHtml = '';
    
    // 渲染章节
    if (report.sections && report.sections.length > 0) {
        report.sections.forEach((section, index) => {
            const sectionId = `section-${index}`;
            
            // 添加到目录
            tocHtml += `
                <a class="toc-item" href="#${sectionId}" onclick="scrollToSection('${sectionId}')">
                    <span class="toc-number">${index + 1}</span>
                    ${escapeHtml(section.name || `章节 ${index + 1}`)}
                </a>
            `;
            
            // 渲染章节内容
            html += renderSection(section, index);
        });
    }
    
    content.innerHTML = html;
    toc.innerHTML = tocHtml;
    
    // 初始化图表
    setTimeout(() => {
        initCharts();
    }, 100);
    
    // 监听滚动更新目录高亮
    setupScrollSpy();
}

/**
 * 渲染章节
 */
function renderSection(section, index) {
    const sectionId = `section-${index}`;
    
    let html = `
        <section class="report-section" id="${sectionId}">
            <div class="section-header">
                <span class="section-number">${index + 1}</span>
                <h2 class="section-title">${escapeHtml(section.name || `章节 ${index + 1}`)}</h2>
            </div>
    `;
    
    // 分析目标
    if (section.analysis_goal) {
        html += `<div class="section-goal">🎯 ${escapeHtml(section.analysis_goal)}</div>`;
    }
    
    // 渲染发现
    if (section.discoveries && section.discoveries.length > 0) {
        section.discoveries.forEach((discovery, dIndex) => {
            html += renderDiscovery(discovery, dIndex);
        });
    }
    
    html += `</section>`;
    return html;
}

/**
 * 渲染发现
 */
function renderDiscovery(discovery, index) {
    // 兼容 insight 和 content 两种字段名
    const insightContent = discovery.insight || discovery.content || '';
    
    // 渲染 insight 内容
    let insightHtml = renderMarkdown(insightContent);
    
    // 替换 {{CHART:chart_id}} 占位符为图表容器
    if (discovery.charts && discovery.charts.length > 0) {
        discovery.charts.forEach((chart, cIndex) => {
            const chartId = chart.chart_id || `chart-${index}-${cIndex}`;
            const placeholder = `{{CHART:${chartId}}}`;
            const chartHtml = renderChartContainer(chart, `chart-${index}-${cIndex}`);
            
            // 替换占位符
            if (insightHtml.includes(placeholder)) {
                insightHtml = insightHtml.replace(placeholder, chartHtml);
            } else if (insightHtml.includes(escapeHtml(placeholder))) {
                insightHtml = insightHtml.replace(escapeHtml(placeholder), chartHtml);
            }
        });
    }
    
    let html = `
        <div class="discovery">
            <h3 class="discovery-title">${escapeHtml(discovery.title || `发现 ${index + 1}`)}</h3>
            <div class="discovery-content markdown-content">
                ${insightHtml}
            </div>
    `;
    
    // 渲染未被占位符替换的图表（追加到末尾）
    if (discovery.charts && discovery.charts.length > 0) {
        discovery.charts.forEach((chart, cIndex) => {
            const chartContainerId = `chart-${index}-${cIndex}`;
            // 如果图表未被替换到内容中，追加到末尾
            if (!insightHtml.includes(`id="${chartContainerId}"`)) {
                html += renderChartContainer(chart, chartContainerId);
            }
        });
    }
    
    // 添加数据解读
    if (discovery.data_interpretation) {
        html += `<div class="discovery-interpretation">💡 ${escapeHtml(discovery.data_interpretation)}</div>`;
    }
    
    html += `</div>`;
    return html;
}

/**
 * 安全地将对象序列化为 HTML 属性值
 * 使用 Base64 编码避免 JSON 中的特殊字符破坏 HTML
 */
function encodeChartData(chart) {
    try {
        const jsonStr = JSON.stringify(chart);
        // 使用 Base64 编码，确保不会有任何特殊字符
        return btoa(unescape(encodeURIComponent(jsonStr)));
    } catch (e) {
        console.error('[Chart] 编码图表数据失败:', e);
        return '';
    }
}

/**
 * 解码图表数据
 */
function decodeChartData(encoded) {
    try {
        const jsonStr = decodeURIComponent(escape(atob(encoded)));
        return JSON.parse(jsonStr);
    } catch (e) {
        console.error('[Chart] 解码图表数据失败:', e);
        return null;
    }
}

/**
 * 渲染图表容器
 */
function renderChartContainer(chart, chartId) {
    const encodedData = encodeChartData(chart);
    return `
        <div class="chart-container">
            <h4 class="chart-title">${escapeHtml(chart.title || '图表')}</h4>
            <div class="chart-wrapper" id="${chartId}" data-chart="${encodedData}"></div>
        </div>
    `;
}

/**
 * 初始化所有图表（使用 ECharts）
 */
function initCharts() {
    // 等待 ECharts 加载
    if (typeof echarts === 'undefined') {
        console.warn('[Chart] ECharts 未加载，1秒后重试');
        setTimeout(initCharts, 1000);
        return;
    }
    
    document.querySelectorAll('.chart-wrapper[data-chart]').forEach(container => {
        try {
            const chartConfig = decodeChartData(container.dataset.chart);
            if (!chartConfig) {
                throw new Error('无法解析图表配置');
            }
            renderEChart(container, chartConfig);
        } catch (e) {
            console.error('[Chart] 图表渲染失败:', e);
            container.innerHTML = `<div class="chart-no-data">图表渲染失败: ${e.message}</div>`;
        }
    });
    
    // 响应式调整
    window.addEventListener('resize', () => {
        if (typeof echarts === 'undefined') return;
        document.querySelectorAll('.chart-wrapper').forEach(container => {
            const chart = echarts.getInstanceByDom(container);
            if (chart) chart.resize();
        });
    });
}

// ============ ECharts 图表渲染 ============

/**
 * 使用 ECharts 渲染图表
 */
function renderEChart(container, config) {
    // 检查 ECharts 是否可用
    if (typeof echarts === 'undefined') {
        console.warn('[Chart] ECharts 未加载');
        container.innerHTML = '<div class="chart-no-data">图表库未加载</div>';
        return;
    }
    
    const data = config.rendered_data || [];
    
    if (!data || data.length === 0) {
        container.innerHTML = '<div class="chart-no-data">暂无数据</div>';
        return;
    }
    
    // 确保容器有高度
    container.style.minHeight = '350px';
    
    // 销毁已有实例
    const existingChart = echarts.getInstanceByDom(container);
    if (existingChart) {
        existingChart.dispose();
    }
    
    // 创建 ECharts 实例
    const chart = echarts.init(container, 'dark');
    
    // 根据类型生成配置
    const chartType = config.chart_type || 'bar';
    let option;
    
    try {
        switch (chartType) {
            case 'pie':
                option = buildPieOption(config, data);
                break;
            case 'line':
                option = buildLineOption(config, data);
                break;
            case 'dual_axis_mixed':
                option = buildDualAxisOption(config, data);
                break;
            case 'stacked_area':
                option = buildStackedAreaOption(config, data);
                break;
            case 'heatmap':
                option = buildHeatmapOption(config, data);
                break;
            case 'bar':
            default:
                option = buildBarOption(config, data);
                break;
        }
        
        // 应用配置
        chart.setOption(option);
        console.log(`[Chart] 渲染成功: ${chartType}, 数据量: ${data.length}`);
        
    } catch (e) {
        console.error('[Chart] 配置生成失败:', e);
        container.innerHTML = `<div class="chart-no-data">图表配置错误: ${e.message}</div>`;
    }
}

/**
 * 解析图表字段（增强版：去重 + 验证）
 */
function parseChartFields(config, data) {
    const dataSources = config.data_sources || [];
    let xField = null;
    let yFieldsSet = new Set(); // 使用 Set 去重
    let dataLabels = {};  // 存储字段对应的中文标签
    
    if (dataSources.length > 0) {
        xField = dataSources[0].xAxis || dataSources[0].x_axis;
        dataSources.forEach(ds => {
            const fields = ds.yAxis || ds.y_axis || [];
            const label = ds.data_label || ds.dataLabel || '';
            fields.forEach(f => {
                yFieldsSet.add(f);
                if (label && !dataLabels[f]) {
                    dataLabels[f] = label;
                }
            });
        });
    }
    
    // 自动检测
    const keys = Object.keys(data[0] || {});
    if (!xField || !keys.includes(xField)) {
        // 优先选择看起来像时间的字段
        xField = keys.find(k => /年|date|year|month|time/i.test(k) && typeof data[0][k] !== 'number') 
              || keys.find(k => typeof data[0][k] === 'string') 
              || keys[0];
    }
    
    let yFields = Array.from(yFieldsSet);
    
    // 验证字段是否存在于数据中
    yFields = yFields.filter(f => {
        if (!keys.includes(f)) {
            console.warn(`[Chart] 字段 "${f}" 不存在于数据中`);
            return false;
        }
        return true;
    });
    
    // 如果没有有效的 Y 字段，自动检测数值字段
    if (yFields.length === 0) {
        yFields = keys.filter(k => k !== xField && typeof data[0][k] === 'number');
        console.log(`[Chart] 自动检测 Y 字段: ${yFields.join(', ')}`);
    }
    
    return { xField, yFields, keys, dataLabels };
}

/**
 * 构建柱状图配置
 */
function buildBarOption(config, data) {
    const { xField, yFields } = parseChartFields(config, data);
    
    // 过滤掉 X 轴值为空的数据
    const validData = data.filter(d => d[xField] != null && d[xField] !== '' && d[xField] !== 'undefined');
    
    // 排序并限制数量
    const sortedData = sortChartData(validData, xField);
    const displayData = sortedData.length > 25 
        ? [...sortedData].sort((a, b) => (parseFloat(b[yFields[0]]) || 0) - (parseFloat(a[yFields[0]]) || 0)).slice(0, 20)
        : sortedData;
    
    return {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' }
        },
        legend: {
            show: yFields.length > 1,
            top: 10,
            textStyle: { color: '#94a3b8' }
        },
        grid: {
            left: '3%', right: '4%', bottom: '15%', top: yFields.length > 1 ? 50 : 30,
            containLabel: true
        },
        xAxis: {
            type: 'category',
            data: displayData.map(d => d[xField]),
            axisLabel: { 
                color: '#94a3b8',
                rotate: displayData.length > 8 ? 45 : 0,
                interval: 0,
                formatter: val => String(val).substring(0, 12)
            },
            axisLine: { lineStyle: { color: '#475569' } }
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: '#94a3b8', formatter: val => formatNumber(val) },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
            axisLine: { lineStyle: { color: '#475569' } }
        },
        series: yFields.map((field, idx) => ({
            name: field,
            type: 'bar',
            data: displayData.map(d => parseFloat(d[field]) || 0),
            itemStyle: { color: CHART_COLORS[idx % CHART_COLORS.length] },
            barMaxWidth: 50
        }))
    };
}

/**
 * 构建折线图配置
 */
function buildLineOption(config, data) {
    const { xField, yFields } = parseChartFields(config, data);
    
    // 过滤掉 X 轴值为空的数据
    const validData = data.filter(d => d[xField] != null && d[xField] !== '' && d[xField] !== 'undefined');
    
    // 按 X 轴排序
    const sortedData = sortChartData(validData, xField);
    const displayData = sortedData.slice(0, 100);
    
    return {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' }
        },
        legend: {
            show: yFields.length > 1,
            top: 10,
            textStyle: { color: '#94a3b8' }
        },
        grid: {
            left: '3%', right: '4%', bottom: '15%', top: yFields.length > 1 ? 50 : 30,
            containLabel: true
        },
        xAxis: {
            type: 'category',
            data: displayData.map(d => d[xField]),
            boundaryGap: false,
            axisLabel: { 
                color: '#94a3b8',
                rotate: displayData.length > 15 ? 45 : 0,
                interval: Math.max(0, Math.floor(displayData.length / 10) - 1)
            },
            axisLine: { lineStyle: { color: '#475569' } }
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: '#94a3b8', formatter: val => formatNumber(val) },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } }
        },
        series: yFields.map((field, idx) => ({
            name: field,
            type: 'line',
            data: displayData.map(d => parseFloat(d[field]) || 0),
            smooth: true,
            symbol: 'circle',
            symbolSize: 6,
            lineStyle: { width: 2.5, color: CHART_COLORS[idx % CHART_COLORS.length] },
            itemStyle: { color: CHART_COLORS[idx % CHART_COLORS.length] },
            areaStyle: { 
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: CHART_COLORS[idx % CHART_COLORS.length] + '40' },
                    { offset: 1, color: CHART_COLORS[idx % CHART_COLORS.length] + '05' }
                ])
            }
        }))
    };
}

/**
 * 构建饼图配置
 */
function buildPieOption(config, data) {
    const { xField, yFields, keys } = parseChartFields(config, data);
    const valueField = yFields[0] || keys.find(k => typeof data[0][k] === 'number');
    const nameField = xField || keys.find(k => typeof data[0][k] === 'string');
    
    // 按值排序取 TOP 10
    const sortedData = [...data].sort((a, b) => 
        (parseFloat(b[valueField]) || 0) - (parseFloat(a[valueField]) || 0)
    ).slice(0, 10);
    
    const total = sortedData.reduce((sum, d) => sum + (parseFloat(d[valueField]) || 0), 0);
    
    return {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'item',
            formatter: params => `${params.name}<br/>${params.seriesName}: ${formatNumber(params.value)} (${params.percent}%)`
        },
        legend: {
            type: 'scroll',
            orient: 'vertical',
            right: '5%',
            top: 'center',
            textStyle: { color: '#94a3b8' }
        },
        series: [{
            name: valueField,
            type: 'pie',
            radius: ['40%', '70%'],
            center: ['40%', '50%'],
            avoidLabelOverlap: true,
            itemStyle: {
                borderRadius: 6,
                borderColor: '#1e293b',
                borderWidth: 2
            },
            label: {
                show: true,
                formatter: '{b}: {d}%',
                color: '#94a3b8'
            },
            emphasis: {
                label: { show: true, fontSize: 14, fontWeight: 'bold' }
            },
            data: sortedData.map((d, idx) => ({
                name: d[nameField] || `项目${idx + 1}`,
                value: parseFloat(d[valueField]) || 0,
                itemStyle: { color: CHART_COLORS[idx % CHART_COLORS.length] }
            }))
        }]
    };
}

/**
 * 构建双轴混合图配置
 */
function buildDualAxisOption(config, data) {
    const dataSources = config.data_sources || [];
    
    // 解析主轴和副轴字段
    let xField = null;
    let primaryFields = [];
    let secondaryFields = [];
    
    dataSources.forEach(ds => {
        const x = ds.xAxis || ds.x_axis;
        if (x) xField = x;
        
        const yFields = ds.yAxis || ds.y_axis || [];
        const axis = ds.axis || 'primary';
        
        if (axis === 'secondary') {
            secondaryFields.push(...yFields);
        } else {
            primaryFields.push(...yFields);
        }
    });
    
    // 如果没有副轴字段，回退到普通柱状图
    if (secondaryFields.length === 0) {
        return buildBarOption(config, data);
    }
    
    const keys = Object.keys(data[0] || {});
    if (!xField) xField = keys[0];
    
    // 验证字段
    primaryFields = primaryFields.filter(f => keys.includes(f));
    secondaryFields = secondaryFields.filter(f => keys.includes(f));
    
    if (primaryFields.length === 0 && secondaryFields.length === 0) {
        return buildBarOption(config, data);
    }
    
    // 过滤掉 X 轴值为空的数据
    const validData = data.filter(d => d[xField] != null && d[xField] !== '' && d[xField] !== 'undefined');
    
    const sortedData = sortChartData(validData, xField);
    // 限制数据量，避免横轴拥挤
    const maxItems = 20;
    const displayData = sortedData.length > maxItems ? sortedData.slice(0, maxItems) : sortedData;
    
    return {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' }
        },
        legend: {
            top: 10,
            textStyle: { color: '#94a3b8' }
        },
        grid: {
            left: '8%', right: '10%', bottom: '20%', top: 60,
            containLabel: true
        },
        xAxis: {
            type: 'category',
            data: displayData.map(d => {
                // 截断过长的标签
                const label = String(d[xField] || '');
                return label.length > 15 ? label.substring(0, 15) + '...' : label;
            }),
            axisLabel: { 
                color: '#94a3b8',
                rotate: displayData.length > 6 ? 45 : 0,
                interval: 0,  // 显示所有标签
                fontSize: 10
            },
            axisLine: { lineStyle: { color: '#475569' } }
        },
        yAxis: [
            {
                type: 'value',
                name: primaryFields.join(', '),
                nameTextStyle: { color: '#6366f1' },
                axisLabel: { color: '#6366f1', formatter: val => formatNumber(val) },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } }
            },
            {
                type: 'value',
                name: secondaryFields.join(', '),
                nameTextStyle: { color: '#22c55e' },
                axisLabel: { color: '#22c55e', formatter: val => formatNumber(val) },
                splitLine: { show: false }
            }
        ],
        series: [
            ...primaryFields.map((field, idx) => ({
                name: field,
                type: 'bar',
                yAxisIndex: 0,
                data: displayData.map(d => parseFloat(d[field]) || 0),
                itemStyle: { color: CHART_COLORS[idx % CHART_COLORS.length] },
                barMaxWidth: 40
            })),
            ...secondaryFields.map((field, idx) => ({
                name: field,
                type: 'line',
                yAxisIndex: 1,
                data: displayData.map(d => parseFloat(d[field]) || 0),
                smooth: true,
                symbol: 'circle',
                symbolSize: 6,
                lineStyle: { width: 3, color: CHART_COLORS[(primaryFields.length + idx) % CHART_COLORS.length] },
                itemStyle: { color: CHART_COLORS[(primaryFields.length + idx) % CHART_COLORS.length] }
            }))
        ]
    };
}

/**
 * 构建堆叠面积图配置（用于占比变化）
 */
function buildStackedAreaOption(config, data) {
    const { xField, yFields } = parseChartFields(config, data);
    
    // 过滤掉 X 轴值为空的数据
    const validData = data.filter(d => d[xField] != null && d[xField] !== '' && d[xField] !== 'undefined');
    
    const sortedData = sortChartData(validData, xField);
    
    return {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' }
        },
        legend: {
            top: 10,
            textStyle: { color: '#94a3b8' }
        },
        grid: {
            left: '3%', right: '4%', bottom: '15%', top: 50,
            containLabel: true
        },
        xAxis: {
            type: 'category',
            boundaryGap: false,
            data: sortedData.map(d => d[xField]),
            axisLabel: { color: '#94a3b8' }
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: '#94a3b8', formatter: val => formatNumber(val) },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } }
        },
        series: yFields.map((field, idx) => ({
            name: field,
            type: 'line',
            stack: 'total',
            areaStyle: {},
            emphasis: { focus: 'series' },
            data: sortedData.map(d => parseFloat(d[field]) || 0),
            itemStyle: { color: CHART_COLORS[idx % CHART_COLORS.length] }
        }))
    };
}

/**
 * 构建热力图配置
 */
function buildHeatmapOption(config, data) {
    // 简化实现，回退到柱状图
    return buildBarOption(config, data);
}

// 专业配色方案
const CHART_COLORS = [
    '#6366f1', // 靛蓝
    '#22c55e', // 绿色
    '#f59e0b', // 琥珀
    '#ef4444', // 红色
    '#8b5cf6', // 紫色
    '#06b6d4', // 青色
    '#ec4899', // 粉色
    '#84cc16', // 青柠
];

// 图表常量
const CHART_CONFIG = {
    padding: { top: 20, right: 20, bottom: 55, left: 55 },  // 适当边距
    barWidthRatio: 0.7,      // 柱宽占可用空间比例
    maxYAxisPadding: 1.12,   // Y轴最大值留12%空间
    gridLines: 5,            // 网格线数量
    maxBarItems: 20,         // 柱状图最大显示条数（超过则只显示 TOP N）
    maxLineItems: 30,        // 折线图最大显示点数（降低到30，避免过于密集）
    maxLinePointsShow: 20,   // 超过此数量不显示数据点圆圈
    fontSize: {
        tick: 11,
        label: 10,
        legend: 11,
    },
};

/**
 * 纯 CSS/SVG 渲染图表入口
 */
function renderCSSChart(container, config) {
    try {
        const data = config.rendered_data || [];
        
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="chart-no-data">暂无数据</div>';
            return;
        }
        
        // 验证数据格式
        if (typeof data[0] !== 'object') {
            container.innerHTML = '<div class="chart-no-data">数据格式错误</div>';
            return;
        }
        
        const chartType = config.chart_type || 'bar';
        
        console.log(`[Chart] 渲染 ${chartType} 图表, 数据量: ${data.length}`);
        
        switch (chartType) {
            case 'pie':
                renderPieChart(container, config, data);
                break;
            case 'line':
                renderLineChart(container, config, data);
                break;
            case 'dual_axis_mixed':
                renderDualAxisChart(container, config, data);
                break;
            case 'bar':
            default:
                renderBarChart(container, config, data);
                break;
        }
    } catch (err) {
        console.error('[Chart] 图表渲染失败:', err, config);
        container.innerHTML = `<div class="chart-no-data">图表渲染失败: ${err.message}</div>`;
    }
}

/**
 * 渲染柱状图 - 严格按规范实现
 */
function renderBarChart(container, config, data) {
    const dataSources = config.data_sources || [];
    
    // 解析字段
    let xField, yFields;
    if (dataSources.length > 0) {
        xField = dataSources[0].xAxis || dataSources[0].x_axis;
        yFields = [];
        dataSources.forEach(ds => {
            yFields.push(...(ds.yAxis || ds.y_axis || []));
        });
    } else {
        const keys = Object.keys(data[0] || {});
        xField = keys[0];
        yFields = keys.slice(1).filter(k => typeof data[0][k] === 'number');
    }
    
    // 验证字段是否存在于数据中
    const dataKeys = Object.keys(data[0] || {});
    if (xField && !dataKeys.includes(xField)) {
        console.warn(`[Chart] xField "${xField}" 不存在于数据中，尝试自动匹配`);
        xField = dataKeys.find(k => typeof data[0][k] === 'string') || dataKeys[0];
    }
    yFields = yFields.filter(f => {
        if (!dataKeys.includes(f)) {
            console.warn(`[Chart] yField "${f}" 不存在于数据中，已跳过`);
            return false;
        }
        return true;
    });
    
    // 如果没有有效的 yFields，尝试自动检测数值字段
    if (yFields.length === 0) {
        yFields = dataKeys.filter(k => k !== xField && typeof data[0][k] === 'number');
        console.warn(`[Chart] 自动检测数值字段: ${yFields.join(', ')}`);
    }
    
    if (!xField || yFields.length === 0) {
        container.innerHTML = '<div class="chart-no-data">数据格式不支持（无有效字段）</div>';
        return;
    }
    
    // 按 xAxis 字段排序
    const sortedData = sortChartData(data, xField);
    
    // 限制柱状图数据量，超过则只显示 TOP N（按第一个 Y 字段降序）
    let displayData = sortedData;
    if (sortedData.length > CHART_CONFIG.maxBarItems && yFields.length > 0) {
        displayData = [...sortedData].sort((a, b) => {
            const va = parseFloat(a[yFields[0]]) || 0;
            const vb = parseFloat(b[yFields[0]]) || 0;
            return vb - va; // 降序
        }).slice(0, CHART_CONFIG.maxBarItems);
        console.log(`[Chart] 柱状图数据过多(${sortedData.length})，只显示 TOP ${CHART_CONFIG.maxBarItems}`);
    }
    
    // 计算 Y 轴范围（从0开始，最大值留15%空间）
    let maxValue = 0;
    displayData.forEach(d => {
        yFields.forEach(f => {
            const val = Math.abs(parseFloat(d[f]) || 0);
            if (val > maxValue) maxValue = val;
        });
    });
    maxValue = maxValue * CHART_CONFIG.maxYAxisPadding || 100;
    
    // 计算 Y 轴刻度
    const yTicks = calculateYTicks(0, maxValue, CHART_CONFIG.gridLines);
    
    // SVG 尺寸
    const width = 600;
    const height = 300;
    const plotLeft = CHART_CONFIG.padding.left;
    const plotRight = width - CHART_CONFIG.padding.right;
    const plotTop = CHART_CONFIG.padding.top;
    const plotBottom = height - CHART_CONFIG.padding.bottom;
    const plotWidth = plotRight - plotLeft;
    const plotHeight = plotBottom - plotTop;
    
    // 柱宽计算
    const groupWidth = plotWidth / displayData.length;
    const barWidth = (groupWidth * CHART_CONFIG.barWidthRatio) / yFields.length;
    const barGap = (groupWidth - barWidth * yFields.length) / 2;
    
    let svg = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">`;
    
    // 背景
    svg += `<rect x="${plotLeft}" y="${plotTop}" width="${plotWidth}" height="${plotHeight}" fill="rgba(0,0,0,0.1)"/>`;
    
    // 网格线和 Y 轴刻度
    yTicks.forEach(tick => {
        const y = plotBottom - (tick / maxValue) * plotHeight;
        svg += `<line x1="${plotLeft}" y1="${y}" x2="${plotRight}" y2="${y}" stroke="rgba(255,255,255,0.1)" stroke-dasharray="4,4"/>`;
        svg += `<text x="${plotLeft - 10}" y="${y + 4}" text-anchor="end" fill="#94a3b8" font-size="${CHART_CONFIG.fontSize.tick}">${formatNumber(tick)}</text>`;
    });
    
    // X 轴基线（Y=0）
    svg += `<line x1="${plotLeft}" y1="${plotBottom}" x2="${plotRight}" y2="${plotBottom}" stroke="#475569" stroke-width="2"/>`;
    // Y 轴线
    svg += `<line x1="${plotLeft}" y1="${plotTop}" x2="${plotLeft}" y2="${plotBottom}" stroke="#475569" stroke-width="2"/>`;
    
    // 绘制柱状图
    displayData.forEach((d, dIdx) => {
        const groupX = plotLeft + dIdx * groupWidth;
        
        yFields.forEach((field, fIdx) => {
            const value = parseFloat(d[field]) || 0;
            const barHeight = (Math.abs(value) / maxValue) * plotHeight;
            const barX = groupX + barGap + fIdx * barWidth;
            const barY = plotBottom - barHeight; // 从 X 轴向上
            const color = CHART_COLORS[fIdx % CHART_COLORS.length];
            
            // 柱体（紧贴X轴，顶部圆角，带 data 属性用于 tooltip）
            const xLabel = d[xField] || '';
            svg += `<rect 
                x="${barX}" 
                y="${barY}" 
                width="${barWidth - 2}" 
                height="${barHeight}" 
                fill="${color}" 
                rx="3" 
                class="chart-bar chart-point"
                data-field="${escapeHtml(field)}"
                data-value="${value}"
                data-label="${escapeHtml(xLabel)}"
                data-color="${color}"
            />`;
            
            // 数值标签（悬停时显示）
            svg += `<text 
                x="${barX + barWidth / 2}" 
                y="${barY - 5}" 
                text-anchor="middle" 
                fill="#f1f5f9" 
                font-size="10" 
                class="bar-value-label"
            >${formatNumber(value)}</text>`;
        });
        
        // X 轴标签（智能显示：超过10个时只显示部分）
        const showLabel = displayData.length <= 10 || dIdx % Math.ceil(displayData.length / 8) === 0;
        if (showLabel) {
            const labelX = groupX + groupWidth / 2;
            const label = String(d[xField]).substring(0, 12);
            const rotation = displayData.length > 6 ? -45 : 0;
            svg += `<text 
                x="${labelX}" 
                y="${plotBottom + 20}" 
                text-anchor="${rotation ? 'end' : 'middle'}" 
                fill="#94a3b8" 
                font-size="${CHART_CONFIG.fontSize.label}"
                ${rotation ? `transform="rotate(${rotation}, ${labelX}, ${plotBottom + 20})"` : ''}
            >${escapeHtml(label)}</text>`;
        }
    });
    
    svg += `</svg>`;
    
    // 图例
    let legendHtml = '';
    if (yFields.length > 1) {
        legendHtml = `<div class="chart-legend">`;
        yFields.forEach((field, idx) => {
            legendHtml += `<span class="legend-item"><span class="legend-dot" style="background:${CHART_COLORS[idx % CHART_COLORS.length]}"></span>${escapeHtml(field)}</span>`;
        });
        legendHtml += `</div>`;
    }
    
    container.innerHTML = `<div class="chart-wrapper-inner">${legendHtml}${svg}</div>`;
}

/**
 * 渲染折线图 - 严格按规范实现
 */
function renderLineChart(container, config, data) {
    const dataSources = config.data_sources || [];
    
    let xField, yFields;
    if (dataSources.length > 0) {
        xField = dataSources[0].xAxis || dataSources[0].x_axis;
        yFields = [];
        dataSources.forEach(ds => {
            yFields.push(...(ds.yAxis || ds.y_axis || []));
        });
    } else {
        const keys = Object.keys(data[0] || {});
        xField = keys[0];
        yFields = keys.slice(1).filter(k => typeof data[0][k] === 'number');
    }
    
    // 验证字段是否存在于数据中
    const dataKeys = Object.keys(data[0] || {});
    if (xField && !dataKeys.includes(xField)) {
        console.warn(`[Chart] xField "${xField}" 不存在于数据中，尝试自动匹配`);
        xField = dataKeys.find(k => typeof data[0][k] === 'string') || dataKeys[0];
    }
    yFields = yFields.filter(f => {
        if (!dataKeys.includes(f)) {
            console.warn(`[Chart] yField "${f}" 不存在于数据中，已跳过`);
            return false;
        }
        return true;
    });
    
    if (yFields.length === 0) {
        yFields = dataKeys.filter(k => k !== xField && typeof data[0][k] === 'number');
    }
    
    if (!xField || yFields.length === 0) {
        container.innerHTML = '<div class="chart-no-data">数据格式不支持（无有效字段）</div>';
        return;
    }
    
    // 按 xAxis 字段排序（支持日期和数字）
    const sortedData = sortChartData(data, xField);
    
    // 智能降采样：如果数据点过多，进行等间隔采样
    const maxItems = CHART_CONFIG.maxLineItems;
    let displayData;
    if (sortedData.length > maxItems) {
        const step = Math.ceil(sortedData.length / maxItems);
        displayData = sortedData.filter((_, i) => i % step === 0).slice(0, maxItems);
        console.log(`[Chart] 折线图降采样: ${sortedData.length} -> ${displayData.length} 条`);
    } else {
        displayData = sortedData;
    }
    
    // Y轴从0开始
    let maxValue = 0;
    displayData.forEach(d => {
        yFields.forEach(f => {
            const val = Math.abs(parseFloat(d[f]) || 0);
            if (val > maxValue) maxValue = val;
        });
    });
    maxValue = maxValue * CHART_CONFIG.maxYAxisPadding || 100;
    
    const yTicks = calculateYTicks(0, maxValue, CHART_CONFIG.gridLines);
    
    // SVG 尺寸
    const width = 600;
    const height = 300;
    const plotLeft = CHART_CONFIG.padding.left;
    const plotRight = width - CHART_CONFIG.padding.right;
    const plotTop = CHART_CONFIG.padding.top;
    const plotBottom = height - CHART_CONFIG.padding.bottom;
    const plotWidth = plotRight - plotLeft;
    const plotHeight = plotBottom - plotTop;
    
    let svg = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">`;
    
    // 网格线和 Y 轴刻度
    yTicks.forEach(tick => {
        const y = plotBottom - (tick / maxValue) * plotHeight;
        svg += `<line x1="${plotLeft}" y1="${y}" x2="${plotRight}" y2="${y}" stroke="rgba(255,255,255,0.1)" stroke-dasharray="4,4"/>`;
        svg += `<text x="${plotLeft - 10}" y="${y + 4}" text-anchor="end" fill="#94a3b8" font-size="${CHART_CONFIG.fontSize.tick}">${formatNumber(tick)}</text>`;
    });
    
    // 坐标轴
    svg += `<line x1="${plotLeft}" y1="${plotBottom}" x2="${plotRight}" y2="${plotBottom}" stroke="#475569" stroke-width="2"/>`;
    svg += `<line x1="${plotLeft}" y1="${plotTop}" x2="${plotLeft}" y2="${plotBottom}" stroke="#475569" stroke-width="2"/>`;
    
    // 绘制每条折线
    yFields.forEach((field, fIdx) => {
        const color = CHART_COLORS[fIdx % CHART_COLORS.length];
        
        // 计算点坐标
        const points = displayData.map((d, i) => {
            const x = plotLeft + (i / (displayData.length - 1 || 1)) * plotWidth;
            const val = parseFloat(d[field]) || 0;
            const y = plotBottom - (val / maxValue) * plotHeight;
            return { x, y, val };
        });
        
        // 填充区域
        const areaPath = `M ${points[0].x} ${plotBottom} ` + 
            points.map(p => `L ${p.x} ${p.y}`).join(' ') + 
            ` L ${points[points.length - 1].x} ${plotBottom} Z`;
        svg += `<path d="${areaPath}" fill="${color}" fill-opacity="0.15"/>`;
        
        // 折线
        const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
        svg += `<path d="${linePath}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;
        
        // 数据点（带 data 属性用于 tooltip）
        // 当数据点超过阈值时，不显示圆圈，避免视觉混乱
        const showPoints = displayData.length <= (CHART_CONFIG.maxLinePointsShow || 20);
        if (showPoints) {
            points.forEach((p, i) => {
                const dataItem = displayData[i];
                const xLabel = dataItem[xField] || '';
                svg += `<circle cx="${p.x}" cy="${p.y}" r="5" fill="${color}" stroke="#1e293b" stroke-width="2" 
                    class="data-point chart-point" 
                    data-field="${escapeHtml(field)}" 
                    data-value="${p.val}" 
                    data-label="${escapeHtml(xLabel)}"
                    data-color="${color}"/>`;
            });
        }
    });
    
    // X 轴标签（智能格式化）
    const labelStep = Math.ceil(displayData.length / 8); // 最多 8 个标签
    displayData.forEach((d, i) => {
        if (i % labelStep === 0 || i === displayData.length - 1) {
            const x = plotLeft + (i / (displayData.length - 1 || 1)) * plotWidth;
            let label = String(d[xField]);
            
            // 智能格式化日期：如果是 YYYY-MM-DD 格式，只显示 MM-DD
            if (/^\d{4}-\d{2}-\d{2}/.test(label)) {
                label = label.substring(5, 10);  // "01-17" 而不是 "2023-01-17"
            } else if (/^\d{4}-\d{2}-\d{2}\s/.test(label)) {
                // 带时间的日期格式
                label = label.substring(5, 10);
            } else {
                label = label.substring(0, 8);
            }
            
            svg += `<text x="${x}" y="${plotBottom + 20}" text-anchor="middle" fill="#94a3b8" font-size="${CHART_CONFIG.fontSize.label}">${escapeHtml(label)}</text>`;
        }
    });
    
    // 添加透明覆盖层用于捕获鼠标事件
    svg += `<rect class="line-chart-overlay" x="${plotLeft}" y="${plotTop}" width="${plotWidth}" height="${plotHeight}" fill="transparent" style="cursor:crosshair"/>`;
    
    // 垂直参考线（初始隐藏）
    svg += `<line class="line-chart-guide" x1="${plotLeft}" y1="${plotTop}" x2="${plotLeft}" y2="${plotBottom}" stroke="#6366f1" stroke-width="1" stroke-dasharray="3,3" opacity="0"/>`;
    
    svg += `</svg>`;
    
    // 图例
    let legendHtml = '';
    if (yFields.length > 1) {
        legendHtml = `<div class="chart-legend">`;
        yFields.forEach((field, idx) => {
            legendHtml += `<span class="legend-item"><span class="legend-dot" style="background:${CHART_COLORS[idx % CHART_COLORS.length]}"></span>${escapeHtml(field)}</span>`;
        });
        legendHtml += `</div>`;
    }
    
    container.innerHTML = `<div class="chart-wrapper-inner">${legendHtml}${svg}</div>`;
    
    // 添加折线图交互（就近定位 tooltip）
    setupLineChartInteraction(container, displayData, xField, yFields, {
        plotLeft, plotRight, plotTop, plotBottom, plotWidth, plotHeight, maxValue
    });
}

/**
 * 设置折线图鼠标交互（垂直参考线 + 就近定位）
 */
function setupLineChartInteraction(container, data, xField, yFields, dims) {
    const svg = container.querySelector('svg');
    if (!svg) return;
    
    const overlay = svg.querySelector('.line-chart-overlay');
    const guideLine = svg.querySelector('.line-chart-guide');
    if (!overlay || !guideLine) return;
    
    const { plotLeft, plotWidth, plotTop, plotBottom, maxValue, plotHeight } = dims;
    
    overlay.addEventListener('mousemove', (e) => {
        const rect = svg.getBoundingClientRect();
        const svgWidth = rect.width;
        const svgHeight = rect.height;
        const viewBox = svg.viewBox.baseVal;
        
        // 计算鼠标在 SVG 坐标系中的位置
        const scaleX = viewBox.width / svgWidth;
        const mouseX = (e.clientX - rect.left) * scaleX;
        
        // 找到最近的数据点索引
        const relativeX = mouseX - plotLeft;
        const dataIndex = Math.round((relativeX / plotWidth) * (data.length - 1));
        const clampedIndex = Math.max(0, Math.min(data.length - 1, dataIndex));
        
        // 计算该点的 X 坐标
        const pointX = plotLeft + (clampedIndex / (data.length - 1 || 1)) * plotWidth;
        
        // 更新垂直参考线
        guideLine.setAttribute('x1', pointX);
        guideLine.setAttribute('x2', pointX);
        guideLine.setAttribute('opacity', '1');
        
        // 构建 tooltip 内容
        const dataItem = data[clampedIndex];
        const label = dataItem[xField] || '';
        let tooltipContent = `<div class="tooltip-title">${escapeHtml(String(label))}</div>`;
        
        yFields.forEach((field, idx) => {
            const value = parseFloat(dataItem[field]) || 0;
            const color = CHART_COLORS[idx % CHART_COLORS.length];
            tooltipContent += `
                <div class="tooltip-row">
                    <span class="tooltip-color" style="background:${color}"></span>
                    <span>${escapeHtml(field)}:</span>
                    <span class="tooltip-value">${formatNumber(value)}</span>
                </div>
            `;
        });
        
        showTooltip(e, tooltipContent);
    });
    
    overlay.addEventListener('mouseleave', () => {
        guideLine.setAttribute('opacity', '0');
        hideTooltip();
    });
}

/**
 * 渲染饼图
 */
function renderPieChart(container, config, data) {
    // 尝试从 config 获取字段，否则自动检测
    const dataSources = config.data_sources || [];
    let nameField, valueField;
    
    if (dataSources.length > 0) {
        nameField = dataSources[0].xAxis || dataSources[0].x_axis;
        const yFields = dataSources[0].yAxis || dataSources[0].y_axis || [];
        valueField = yFields[0];
    }
    
    // 自动检测字段
    const keys = Object.keys(data[0] || {});
    if (!nameField || !keys.includes(nameField)) {
        nameField = keys.find(k => typeof data[0][k] === 'string') || keys[0];
    }
    if (!valueField || !keys.includes(valueField)) {
        valueField = keys.find(k => typeof data[0][k] === 'number') || keys[1];
    }
    
    console.log(`[Pie] nameField=${nameField}, valueField=${valueField}`);
    
    const total = data.reduce((sum, d) => sum + (parseFloat(d[valueField]) || 0), 0);
    if (total === 0) {
        container.innerHTML = '<div class="chart-no-data">暂无数据</div>';
        return;
    }
    
    // 如果只有一条数据，显示提示
    if (data.length === 1) {
        container.innerHTML = `<div class="chart-no-data">饼图需要多条数据来展示分布（当前仅1条）</div>`;
        return;
    }
    
    // 按值降序排序，取 TOP 8
    const sortedData = [...data].sort((a, b) => {
        return (parseFloat(b[valueField]) || 0) - (parseFloat(a[valueField]) || 0);
    });
    const displayData = sortedData.slice(0, 8);
    
    // 计算扇区
    let currentAngle = -90; // 从12点钟方向开始
    const segments = displayData.map((d, idx) => {
        const value = parseFloat(d[valueField]) || 0;
        const percentage = (value / total) * 100;
        const angle = (value / total) * 360;
        const seg = {
            name: d[nameField],
            value,
            percentage,
            startAngle: currentAngle,
            endAngle: currentAngle + angle,
            color: CHART_COLORS[idx % CHART_COLORS.length]
        };
        currentAngle += angle;
        return seg;
    });
    
    // SVG 饼图
    const size = 200;
    const cx = size / 2;
    const cy = size / 2;
    const outerR = 90;
    const innerR = 45;
    
    let svg = `<svg class="pie-svg" viewBox="0 0 ${size} ${size}">`;
    
    segments.forEach(seg => {
        const startRad = (seg.startAngle * Math.PI) / 180;
        const endRad = (seg.endAngle * Math.PI) / 180;
        
        const x1 = cx + outerR * Math.cos(startRad);
        const y1 = cy + outerR * Math.sin(startRad);
        const x2 = cx + outerR * Math.cos(endRad);
        const y2 = cy + outerR * Math.sin(endRad);
        const x3 = cx + innerR * Math.cos(endRad);
        const y3 = cy + innerR * Math.sin(endRad);
        const x4 = cx + innerR * Math.cos(startRad);
        const y4 = cy + innerR * Math.sin(startRad);
        
        const largeArc = seg.endAngle - seg.startAngle > 180 ? 1 : 0;
        
        const path = `M ${x1} ${y1} A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2} ${y2} L ${x3} ${y3} A ${innerR} ${innerR} 0 ${largeArc} 0 ${x4} ${y4} Z`;
        
        svg += `<path d="${path}" fill="${seg.color}" class="pie-segment">
            <title>${seg.name}: ${seg.percentage.toFixed(1)}%</title>
        </path>`;
    });
    
    svg += `</svg>`;
    
    // 图例
    let legendHtml = `<div class="pie-legend">`;
    segments.forEach(seg => {
        legendHtml += `
            <div class="pie-legend-item">
                <span class="legend-dot" style="background:${seg.color}"></span>
                <span class="legend-name">${escapeHtml(String(seg.name).substring(0, 12))}</span>
                <span class="legend-value">${seg.percentage.toFixed(1)}%</span>
            </div>
        `;
    });
    legendHtml += `</div>`;
    
    container.innerHTML = `<div class="css-pie-chart">${svg}${legendHtml}</div>`;
}

/**
 * 渲染双轴混合图 - 严格按规范实现
 */
function renderDualAxisChart(container, config, data) {
    const dataSources = config.data_sources || [];
    
    if (dataSources.length < 2) {
        console.warn('[Chart] 双轴图需要至少2个数据源，回退到柱状图');
        renderBarChart(container, config, data);
        return;
    }
    
    let xField = dataSources[0].xAxis || dataSources[0].x_axis;
    let primaryFields = dataSources[0].yAxis || dataSources[0].y_axis || [];
    let secondaryFields = dataSources[1].yAxis || dataSources[1].y_axis || [];
    
    // 验证字段是否存在于数据中
    const dataKeys = Object.keys(data[0] || {});
    if (xField && !dataKeys.includes(xField)) {
        console.warn(`[Chart] xField "${xField}" 不存在于数据中，尝试自动匹配`);
        xField = dataKeys.find(k => typeof data[0][k] === 'string') || dataKeys[0];
    }
    primaryFields = primaryFields.filter(f => dataKeys.includes(f));
    secondaryFields = secondaryFields.filter(f => dataKeys.includes(f));
    
    if (!xField || primaryFields.length === 0 || secondaryFields.length === 0) {
        console.warn('[Chart] 双轴字段无效，回退到柱状图');
        renderBarChart(container, config, data);
        return;
    }
    
    // 按 xAxis 字段排序
    const sortedData = sortChartData(data, xField);
    
    // 限制数据量
    let displayData = sortedData;
    if (sortedData.length > CHART_CONFIG.maxBarItems) {
        displayData = sortedData.slice(0, CHART_CONFIG.maxBarItems);
        console.log(`[Chart] 双轴图数据过多(${sortedData.length})，只显示前 ${CHART_CONFIG.maxBarItems} 条`);
    }
    
    // 计算两个轴的范围（都从0开始）
    let primaryMax = 0, secondaryMax = 0;
    displayData.forEach(d => {
        primaryFields.forEach(f => {
            const val = Math.abs(parseFloat(d[f]) || 0);
            if (val > primaryMax) primaryMax = val;
        });
        secondaryFields.forEach(f => {
            const val = Math.abs(parseFloat(d[f]) || 0);
            if (val > secondaryMax) secondaryMax = val;
        });
    });
    primaryMax = primaryMax * CHART_CONFIG.maxYAxisPadding || 100;
    secondaryMax = secondaryMax * CHART_CONFIG.maxYAxisPadding || 100;
    
    const primaryTicks = calculateYTicks(0, primaryMax, 5);
    const secondaryTicks = calculateYTicks(0, secondaryMax, 5);
    
    // SVG 尺寸（双轴需要更多右边距）
    const width = 650;
    const height = 320;
    const plotLeft = 65;
    const plotRight = width - 65;
    const plotTop = 25;
    const plotBottom = height - 55;
    const plotWidth = plotRight - plotLeft;
    const plotHeight = plotBottom - plotTop;
    
    // 柱宽
    const groupWidth = plotWidth / displayData.length;
    const barWidth = groupWidth * 0.5;
    const barOffset = (groupWidth - barWidth) / 2;
    
    let svg = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">`;
    
    // 左轴网格线和刻度
    primaryTicks.forEach(tick => {
        const y = plotBottom - (tick / primaryMax) * plotHeight;
        svg += `<line x1="${plotLeft}" y1="${y}" x2="${plotRight}" y2="${y}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="4,4"/>`;
        svg += `<text x="${plotLeft - 10}" y="${y + 4}" text-anchor="end" fill="${CHART_COLORS[0]}" font-size="11">${formatNumber(tick)}</text>`;
    });
    
    // 右轴刻度
    secondaryTicks.forEach(tick => {
        const y = plotBottom - (tick / secondaryMax) * plotHeight;
        svg += `<text x="${plotRight + 10}" y="${y + 4}" text-anchor="start" fill="${CHART_COLORS[1]}" font-size="11">${formatNumber(tick)}</text>`;
    });
    
    // 坐标轴
    svg += `<line x1="${plotLeft}" y1="${plotBottom}" x2="${plotRight}" y2="${plotBottom}" stroke="#475569" stroke-width="2"/>`;
    svg += `<line x1="${plotLeft}" y1="${plotTop}" x2="${plotLeft}" y2="${plotBottom}" stroke="${CHART_COLORS[0]}" stroke-width="2"/>`;
    svg += `<line x1="${plotRight}" y1="${plotTop}" x2="${plotRight}" y2="${plotBottom}" stroke="${CHART_COLORS[1]}" stroke-width="2"/>`;
    
    // 绘制柱状图（主轴，紧贴X轴）
    displayData.forEach((d, dIdx) => {
        const groupX = plotLeft + dIdx * groupWidth;
        
        primaryFields.forEach((field, fIdx) => {
            const value = parseFloat(d[field]) || 0;
            const barHeight = (Math.abs(value) / primaryMax) * plotHeight;
            const barX = groupX + barOffset;
            const barY = plotBottom - barHeight;
            const color = CHART_COLORS[fIdx];
            
            svg += `<rect x="${barX}" y="${barY}" width="${barWidth}" height="${barHeight}" fill="${color}" rx="2">
                <title>${field}: ${formatNumber(value)}</title>
            </rect>`;
        });
    });
    
    // 绘制折线（副轴）
    secondaryFields.forEach((field, fIdx) => {
        const color = CHART_COLORS[primaryFields.length + fIdx];
        
        const points = displayData.map((d, i) => {
            const x = plotLeft + i * groupWidth + groupWidth / 2;
            const val = parseFloat(d[field]) || 0;
            const y = plotBottom - (Math.abs(val) / secondaryMax) * plotHeight;
            return { x, y, val };
        });
        
        // 折线
        const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
        svg += `<path d="${linePath}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
        
        // 数据点
        points.forEach(p => {
            svg += `<circle cx="${p.x}" cy="${p.y}" r="6" fill="${color}" stroke="#1e293b" stroke-width="2">
                <title>${field}: ${formatNumber(p.val)}</title>
            </circle>`;
        });
    });
    
    // X 轴标签（智能显示）
    displayData.forEach((d, i) => {
        const showLabel = displayData.length <= 10 || i % Math.ceil(displayData.length / 8) === 0;
        if (showLabel) {
            const x = plotLeft + i * groupWidth + groupWidth / 2;
            const label = String(d[xField]).substring(0, 10);
            const rotation = displayData.length > 6 ? -45 : 0;
            svg += `<text x="${x}" y="${plotBottom + 18}" text-anchor="${rotation ? 'end' : 'middle'}" fill="#94a3b8" font-size="10" ${rotation ? `transform="rotate(${rotation}, ${x}, ${plotBottom + 18})"` : ''}>${escapeHtml(label)}</text>`;
        }
    });
    
    svg += `</svg>`;
    
    // 图例
    let legendHtml = `<div class="chart-legend">`;
    primaryFields.forEach((field, idx) => {
        legendHtml += `<span class="legend-item"><span class="legend-dot" style="background:${CHART_COLORS[idx]}"></span>${escapeHtml(field)} (左轴)</span>`;
    });
    secondaryFields.forEach((field, idx) => {
        legendHtml += `<span class="legend-item"><span class="legend-dot" style="background:${CHART_COLORS[primaryFields.length + idx]}"></span>${escapeHtml(field)} (右轴)</span>`;
    });
    legendHtml += `</div>`;
    
    container.innerHTML = `<div class="chart-wrapper-inner">${legendHtml}${svg}</div>`;
}

/**
 * 计算 Y 轴刻度（智能取整）
 */
function calculateYTicks(min, max, count) {
    const range = max - min;
    const roughStep = range / (count - 1);
    
    // 找到合适的步长（1, 2, 5 的倍数）
    const magnitude = Math.pow(10, Math.floor(Math.log10(roughStep)));
    const residual = roughStep / magnitude;
    
    let niceStep;
    if (residual <= 1.5) niceStep = 1 * magnitude;
    else if (residual <= 3) niceStep = 2 * magnitude;
    else if (residual <= 7) niceStep = 5 * magnitude;
    else niceStep = 10 * magnitude;
    
    const ticks = [];
    for (let i = 0; i < count; i++) {
        ticks.push(Math.round(i * niceStep * 100) / 100);
    }
    
    return ticks;
}

/**
 * 格式化数字
 */
function formatNumber(num) {
    if (num === null || num === undefined || isNaN(num)) return '0';
    num = parseFloat(num);
    if (Math.abs(num) >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (Math.abs(num) >= 1000) return (num / 1000).toFixed(1) + 'K';
    if (num % 1 !== 0) return num.toFixed(1);
    return String(Math.round(num));
}

/**
 * 渲染 Markdown
 */
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
    
    if (typeof marked !== 'undefined') {
        // 配置 marked
        marked.setOptions({
            gfm: true,
            breaks: true,
        });
        
        // 自定义 renderer 禁用所有链接
        const renderer = new marked.Renderer();
        renderer.link = function(href, title, text) {
            // 完全禁用链接，只返回文本
            return text || '';
        };
        
        return marked.parse(cleanedText, { renderer });
    }
    
    // 简单的 Markdown 处理
    return cleanedText
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
}

/**
 * 滚动到章节
 */
function scrollToSection(sectionId) {
    const element = document.getElementById(sectionId);
    if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

/**
 * 设置滚动监听
 */
function setupScrollSpy() {
    const sections = document.querySelectorAll('.report-section');
    const tocItems = document.querySelectorAll('.toc-item');
    
    window.addEventListener('scroll', () => {
        let currentSection = '';
        
        sections.forEach(section => {
            const rect = section.getBoundingClientRect();
            if (rect.top <= 100) {
                currentSection = section.id;
            }
        });
        
        tocItems.forEach(item => {
            item.classList.remove('active');
            if (item.getAttribute('href') === `#${currentSection}`) {
                item.classList.add('active');
            }
        });
    });
}

/**
 * 切换侧边栏
 */
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('collapsed');
}

/**
 * 下载 PDF - 直接生成文件下载
 */
async function downloadPDF() {
    if (!currentReport) {
        alert('报告未加载');
        return;
    }
    
    // 检查依赖库
    if (typeof html2canvas === 'undefined' || typeof jspdf === 'undefined') {
        alert('PDF 导出库未加载，请刷新页面后重试');
        return;
    }
    
    const { jsPDF } = jspdf;
    
    // 显示进度提示
    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'pdf-loading';
    loadingDiv.innerHTML = `
        <div style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);
                    display:flex;align-items:center;justify-content:center;z-index:99999;">
            <div style="background:#1e293b;padding:2.5rem 3rem;border-radius:16px;text-align:center;color:white;
                        box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);">
                <div style="font-size:2rem;margin-bottom:1rem;">📄</div>
                <div style="font-size:1.25rem;font-weight:600;margin-bottom:0.5rem;">正在生成 PDF</div>
                <div id="pdf-progress" style="color:#94a3b8;font-size:0.9rem;">准备中...</div>
                <div style="margin-top:1rem;width:200px;height:4px;background:#334155;border-radius:2px;overflow:hidden;">
                    <div id="pdf-progress-bar" style="width:0%;height:100%;background:linear-gradient(90deg,#3b82f6,#8b5cf6);
                         transition:width 0.3s;"></div>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(loadingDiv);
    
    const updateProgress = (text, percent) => {
        const progressEl = document.getElementById('pdf-progress');
        const barEl = document.getElementById('pdf-progress-bar');
        if (progressEl) progressEl.textContent = text;
        if (barEl) barEl.style.width = percent + '%';
    };
    
    // 保存原始状态
    const chartBackups = [];
    const reportContent = document.getElementById('reportContent');
    
    try {
        updateProgress('转换图表中...', 10);
        
        // Step 1: 将 ECharts 转换为图片
        const chartWrappers = document.querySelectorAll('.chart-wrapper');
        for (const wrapper of chartWrappers) {
            // 检查 echarts 是否可用
            if (typeof echarts !== 'undefined') {
                const chartInstance = echarts.getInstanceByDom(wrapper);
                if (chartInstance) {
                    const dataURL = chartInstance.getDataURL({
                        type: 'png',
                        pixelRatio: 2,
                        backgroundColor: '#ffffff'
                    });
                    chartBackups.push({
                        wrapper: wrapper,
                        originalHTML: wrapper.innerHTML,
                        originalStyle: wrapper.getAttribute('style')
                    });
                    wrapper.innerHTML = `<img src="${dataURL}" style="width:100%;height:auto;display:block;background:white;" />`;
                    wrapper.style.minHeight = 'auto';
                    wrapper.style.background = 'white';
                }
            }
        }
        
        updateProgress('准备导出内容...', 20);
        
        // Step 2: 创建临时导出容器（白色背景）
        const exportContainer = document.createElement('div');
        exportContainer.id = 'pdf-export-container';
        exportContainer.style.cssText = `
            position: absolute;
            left: -9999px;
            top: 0;
            width: 800px;
            background: white;
            color: #1e293b;
            padding: 40px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        `;
        
        // 复制报告内容
        exportContainer.innerHTML = reportContent.innerHTML;
        
        // 应用白色主题样式
        exportContainer.querySelectorAll('.report-section').forEach(el => {
            el.style.cssText = 'background:white;border:1px solid #e2e8f0;border-radius:8px;padding:20px;margin-bottom:20px;';
        });
        exportContainer.querySelectorAll('.discovery').forEach(el => {
            el.style.cssText = 'background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:16px;margin-bottom:12px;';
        });
        exportContainer.querySelectorAll('.section-title, .discovery-title, h1, h2, h3, h4').forEach(el => {
            el.style.color = '#1e293b';
        });
        exportContainer.querySelectorAll('p, li, span').forEach(el => {
            el.style.color = '#334155';
        });
        exportContainer.querySelectorAll('.insight, .data-interpretation').forEach(el => {
            el.style.cssText = 'background:#f1f5f9;border:1px solid #cbd5e1;border-radius:6px;padding:12px;color:#334155;';
        });
        exportContainer.querySelectorAll('.chart-container').forEach(el => {
            el.style.cssText = 'background:white;border:1px solid #e2e8f0;border-radius:6px;padding:12px;margin:12px 0;';
        });
        exportContainer.querySelectorAll('.chart-title').forEach(el => {
            el.style.cssText = 'color:#1e293b;font-size:14px;font-weight:600;margin-bottom:8px;';
        });
        
        document.body.appendChild(exportContainer);
        
        updateProgress('渲染页面...', 40);
        await new Promise(r => setTimeout(r, 500));
        
        // Step 3: 使用 html2canvas 渲染
        const canvas = await html2canvas(exportContainer, {
            scale: 2,
            useCORS: true,
            allowTaint: true,
            backgroundColor: '#ffffff',
            logging: false,
            windowWidth: 800
        });
        
        updateProgress('生成 PDF 文件...', 70);
        
        // Step 4: 创建 PDF
        const imgData = canvas.toDataURL('image/jpeg', 0.95);
        const imgWidth = 210; // A4 宽度 (mm)
        const pageHeight = 297; // A4 高度 (mm)
        const imgHeight = (canvas.height * imgWidth) / canvas.width;
        
        const pdf = new jsPDF('p', 'mm', 'a4');
        let heightLeft = imgHeight;
        let position = 0;
        
        // 添加第一页
        pdf.addImage(imgData, 'JPEG', 0, position, imgWidth, imgHeight);
        heightLeft -= pageHeight;
        
        // 添加更多页
        while (heightLeft > 0) {
            position = heightLeft - imgHeight;
            pdf.addPage();
            pdf.addImage(imgData, 'JPEG', 0, position, imgWidth, imgHeight);
            heightLeft -= pageHeight;
        }
        
        updateProgress('完成！', 100);
        
        // Step 5: 下载文件
        const fileName = `分析报告_${currentReport.title || 'report'}_${new Date().toLocaleDateString('zh-CN').replace(/\//g, '-')}.pdf`;
        pdf.save(fileName);
        
        // 清理
        exportContainer.remove();
        
    } catch (error) {
        console.error('[PDF] 导出失败:', error);
        alert('PDF 导出失败: ' + error.message);
    } finally {
        // 恢复图表
        for (const backup of chartBackups) {
            backup.wrapper.innerHTML = backup.originalHTML;
            if (backup.originalStyle) {
                backup.wrapper.setAttribute('style', backup.originalStyle);
            }
            try {
                const chartConfig = decodeChartData(backup.wrapper.dataset.chart);
                if (chartConfig) {
                    renderEChart(backup.wrapper, chartConfig);
                }
            } catch (e) {
                console.warn('[PDF] 恢复图表失败:', e);
            }
        }
        
        // 移除加载提示
        loadingDiv.remove();
        
        // 清理可能残留的导出容器
        const leftover = document.getElementById('pdf-export-container');
        if (leftover) leftover.remove();
    }
}

/**
 * HTML 转义
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

