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
    },

    async initPanelScope(name, scope) {
      // panel x-init 调用. scope 是 panel 的 $data (Alpine 响应式对象).
      // 拉 example 填默认表单 + 渲染 preview 到结果区.
      const cfg = this.presetCfgs[name];
      if (!cfg) return;
      // 1. 拉 example 填表单
      try {
        const values = await fetchJSON(`/api/example/${name}`);
        const fv = {};
        let fi = 0;
        for (const spec of cfg.user_facing_inputs) {
          if (spec.type === 'int_random') {
            fv[fi + '_random'] = values[fi];
            fv[fi] = values[fi + 1];
            fi += 2;
          } else {
            fv[fi] = values[fi];
            fi += 1;
          }
        }
        scope.formValues = fv;
      } catch (e) {
        console.error('initPanelScope example', name, e);
      }
      // 2. 渲染 preview 作为默认结果
      if (cfg.preview_url) {
        const k = cfg.preview_kind || 'image';
        const caption = '<p class="result-placeholder" style="margin-top:8px">📸 示例效果 (默认参数对应的结果)</p>';
        if (k === 'video') {
          scope.defaultResultHtml = `<div style="padding:8px"><video controls preload="metadata" style="max-width:100%;max-height:70vh;object-fit:contain;border-radius:var(--radius-md);display:block;margin:0 auto""><source src="${cfg.preview_url}"/></video></div>${caption}`;
        } else if (k === 'audio') {
          scope.defaultResultHtml = `<div style="padding:8px"><audio controls preload="metadata" style="width:100%;max-width:480px"><source src="${cfg.preview_url}"/></audio></div>${caption}`;
        } else {
          scope.defaultResultHtml = `<div style="padding:8px"><img src="${cfg.preview_url}" loading="lazy" style="max-width:100%;max-height:70vh;object-fit:contain;border-radius:var(--radius-md);display:block;margin:0 auto""/></div>${caption}`;
        }
      }
    },

    _applyFormValues(panelEl, cfg, values) {
      // loadExample / loadLastRun 用: 把 values 填进 panel formValues.
      // Alpine 3 通过 Alpine.$data(el) 拿响应式 scope.
      const data = (window.Alpine && Alpine.$data) ? Alpine.$data(panelEl) : (panelEl.__x ? panelEl.__x.$data : null);
      if (!data) return;
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
      data.formValues = formValues;
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
      // 兼容旧调用 (loadExample / loadLastRun 用)
      const panel = document.querySelector(`[data-preset="${name}"]`);
      if (!panel || !panel.__x) return;
      this._applyFormValues(panel, cfg, values);
    },

    sizeValue(opt) { return typeof opt === 'object' ? opt.value : opt; },
    sizeLabel(opt) { return typeof opt === 'object' ? opt.label : opt; },

    getExampleThumbUrl(presetName, specIdx) {
      // 从 panel 的 formValues[specIdx] (可能是绝对路径 / 文件名) 提取缩略图 URL.
      // 路径形如 'F:\\...\\.examples_cache\\halfbody.png' -> '/example_cache/halfbody.png'
      // 或纯文件名 'halfbody.png' -> '/comfy_input/halfbody.png'
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return '';
      const data = Alpine.$data(panel);
      const v = data.formValues[specIdx];
      if (!v) return '';
      const basename = v.replace(/\\/g, '/').split('/').pop();
      if (!basename) return '';
      // 如果原路径含 .examples_cache, 走 /example_cache; 否则 /comfy_input
      if (v.includes('.examples_cache') || v.includes('examples_cache')) {
        return '/example_cache/' + encodeURIComponent(basename);
      }
      return '/comfy_input/' + encodeURIComponent(basename);
    },

    async onFileSelect(event, presetName, specIdx, kind) {
      // 步骤 5: 真正上传到 ComfyUI, 把返回的 name 存进 formValues.
      // run_workflow 的 _resolve_upload_name 会识别它在 ComfyUI input 目录, 跳过重复上传.
      const file = event.target.files[0];
      if (!file) return;
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;

      // 先用本地文件名占位, 显示"上传中"
      panel.__x.$data.formValues[specIdx] = file.name + ' (上传中…)';

      const formData = new FormData();
      formData.append('file', file);
      formData.append('kind', kind);
      try {
        const r = await fetch('/api/upload', { method: 'POST', body: formData });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          throw new Error(err.error || `${r.status} ${r.statusText}`);
        }
        const data = await r.json();
        // 用 ComfyUI 端的 name 替换占位
        panel.__x.$data.formValues[specIdx] = data.name;
      } catch (e) {
        panel.__x.$data.formValues[specIdx] = '';
        alert('上传失败: ' + e.message);
      }
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
      this._applyFormValues(panel, cfg, values);
    },

    async loadLastRun(presetName) {
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;
      const cfg = panel.__x.$data.presetCfg;
      if (!cfg) return;
      const values = await fetchJSON(`/api/last_run/${presetName}`);
      this._applyFormValues(panel, cfg, values);
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
      // 步骤 4: 接 SSE 流 (POST + fetch streaming, 因为 EventSource 只支持 GET)
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;
      const formValues = this.collectFormValues(panel);
      const cfg = panel.__x.$data.presetCfg;
      const outputKind = cfg?.output_kind || 'video';

      this.runState[presetName] = 'running';
      this.statusMsg[presetName] = '';
      this.errorHtml[presetName] = '';
      this.runLogs[presetName] = '';

      const startTime = Date.now();
      const updateElapsed = () => {
        const sec = Math.floor((Date.now() - startTime) / 1000);
        const m = String(Math.floor(sec / 60)).padStart(2, '0');
        const s = String(sec % 60).padStart(2, '0');
        this.elapsedStr[presetName] = `${m}:${s}`;
      };
      const elapsedTimer = setInterval(updateElapsed, 1000);

      try {
        const resp = await fetch(`/api/run/${presetName}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ form_values: formValues }),
        });
        if (!resp.ok) {
          throw new Error(`${resp.status} ${resp.statusText}`);
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // SSE 事件以 \n\n 分隔
          let idx;
          while ((idx = buffer.indexOf('\n\n')) >= 0) {
            const block = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            this.handleSSEEvent(presetName, block);
          }
        }
      } catch (e) {
        this.runState[presetName] = 'failure';
        this.statusMsg[presetName] = '运行失败: ' + e.message;
      } finally {
        clearInterval(elapsedTimer);
        updateElapsed();
        // running 状态没被 SSE 改成 success/failure 的话, 兜底设 failure
        if (this.runState[presetName] === 'running') {
          this.runState[presetName] = 'failure';
        }
      }
    },

    handleSSEEvent(presetName, block) {
      // block 形如 "data: {...}"
      for (const line of block.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') continue;
        let ev;
        try { ev = JSON.parse(payload); } catch { continue; }

        if (ev.log) this.runLogs[presetName] = ev.log;
        if (ev.status_msg) this.statusMsg[presetName] = ev.status_msg;
        if (ev.media_html) this.resultHtml[presetName] = ev.media_html;
        if (ev.error_html) this.errorHtml[presetName] = ev.error_html;
        if (ev.state && ev.state !== 'running') {
          this.runState[presetName] = ev.state;
        }
      }
    },

    collectFormValues(panel) {
      // 从 panel.__x.$data.formValues 收集成扁平 list (按 spec 顺序)
      const cfg = panel.__x.$data.presetCfg;
      const fv = panel.__x.$data.formValues;
      if (!cfg) return [];
      const out = [];
      let flatIdx = 0;
      for (const spec of cfg.user_facing_inputs) {
        if (spec.type === 'int_random') {
          out.push(fv[flatIdx + '_random'] ?? true);
          out.push(fv[flatIdx] ?? spec.default);
          flatIdx += 2;
        } else {
          out.push(fv[flatIdx] ?? spec.default);
          flatIdx += 1;
        }
      }
      return out;
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
