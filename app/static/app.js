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

function installThemeResponse(data) {
  const styleEl = document.getElementById('theme-injector');
  if (styleEl) styleEl.textContent = data.css.replace(/^<style[^>]*>/, '').replace(/<\/style>$/, '');
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  if (themeMeta && data.page_bg_color) themeMeta.setAttribute('content', data.page_bg_color);
  document.body.dataset.theme = data.theme_id;
}

function appShell() {
  return {
    currentTab: window.location.pathname.startsWith('/settings') ? 'settings'
             : window.location.pathname.startsWith('/wizard') ? 'wizard'
             : 'run',
    comfyStatusHtml: '',         // 兼容旧调用方 (systemStatusHtml getter 还在)
    pending: false,
    // status pill (顶部菜单栏右侧) 用的派生数据
    comfyStatusState: 'loading',   // loading | ok | err
    comfyStatusUrl: '',            // e.g. http://127.0.0.1:8188
    comfyStatusLabel: '',          // e.g. ComfyUI · 8188
    get systemStatusHtml() {
      return this.comfyStatusHtml || '<span class="system-status-empty">检测 ComfyUI 状态中…</span>';
    },
    get comfyStatusClass() {
      return { ok: 'status-pill-ok', err: 'status-pill-err', loading: 'status-pill-loading' }[this.comfyStatusState] || '';
    },
    get comfyStatusShort() {
      if (this.comfyStatusState === 'loading') return 'ComfyUI 检测中…';
      return this.comfyStatusLabel || 'ComfyUI';
    },
    get comfyStatusTitle() {
      if (this.comfyStatusState === 'err') return 'ComfyUI 状态获取失败 (HTTP 不可达)';
      return this.comfyStatusUrl || '';
    },

    async init() {
      await this.refreshStatus();
      setInterval(() => this.refreshStatus(), 30000);
    },

    async refreshStatus() {
      try {
        const s = await fetchJSON('/api/comfy_status');
        this.comfyStatusHtml = 'ComfyUI: ' + s.dot + ' <code>' + s.url + '</code>';
        this.comfyStatusUrl = s.url || '';
        this.comfyStatusLabel = s.url || 'ComfyUI';
        this.comfyStatusState = s.ok ? 'ok' : 'err';
      } catch (e) {
        this.comfyStatusHtml = 'ComfyUI: <span class="err">状态获取失败</span>';
        this.comfyStatusUrl = '';
        this.comfyStatusLabel = 'ComfyUI 不可达';
        this.comfyStatusState = 'err';
      }
    },



    // 主题切换 helper (settings tab 也复用)
    async applyTheme(themeId) {
      const data = await fetchJSON('/api/theme', {
        method: 'POST',
        body: JSON.stringify({ theme_id: themeId }),
      });
      installThemeResponse(data);
      return data;
    },
  };
}


// ============================================================
// runTab — 运行 tab
// ============================================================

