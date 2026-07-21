/* app.js — Alpine.js 组件 + fetch helpers.
 *
 * 三个 Alpine 组件:
 *   appShell()        — 全局 shell (base.html), 管当前 tab + comfy 连接状态 + 主题切换
 *   runTab(workflows) — 运行 tab (run.html), 管 preset 选择 + 表单 + 运行 (步骤 4 接 SSE)
 *   settingsTab()     — 设置 tab (settings.html), 管 URL/主题/健康检查
 *
 * 步骤 4 在 runWorkflow() 里接 SSE 流 (/api/run/<preset>).
 * 步骤 5 在 onFileSelect() 里接文件上传 (/api/upload).
 */

// ============================================================
// 通用 fetch helper
// ============================================================

async function fetchJSON(url, options = {}) {
  const r = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!r.ok) {
    const txt = await r.text().catch(() => '');
    throw new Error(`${r.status} ${r.statusText}: ${txt}`);
  }
  return r.json();
}


// ============================================================
// appShell — 全局 shell (base.html)
// ============================================================

function appShell() {
  return {
    currentTab: window.location.pathname.startsWith('/settings') ? 'settings' : 'run',
    comfyStatusHtml: '',
    pending: false,

    async init() {
      await this.refreshStatus();
      // 每 30s 刷新一次连接状态
      setInterval(() => this.refreshStatus(), 30000);
    },

    async refreshStatus() {
      try {
        const s = await fetchJSON('/api/comfy_status');
        this.comfyStatusHtml = `ComfyUI: ${s.dot} <code>${s.url}</code>`;
      } catch (e) {
        this.comfyStatusHtml = 'ComfyUI: <span class="err">状态获取失败</span>';
      }
    },

    // 主题切换 helper (settings tab 也复用)
    async applyTheme(themeId) {
      const data = await fetchJSON('/api/theme', {
        method: 'POST',
        body: JSON.stringify({ theme_id: themeId }),
      });
      // 直接重写 <style id="theme-injector"> 的内容, 毫秒级生效
      const styleEl = document.getElementById('theme-injector');
      if (styleEl) styleEl.textContent = data.css.replace(/^<style[^>]*>/, '').replace(/<\/style>$/, '');
      return data;
    },
  };
}


// ============================================================
// runTab — 运行 tab
// ============================================================

function runTab(workflows, presetCfgs) {
  return {
    workflows: workflows,
    presetCfgs: presetCfgs || {},
    currentPreset: workflows[0]?.name || '',
    searchQuery: '',
    statusHtml: '',
    openDirMsg: '',
    hasLastRun: {},
    // 每个 preset 一组独立状态 (按 name 索引)
    runState: {},       // 'idle' | 'running' | 'success' | 'failure' | 'timeout'
    runLogs: {},
    statusMsg: {},
    elapsedStr: {},
    errorHtml: {},
    resultHtml: {},
    // 配置常量 (从 config 同步)
    imageExts: '.png,.jpg,.jpeg,.webp',
    videoExts: '.mp4,.mov,.webm,.m4v',

    async init() {
      this.refreshStatus();
      // 预加载所有 preset 的 example 值 (填充默认表单)
      for (const w of this.workflows) {
        try {
          const cfg = this.presetCfgs[w.name];
          if (!cfg) continue;
          const exampleVals = await fetchJSON(`/api/example/${w.name}`);
          // 等 Alpine 把 panel 渲染出来再填
          this.$nextTick(() => this.fillPresetPanel(w.name, cfg, exampleVals));
        } catch (e) {
          console.error('init preset', w.name, e);
        }
      }
    },

    get filteredWorkflows() {
      if (!this.searchQuery) return this.workflows;
      const q = this.searchQuery.toLowerCase();
      return this.workflows.filter(w =>
        w.display_name.toLowerCase().includes(q) ||
        w.name.toLowerCase().includes(q)
      );
    },

    selectPreset(name) {
      this.currentPreset = name;
    },

    getPresetCfg(name) {
      return this.presetCfgs[name] || null;
    },

    fillPresetPanel(name, cfg, values) {
      const panel = document.querySelector(`[data-preset="${name}"]`);
      if (!panel || !panel.__x) return;
      panel.__x.$data.presetCfg = cfg;
      const formValues = {};
      let flatIdx = 0;
      for (const spec of cfg.user_facing_inputs) {
        if (spec.type === 'int_random') {
          formValues[flatIdx + '_random'] = values[flatIdx];
          formValues[flatIdx] = values[flatIdx + 1];
          flatIdx += 2;
        } else {
          formValues[flatIdx] = values[flatIdx];
          flatIdx += 1;
        }
      }
      panel.__x.$data.formValues = formValues;
    },

    fillForm(panel, cfg, values) {
      const formValues = {};
      let flatIdx = 0;
      for (const spec of cfg.user_facing_inputs) {
        if (spec.type === 'int_random') {
          formValues[flatIdx + '_random'] = values[flatIdx];
          formValues[flatIdx] = values[flatIdx + 1];
          flatIdx += 2;
        } else {
          formValues[flatIdx] = values[flatIdx];
          flatIdx += 1;
        }
      }
      panel.__x.$data.formValues = formValues;
    },

    sizeValue(opt) { return typeof opt === 'object' ? opt.value : opt; },
    sizeLabel(opt) { return typeof opt === 'object' ? opt.label : opt; },

    async onFileSelect(event, presetName, specIdx, kind) {
      // [步骤 5] 接 /api/upload. 步骤 3 占位.
      const file = event.target.files[0];
      if (!file) return;
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (panel) panel.__x.$data.formValues[specIdx] = file.name;
      console.log('文件选中 (步骤 5 接上传):', file.name);
    },

    onSizeToggle(event, presetName, specIdx) {
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;
      const checked = event.target;
      const current = panel.__x.$data.formValues[specIdx] || [];
      const value = checked.value;
      if (checked.checked) {
        if (!current.includes(value)) current.push(value);
      } else {
        const i = current.indexOf(value);
        if (i >= 0) current.splice(i, 1);
      }
      panel.__x.$data.formValues[specIdx] = current;
    },

    async randomPrompt(presetName, specIdx, n) {
      try {
        const url = n > 1 ? `/api/random_prompt?n=${n}` : '/api/random_prompt';
        const data = await fetchJSON(url);
        const panel = document.querySelector(`[data-preset="${presetName}"]`);
        if (panel) panel.__x.$data.formValues[specIdx] = data.prompt;
      } catch (e) {
        console.error('randomPrompt failed:', e);
      }
    },

    async loadExample(presetName) {
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;
      const cfg = panel.__x.$data.presetCfg;
      if (!cfg) return;
      const values = await fetchJSON(`/api/example/${presetName}`);
      this.fillForm(panel, cfg, values);
    },

    async loadLastRun(presetName) {
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;
      const cfg = panel.__x.$data.presetCfg;
      if (!cfg) return;
      const values = await fetchJSON(`/api/last_run/${presetName}`);
      this.fillForm(panel, cfg, values);
    },

    isRunning(presetName) {
      return this.runState[presetName] === 'running';
    },

    statusIcon(presetName) {
      return ({
        running: '⏳', success: '✅', failure: '❌', timeout: '⏰',
      })[this.runState[presetName]] || '';
    },

    statusLabel(presetName) {
      return ({
        running: '运行中', success: '成功', failure: '失败', timeout: '超时',
      })[this.runState[presetName]] || '';
    },

    async runWorkflow(presetName) {
      // [步骤 4] 接 SSE 流. 步骤 3 占位 — 直接显示 running 状态.
      this.runState[presetName] = 'running';
      this.statusMsg[presetName] = '步骤 3 占位: SSE 在步骤 4 接通';
      console.log('runWorkflow (步骤 4 接 SSE):', presetName);
    },

    async openOutputFolder() {
      try {
        const data = await fetchJSON('/api/open_output_dir', { method: 'POST' });
        this.openDirMsg = data.message;
      } catch (e) {
        this.openDirMsg = '打开失败: ' + e.message;
      }
    },

    async refreshStatus() {
      try {
        const s = await fetchJSON('/api/comfy_status');
        this.statusHtml = `ComfyUI: ${s.dot} <code>${s.url}</code>`;
      } catch (e) {
        this.statusHtml = '状态获取失败';
      }
    },
  };
}


