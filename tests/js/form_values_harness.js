/* 前端表单值映射的 Node 测台 (只给 pytest 调, 不参与前端打包).
 *
 * 用法: node form_values_harness.js <payload.json> <app.js 路径>
 * payload.json: { preset, definition, exampleValues, lastRunValues?, edits? }
 * 输出 (stdout, 单行 JSON):
 *   { formValues: {...}, collected: [...], selects: [{idx, value}] }
 *
 * 测的是真 app.js:
 *   - initPanelScope 怎么把扁平表单值铺进 formValues (键 = spec 索引)
 *   - collectFormValues 怎么把它收回扁平数组 (顺序 = spec 顺序)
 *   - _syncModelSelects 怎么把模型下拉框的值摆正 (选项异步到, x-model 会落回第一项)
 */
const fs = require('fs');
const vm = require('vm');

const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const appJsPath = process.argv[3];

const responses = {
  [`/api/example/${payload.preset}`]: payload.exampleValues,
  [`/api/preset_models/${payload.preset}`]: { slots: [] },
};
if (payload.lastRunValues) {
  responses[`/api/last_run/${payload.preset}`] = payload.lastRunValues;
}

// 假 DOM: 只够跑表单值映射 + 模型下拉框摆正.
const panel = { __data: null, _selects: [] };
panel.getAttribute = (k) => (k === 'data-preset' ? payload.preset : null);
panel.querySelectorAll = (sel) => (sel === 'select[data-model-idx]' ? panel._selects : []);

const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  fetch: async (url) => {
    if (Object.prototype.hasOwnProperty.call(responses, url)) {
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify(responses[url]),
        json: async () => responses[url],
      };
    }
    return {
      ok: false,
      status: 404,
      statusText: 'Not Found',
      text: async () => '',
      json: async () => { throw new Error('404 ' + url); },
    };
  },
};
sandbox.window = { location: { pathname: '/' }, Alpine: { $data: (el) => el.__data } };
sandbox.Alpine = sandbox.window.Alpine;
sandbox.document = {
  querySelector: () => null,
  querySelectorAll: (sel) => (sel === `[data-preset="${payload.preset}"]` ? [panel] : []),
  addEventListener: () => {},
  getElementById: () => null,
  body: { dataset: {} },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(appJsPath, 'utf8'), sandbox);

const definition = payload.definition;
const app = sandbox.runTab([{ name: payload.preset }], { [payload.preset]: definition });

(async () => {
  // 每个 model spec 一个假 <select>
  const modelSpecs = definition.user_facing_inputs
    .map((spec, idx) => ({ spec, idx }))
    .filter(({ spec }) => spec.type === 'model');
  panel._selects = modelSpecs.map(({ idx }) => ({
    _idx: String(idx),
    value: '',
    getAttribute(name) { return name === 'data-model-idx' ? this._idx : null; },
  }));

  panel.__data = { presetCfg: definition, formValues: {} };
  await app.initPanelScope(payload.preset, panel.__data);
  // 模拟用户在控件里改值 (模板写 formValues[spec.idx])
  for (const [idx, value] of Object.entries(payload.edits || {})) {
    panel.__data.formValues[idx] = value;
  }
  // 等 setTimeout(0) 里的下拉框摆正跑完
  await new Promise((r) => setTimeout(r, 20));

  const result = {
    formValues: panel.__data.formValues,
    collected: app.collectFormValues(panel),
    selects: panel._selects.map((s) => ({ idx: s._idx, value: s.value })),
  };
  process.stdout.write(JSON.stringify(result));
})().catch((e) => {
  process.stderr.write(String(e && e.stack ? e.stack : e));
  process.exit(1);
});