function panelData(panel) {
  if (!panel) return null;
  if (window.Alpine && Alpine.$data) return Alpine.$data(panel);
  return panel.__x ? panel.__x.$data : null;
}

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
    audioExts: '.mp3,.wav,.m4a,.flac,.ogg',

    async init() {
      this.refreshStatus();
    },

    async initPanelScope(name, scope) {
      this.activePanel = scope && scope.$el ? scope.$el : null;

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
        this._seedImageSizesCustomKeys(fv, cfg);
        scope.formValues = fv;
        for (let i = 0; i < cfg.user_facing_inputs.length; i++) {
          const spec = cfg.user_facing_inputs[i];
          if (spec.type === 'image_sizes' && Array.isArray(fv[i]) && fv[i].length === 0 && Array.isArray(spec.presets) && spec.presets.length) {
            const first = spec.presets[0];
            const val = typeof first === 'object' ? first.value : first;
            fv[i] = [val];
          }
        }
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
          scope.defaultResultHtml = `<div style="padding:8px"><img src="${cfg.preview_url}" loading="lazy" style="max-width:100%;max-height:70vh;object-fit:contain;border-radius:var(--radius-md);display:block;margin:0 auto" /></div>${caption}`;
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
      this._seedImageSizesCustomKeys(formValues, cfg);
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

    // 把 preset 的 user_facing_inputs 按 tier 分成两组, 保留原 idx
    // (idx 是 spec 在原数组里的位置, formValues/collectFormValues 按它读写, 不能因分组而变)
    // 不管 spec 数组里 tier 是否有序, 渲染时都是 basic 在前、advanced 折叠在后.
    basicInputs(cfg) {
      if (!cfg || !cfg.user_facing_inputs) return [];
      return cfg.user_facing_inputs
        .map((spec, idx) => ({ spec, idx }))
        .filter(({ spec }) => (spec.tier || 'basic') === 'basic');
    },

    advancedInputs(cfg) {
      if (!cfg || !cfg.user_facing_inputs) return [];
      return cfg.user_facing_inputs
        .map((spec, idx) => ({ spec, idx }))
        .filter(({ spec }) => spec.tier === 'advanced');
    },

    // 分组列表: [{tier:'basic', items:[...]}, {tier:'advanced', items:[...]}]
    // 没有 advanced 字段时只返回 basic 一组 (模板里不渲染 details 折叠区).
    groupedInputs(cfg) {
      const basic = this.basicInputs(cfg);
      const advanced = this.advancedInputs(cfg);
      const groups = [{ tier: 'basic', items: basic }];
      if (advanced.length > 0) {
        groups.push({ tier: 'advanced', items: advanced });
      }
      return groups;
    },

    fillPresetPanel(name, cfg, values) {
      // 兼容旧调用 (loadExample / loadLastRun 用)
      const panel = document.querySelector(`[data-preset="${name}"]`);
      if (!panel || !panel.__x) return;
      this._applyFormValues(panel, cfg, values);
    },

    sizeValue(opt) { return typeof opt === 'object' ? opt.value : opt; },
    sizeLabel(opt) { return typeof opt === 'object' ? opt.label : opt; },
    sizeChecked(opt, idx) {
      const val = this.sizeValue(opt);
      const panels = Array.from(document.querySelectorAll('[data-preset]'));
      for (const panel of panels) {
        const data = panelData(panel);
        if (!data || !Array.isArray(data.formValues)) continue;
        const list = data.formValues[idx];
        if (Array.isArray(list) && list.includes(val)) return true;
      }
      return false;
    },

    getExampleThumbUrl(presetName, specIdx) {
      // 从 panel 的 formValues[specIdx] 提取缩略图 URL.
      // form_schema.example_to_form_values 返回 "app/static/examples/<name>" (review 2026-07-28
      // 起统一从项目仓库读, 不再去 ComfyUI input 翻), 前端通过 /example_thumb/<basename>
      // 路由读取本地文件展示. 该路由只查 app/static/examples/, 见 flask_app.example_thumb.
      // 历史 manifest 侧车里可能存的是绝对路径或裸 basename, 也取 basename 兼容.
      const panel = document.querySelector("[data-preset=\"" + presetName + "\"]");
      if (!panel) return "";
      const data = Alpine.$data(panel);
      const v = data.formValues[specIdx];
      if (!v) return "";
      const basename = v.replace(/\\/g, "/").split("/").pop();
      if (!basename) return "";
      return "/example_thumb/" + encodeURIComponent(basename);
    },

    async onFileSelect(event, presetName, specIdx, kind) {
      // 步骤 5: 真正上传到 ComfyUI, 把返回的 name 存进 formValues.
      // run_workflow 的 _resolve_upload_name 会识别它在 ComfyUI input 目录, 跳过重复上传.
      const file = event.target.files[0];
      if (!file) return;
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;

      // 先用本地文件名占位, 显示"上传中"
      panelData(panel).formValues[specIdx] = file.name + ' (上传中…)';

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
        panelData(panel).formValues[specIdx] = data.name;
      } catch (e) {
        panelData(panel).formValues[specIdx] = '';
        alert('上传失败: ' + e.message);
      }
    },

    clearFile(presetName, specIdx) {
      // 用户点清除框后, 文件位置释放, run 时跳过对应 spec.
      // 不是“删除文件”, 只是不用这个输入了.
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;
      panelData(panel).formValues[specIdx] = '';
    },

    onSizeToggle(event, presetName, specIdx) {
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;
      const checked = event.target;
      const value = checked.value;
      // 多选: formValues[idx] 是 ["WxH", ...] 字符串数组, runner image 路径按每个尺寸各跑一张.
      // 勾上 -> 加入列表 (去重), 不替换; 取消 -> 只移除该项, 保留其它.
      const current = panelData(panel).formValues[specIdx] || [];
      if (checked.checked) {
        panelData(panel).formValues[specIdx] =
          current.includes(value) ? current : [...current, value];
      } else {
        panelData(panel).formValues[specIdx] =
          current.filter((item) => item !== value);
      }
    },

    async randomPrompt(presetName, specIdx, n) {
      try {
        const url = n > 1 ? `/api/random_prompt?n=${n}` : '/api/random_prompt';
        const data = await fetchJSON(url);
        const panel = document.querySelector(`[data-preset="${presetName}"]`);
        if (panel) panelData(panel).formValues[specIdx] = data.prompt;
      } catch (e) {
        console.error('randomPrompt failed:', e);
      }
    },

    async loadExample(presetName) {
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;
      const cfg = panelData(panel)?.presetCfg;
      if (!cfg) return;
      const values = await fetchJSON(`/api/example/${presetName}`);
      this._applyFormValues(panel, cfg, values);
    },

    async loadLastRun(presetName) {
      const panel = document.querySelector(`[data-preset="${presetName}"]`);
      if (!panel) return;
      const cfg = panelData(panel)?.presetCfg;
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
      const cfg = panelData(panel)?.presetCfg;
      const outputKind = cfg?.output_kind || 'video';

      this.runState[presetName] = 'running';
      this.statusMsg[presetName] = '';
      this.errorHtml[presetName] = '';
      this.runLogs[presetName] = '';
      this.resultHtml[presetName] = '<div class="result-placeholder">正在生成新结果…</div>';

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

    // === image_sizes 自定义 WxH 字段 helpers ===
    //
    // 数据模型 (formValues):
    //   - formValues[idx]              : ["WxH", ...] 主数组, runner 直接吃
    //   - formValues[idx + '_custom_on']: bool, 自定义卡片是否勾上
    //   - formValues[idx + '_cw']      : number, 自定义宽度
    //   - formValues[idx + '_ch']      : number, 自定义高度
    //
    // 三个 _custom_on / _cw / _ch 辅助键必须在 initPanelScope + _applyFormValues
    // 初始化时就建好 (Alpine 3 Proxy 不追踪后加的 key, 必须预建).
    // _seedImageSizesCustomKeys 在两条路径都调.

    _parseWxH(s) {
      if (!s || typeof s !== 'string') return null;
      const m = s.match(/^(\d+)\s*[x\u00d7]\s*(\d+)$/);
      return m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : null;
    },

    _presetValuesFor(spec) {
      return (spec.presets || []).map(p => typeof p === 'object' ? p.value : p);
    },

    _seedImageSizesCustomKeys(fv, cfg) {
      // 对 cfg.user_facing_inputs 里的 image_sizes spec:
      //   - 预建 _custom_on / _cw / _ch 三个键 (Alpine 响应式前提)
      //   - 若 formValues[idx] 含不在 spec.presets 里的值, 自动点亮自定义 + 填 W/H
      const inputs = cfg.user_facing_inputs || [];
      for (let i = 0; i < inputs.length; i++) {
        const spec = inputs[i];
        if (spec.type !== 'image_sizes') continue;
        const presetValues = this._presetValuesFor(spec);
        const list = Array.isArray(fv[i]) ? fv[i] : [];
        // 找一个不在 presetValues 里的值 (作为自定义的种子)
        const customSeed = list.find(v => !presetValues.includes(v));
        // 预建三个键 (Alpine 3 Proxy 必须显式 set 才能追踪)
        if (fv[i + '_custom_on'] === undefined) fv[i + '_custom_on'] = !!customSeed;
        if (fv[i + '_cw'] === undefined) fv[i + '_cw'] = customSeed ? (this._parseWxH(customSeed)?.[0] ?? null) : null;
        if (fv[i + '_ch'] === undefined) fv[i + '_ch'] = customSeed ? (this._parseWxH(customSeed)?.[1] ?? null) : null;
      }
    },

    customChecked(presetName, specIdx) {
      const panel = document.querySelector('[data-preset="' + presetName + '"]');
      if (!panel) return false;
      const fv = panelData(panel).formValues;
      return !!fv[specIdx + '_custom_on'];
    },

    customW(presetName, specIdx) {
      const panel = document.querySelector('[data-preset="' + presetName + '"]');
      if (!panel) return '';
      const fv = panelData(panel).formValues;
      return fv[specIdx + '_cw'] ?? '';
    },

    customH(presetName, specIdx) {
      const panel = document.querySelector('[data-preset="' + presetName + '"]');
      if (!panel) return '';
      const fv = panelData(panel).formValues;
      return fv[specIdx + '_ch'] ?? '';
    },

    onCustomToggle(event, presetName, specIdx) {
      // 勾 / 取消自定义卡片:
      //  勾上: 预填 _cw / _ch (从当前主数组第一个非 preset 的值, 或第一个 preset),
      //        把 "W x H" 推进 formValues[idx] (去重)
      //  取消: 把 "W x H" 从 formValues[idx] 摘掉, 清 _cw / _ch
      const panel = document.querySelector('[data-preset="' + presetName + '"]');
      if (!panel) return;
      const data = panelData(panel);
      const fv = data.formValues;
      const cfg = data.presetCfg;
      const spec = cfg.user_facing_inputs[specIdx];
      const presetValues = this._presetValuesFor(spec);
      const list = Array.isArray(fv[specIdx]) ? fv[specIdx] : [];
      const checked = !!event.target.checked;
      fv[specIdx + '_custom_on'] = checked;
      if (checked) {
        // 预填 _cw / _ch
        if (!fv[specIdx + '_cw'] || !fv[specIdx + '_ch']) {
          // 优先复用当前数组里非 preset 的值, 没有再用第一个 preset
          const seed = list.find(v => !presetValues.includes(v)) || presetValues[0];
          const wh = this._parseWxH(seed);
          if (wh) { fv[specIdx + '_cw'] = wh[0]; fv[specIdx + '_ch'] = wh[1]; }
        }
        // 把 "W x H" 推进主数组
        const tag = fv[specIdx + '_cw'] + 'x' + fv[specIdx + '_ch'];
        if (fv[specIdx + '_cw'] && fv[specIdx + '_ch'] && !list.includes(tag)) {
          fv[specIdx] = [...list, tag];
        }
      } else {
        // 把当前 "W x H" 摘掉
        const tag = fv[specIdx + '_cw'] + 'x' + fv[specIdx + '_ch'];
        fv[specIdx] = list.filter(v => v !== tag);
        fv[specIdx + '_cw'] = null;
        fv[specIdx + '_ch'] = null;
      }
    },

    onCustomSizeInput(event, presetName, specIdx, which) {
      // 用户在自定义 W/H 输入框改值, 实时:
      //  - 更新 _cw / _ch
      //  - 把新 "W x H" 写进 formValues[idx] (替换旧的 custom 项)
      const panel = document.querySelector('[data-preset="' + presetName + '"]');
      if (!panel) return;
      const data = panelData(panel);
      const fv = data.formValues;
      const cfg = data.presetCfg;
      const spec = cfg.user_facing_inputs[specIdx];
      const presetValues = this._presetValuesFor(spec);
      const v = event.target.value === '' ? null : parseInt(event.target.value, 10);
      const list = Array.isArray(fv[specIdx]) ? fv[specIdx] : [];
      // 记住旧 custom 的 tag (要替换)
      const oldTag = (fv[specIdx + '_cw'] && fv[specIdx + '_ch']) ? (fv[specIdx + '_cw'] + 'x' + fv[specIdx + '_ch']) : null;
      if (which === 'w') fv[specIdx + '_cw'] = v;
      else fv[specIdx + '_ch'] = v;
      const newTag = (fv[specIdx + '_cw'] && fv[specIdx + '_ch']) ? (fv[specIdx + '_cw'] + 'x' + fv[specIdx + '_ch']) : null;
      // 替换主数组里的 custom 项
      let next = list;
      if (oldTag && newTag && oldTag !== newTag) {
        next = list.map(x => x === oldTag ? newTag : x);
      } else if (newTag && !oldTag) {
        next = [...list, newTag];
      } else if (!newTag && oldTag) {
        next = list.filter(x => x !== oldTag);
      }
      fv[specIdx] = next.filter(x => x && !presetValues.includes(x) || presetValues.includes(x));
    },

    collectFormValues(panel) {
      // 从 panelData(panel).formValues 收集成扁平 list (按 spec 顺序)
      const cfg = panelData(panel)?.presetCfg;
      const fv = panelData(panel).formValues;
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
      // 并行拆 3 个独竆请求 (comfy_status + themes + theme).
      // 之前串行实现在主机上走 ~6 秒才能看到主题列表.
      // 现在三者并行, 总耗时 = max(50ms, 50ms, 2ms) ≈ 50ms.
      // 只拉 themes 和 theme. comfy_status 由 appShell 处理, 不重拉 (同一个接口会走 check_connection(timeout=2), 双拉一起后面的请求都要排队 2 秒).
      const [themes, cur] = await Promise.all([
        fetchJSON('/api/themes').catch(() => []),
        fetchJSON('/api/theme').catch(() => ({ theme_id: '', desc: '' })),
      ]);
      // url 从 appShell 的 comfyStatusHtml 反推 (调用 /api/comfy_status 也会重走连接检查的 2 秒超时).
      this.url = (window.Alpine && document.body._x_dataStack && document.body._x_dataStack[0] && document.body._x_dataStack[0].comfyStatusUrl) || '';
      this.themes = themes || [];
      this.currentThemeId = (cur && cur.theme_id) || '';
      this.themeDesc = (cur && cur.desc) || '';
      // themes 加载完成后, 还要为每个主题设 currentThemeId 默认 (首次访问时为空)
      if (!this.currentThemeId && this.themes.length > 0) {
        this.currentThemeId = this.themes[0].id;
      }
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
      // 模态弹窗: 完成 (或失败) 时调 showModal() 弹出. dialog 元素来自 settings.html 的 <dialog>.
      const dlg = document.querySelector('.health-modal');
      if (dlg && typeof dlg.showModal === 'function') dlg.showModal();
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
        installThemeResponse(data);
        this.themeDesc = data.desc;
      } catch (e) {
        this.statusMsg = '主题切换失败: ' + e.message;
      }
    },
  };
}