// ============================================================
// settingsTab — 设置 tab
// ============================================================

function settingsTab() {
  return {
    url: '',
    statusMsg: '',
    healthReport: '_点上方「🔍 完整健康检查」查看报告_',
    themes: [],
    currentThemeId: '',
    themeDesc: '',

    async init() {
      // 当前 URL 通过 /api/settings/url/test 之前的某个 GET 拿, 或直接从 comfy_status
      // 这里用 comfy_status 的 url 字段 (settings tab 已有 refreshStatus)
      try {
        const s = await fetchJSON('/api/comfy_status');
        this.url = s.url || '';
      } catch (e) {}
      await this.loadThemes();
    },

    async loadThemes() {
      this.themes = await fetchJSON('/api/themes');
      const cur = await fetchJSON('/api/theme');
      this.currentThemeId = cur.theme_id;
      this.themeDesc = cur.desc;
    },

    async saveUrl() {
      try {
        const data = await fetchJSON('/api/settings/url', {
          method: 'POST',
          body: JSON.stringify({ url: this.url }),
        });
        this.statusMsg = data.message;
      } catch (e) {
        this.statusMsg = '保存失败: ' + e.message;
      }
    },

    async resetUrl() {
      try {
        const data = await fetchJSON('/api/settings/url/reset', { method: 'POST' });
        this.url = data.url;
        this.statusMsg = data.message;
      } catch (e) {
        this.statusMsg = '恢复失败: ' + e.message;
      }
    },

    async retestUrl() {
      try {
        const data = await fetchJSON('/api/settings/url/test');
        this.statusMsg = data.message;
      } catch (e) {
        this.statusMsg = '测试失败: ' + e.message;
      }
    },

    async fullCheck() {
      this.healthReport = '检查中…';
      try {
        const data = await fetchJSON('/api/health');
        this.healthReport = data.report;
      } catch (e) {
        this.healthReport = '检查失败: ' + e.message;
      }
    },

    async changeTheme(themeId) {
      try {
        const data = await fetchJSON('/api/theme', {
          method: 'POST',
          body: JSON.stringify({ theme_id: themeId }),
        });
        // 重写 <style id="theme-injector">
        const styleEl = document.getElementById('theme-injector');
        if (styleEl) {
          styleEl.textContent = data.css.replace(/^<style[^>]*>/, '').replace(/<\/style>$/, '');
        }
        this.themeDesc = data.desc;
      } catch (e) {
        this.statusMsg = '主题切换失败: ' + e.message;
      }
    },
  };
}