// ============================================================
// wizardTab — 工作流向导 (wizard.html)
// 3 步: 上传 workflow → 确认输入项 → 跑一次选输出 → 保存
// ============================================================

function wizardTab() {
  return {
    step: 1,
    token: '',
    fields: [],
    nodeCount: 0,
    fieldsSummary: '',
    parsing: false,
    uploadError: '',

    wizardMode: 'new',
    editableWorkflows: [],
    editPreset: '',
    editItems: [],
    editCanRestore: false,
    editDirty: false,
    editLoading: false,
    editSaving: false,
    editStatus: '',
    editDragIndex: null,

    // 排序模式: editableWorkflows 镜像 (用户拖拽后只动 orderItems, 不动 editableWorkflows,
    // 这样切回 edit tab 时下拉框还是原始顺序, 避免下拉里出现一份跟列表对不上的 ghost)
    orderItems: [],
    orderDirty: false,
    orderSaving: false,
    orderLoading: false,
    orderStatus: '',
    orderDragIndex: null,

    // 步骤 3: 运行 + 输出选择
    running: false,
    runError: '',
    outputs: [],
    selectedOutput: null,
    runValues: {},

    // 保存表单
    saveName: '',
    saveDisplayName: '',
    saveCategory: 'image',
    saveDescription: '',
    saving: false,
    saveMsg: '',
    saveError: '',

    init() {},

    async setWizardMode(mode) {
      this.wizardMode = mode;
      if ((mode === 'edit' || mode === 'order') && this.editableWorkflows.length === 0) {
        try { this.editableWorkflows = await fetchJSON('/api/wizard/editable-workflows'); }
        catch (e) {
          if (mode === 'edit') this.editStatus = '加载工作流列表失败: ' + e.message;
          else this.orderStatus = '加载工作流列表失败: ' + e.message;
        }
      }
      if (mode === 'order') this.loadOrder();
    },

    // category 显示名 (跟原 order 一致: image=图, video=视频, audio=音频, 其它=其它)
    categoryLabel(cat) {
      return ({ image: '图', video: '视频', audio: '音频' })[cat] || '其它';
    },

    // 排序模式: 从 editableWorkflows (已按 order 排序) 拉一份镜像
    async loadOrder() {
      if (!this.editableWorkflows.length) return;
      this.orderLoading = true;
      try {
        this.orderItems = this.editableWorkflows.map(w => ({ name: w.name, display_name: w.display_name, category: w.category }));
        this.orderDirty = false;
        this.orderStatus = '';
      } finally { this.orderLoading = false; }
    },

    markOrderDirty() { this.orderDirty = true; this.orderStatus = '有未保存修改'; },

    moveOrderItem(idx, dir) {
      const next = idx + dir;
      if (next < 0 || next >= this.orderItems.length) return;
      const item = this.orderItems.splice(idx, 1)[0];
      this.orderItems.splice(next, 0, item); this.markOrderDirty();
    },

    startOrderDrag(idx) { this.orderDragIndex = idx; },
    dropOrderItem(idx) {
      const from = this.orderDragIndex; this.orderDragIndex = null;
      if (from == null || from === idx) return;
      const item = this.orderItems.splice(from, 1)[0];
      this.orderItems.splice(from < idx ? idx - 1 : idx, 0, item); this.markOrderDirty();
    },

    async saveOrder() {
      if (!this.orderItems.length || !this.orderDirty || this.orderSaving) return;
      this.orderSaving = true; this.orderStatus = '保存中…';
      try {
        await fetchJSON('/api/wizard/preset-order', {
          method: 'PUT',
          body: JSON.stringify({ order: this.orderItems.map(i => i.name) }),
        });
        this.orderDirty = false;
        this.orderStatus = '已保存, 运行页刷新后生效';
        // editableWorkflows 也跟着同步, 这样切回 edit tab 下拉顺序也对
        this.editableWorkflows = await fetchJSON('/api/wizard/editable-workflows');
        this.orderItems = this.editableWorkflows.map(w => ({ name: w.name, display_name: w.display_name, category: w.category }));
      } catch (e) { this.orderStatus = '保存失败: ' + e.message; }
      finally { this.orderSaving = false; }
    },

    async resetOrder() {
      // 撤销: 重新拉一份原始顺序
      this.editableWorkflows = await fetchJSON('/api/wizard/editable-workflows');
      await this.loadOrder();
      this.orderDirty = false;
      this.orderStatus = '已撤销修改';
    },

    async loadEditPreset() {
      this.editItems = []; this.editDirty = false; this.editStatus = ''; this.editCanRestore = false;
      if (!this.editPreset) return;
      this.editLoading = true;
      try {
        const data = await fetchJSON(`/api/wizard/definition/${this.editPreset}`);
        this.editItems = data.inputs.map(item => ({ ...item }));
        this.editCanRestore = Boolean(data.can_restore);
      } catch (e) { this.editStatus = '加载失败: ' + e.message; }
      finally { this.editLoading = false; }
    },

    markEditDirty() { this.editDirty = true; this.editStatus = '有未保存修改'; },

    moveEditItem(idx, dir) {
      const next = idx + dir;
      if (next < 0 || next >= this.editItems.length) return;
      const item = this.editItems.splice(idx, 1)[0];
      this.editItems.splice(next, 0, item); this.markEditDirty();
    },

    startEditDrag(idx) { this.editDragIndex = idx; },
    dropEditItem(idx) {
      const from = this.editDragIndex; this.editDragIndex = null;
      if (from == null || from === idx) return;
      const item = this.editItems.splice(from, 1)[0];
      this.editItems.splice(from < idx ? idx - 1 : idx, 0, item); this.markEditDirty();
    },

    async saveEditPreset() {
      if (!this.editPreset || !this.editDirty) return;
      this.editSaving = true;
      try {
        const data = await fetchJSON(`/api/wizard/definition/${this.editPreset}/inputs`, {
          method: 'PUT',
          body: JSON.stringify({ inputs: this.editItems.map(({ stable_id, label, tier, help }) => ({ stable_id, label, tier, help })) }),
        });
        this.editItems = data.inputs.map(item => ({ ...item }));
        this.editCanRestore = Boolean(data.can_restore); this.editDirty = false;
        this.editStatus = '已保存，刷新运行页后生效';
        this.editableWorkflows = await fetchJSON('/api/wizard/editable-workflows');
      } catch (e) { this.editStatus = '保存失败: ' + e.message; }
      finally { this.editSaving = false; }
    },

    async restoreEditPreset() {
      if (!this.editPreset || !this.editCanRestore) return;
      try {
        await fetchJSON(`/api/wizard/definition/${this.editPreset}/override`, { method: 'DELETE' });
        await this.loadEditPreset(); this.editStatus = '已恢复默认输入布局';
        this.editableWorkflows = await fetchJSON('/api/wizard/editable-workflows');
      } catch (e) { this.editStatus = '恢复失败: ' + e.message; }
    },

    // --- 步骤 1: 上传 ---
    async onUpload(event) {
      const file = event.target.files[0];
      if (!file) return;
      this.uploadError = '';
      this.parsing = true;
      this.fields = [];
      try {
        const text = await file.text();
        const data = await fetchJSON('/api/wizard/parse', {
          method: 'POST',
          body: JSON.stringify({ workflow_json: text }),
        });
        this.token = data.token;
        this.nodeCount = data.node_count;
        // 给每个字段加 enabled/tier (前端编辑用).
        // enabled 默认值由 confidence 决定:
        //   high   (LoadImage/视频/seed/尺寸) → 勾选 (明确是用户要改的)
        //   medium (提示词 CLIPTextEncode.text 长内容) → 勾选
        //   low    (裸 int/bool/短 text 兜底) → 不勾选 (语义不明, 等用户决定)
        this.fields = data.fields.map(f => {
          const conf = f.confidence || 'low';
          return {
            ...f,
            enabled: conf === 'high' || conf === 'medium',
            tier: f.tier || 'basic',
          };
        });
        const selCount = this.fields.filter(f => f.enabled).length;
        const totalCount = this.fields.length;
        this.fieldsSummary = `已勾选 ${selCount}/${totalCount} 个高置信度字段，其余请按需勾选`;
      } catch (e) {
        this.uploadError = '解析失败: ' + e.message;
      } finally {
        this.parsing = false;
      }
    },

    selectAllFields() {
      this.fields.forEach(f => f.enabled = true);
    },

    selectNoneFields() {
      this.fields.forEach(f => f.enabled = false);
    },

    // 调整字段顺序 (基础设置里用户可上下挪动). dir: -1 上移 / +1 下移.
    moveField(idx, dir) {
      const j = idx + dir;
      if (j < 0 || j >= this.fields.length) return;
      const tmp = this.fields[idx];
      this.fields.splice(idx, 1);
      this.fields.splice(j, 0, tmp);
    },

    // 格式化字段的当前值用于表格显示 (截断长字符串)
    formatValue(v) {
      if (v == null) return '';
      if (typeof v === 'boolean') return v ? 'true' : 'false';
      const s = String(v);
      return s.length > 60 ? s.slice(0, 60) + '…' : s;
    },

    goStep(n) {
      // 进步骤 3 (排序) 前, 把已选字段重排到数组前面, 未选的挪到后面.
      // 这样排序表格只显示前面已选的, moveField 在连续的已选段操作不会跳到隐藏字段.
      if (n === 3) {
        const selected = this.fields.filter(f => f.enabled);
        const unselected = this.fields.filter(f => !f.enabled);
        this.fields = [...selected, ...unselected];
      }
      this.step = n;
    },

    // --- 步骤 3 → 4: 跑一次 ---
    async goRun() {
      this.step = 4;
      this.running = true;
      this.runError = '';
      this.outputs = [];
      this.selectedOutput = null;
      try {
        const enabled = this.fields.filter(f => f.enabled);
        // values: 用每个字段的 default 填 (用户没在向导里改值, 跑一次只是看输出)
        const values = {};
        for (const f of enabled) {
          values[f.field] = f.default;
        }
        this.runValues = values;
        const data = await fetchJSON('/api/wizard/run', {
          method: 'POST',
          body: JSON.stringify({ token: this.token, fields: enabled, values }),
        });
        this.outputs = data.outputs;
        const finished = this.outputs.map((o, i) => o.type === 'output' ? i : -1).filter(i => i >= 0);
        if (finished.length === 1) this.selectedOutput = finished[0];
      } catch (e) {
        this.runError = '运行失败: ' + e.message;
      } finally {
        this.running = false;
      }
    },

    // 把一个输出产物渲染成 <img>/<video>/<audio> (按扩展名分桶)
    renderOutput(o) {
      const url = o.url;
      const ext = (o.filename.split('.').pop() || '').toLowerCase();
      if (['mp4', 'mov', 'webm', 'gif'].includes(ext)) {
        return `<video controls preload="metadata" style="max-width:100%;max-height:200px;border-radius:var(--radius-md)"><source src="${url}"/></video>`;
      }
      if (['mp3', 'wav', 'flac', 'ogg', 'm4a'].includes(ext)) {
        return `<audio controls preload="metadata" style="width:100%"><source src="${url}"/></audio>`;
      }
      // 图片 / 未知 → img
      return `<img src="${url}" loading="lazy" style="max-width:100%;max-height:200px;object-fit:contain;border-radius:var(--radius-md)">`;
    },

    // --- 步骤 3: 保存 ---
    async doSave() {
      this.saving = true;
      this.saveMsg = '';
      this.saveError = '';
      try {
        const enabled = this.fields.filter(f => f.enabled);
        const sel = this.outputs[this.selectedOutput];
        const data = await fetchJSON('/api/wizard/save', {
          method: 'POST',
          body: JSON.stringify({
            token: this.token,
            name: this.saveName.trim(),
            display_name: this.saveDisplayName.trim() || this.saveName.trim(),
            category: this.saveCategory,
            description: this.saveDescription.trim(),
            fields: enabled,
            output_node_id: sel ? sel.node_id : null,
            output_kind: sel ? this._kindFromMediaKey(sel.media_key, sel.filename) : 'video',
            selected_output: sel,
            values: this.runValues,
          }),
        });
        this.saveMsg = `✅ 已保存为 ${data.name}！刷新"运行"页即可在左侧看到这个工作流。`;
      } catch (e) {
        this.saveError = '保存失败: ' + e.message;
      } finally {
        this.saving = false;
      }
    },

    _kindFromMediaKey(mediaKey, filename) {
      if (mediaKey === 'images') return 'image';
      if (mediaKey === 'audio') return 'audio';
      if (mediaKey === 'videos' || mediaKey === 'gifs') return 'video';
      return 'video';
    },
  };
}
