// AgentMesh Workstation SPA — Phase C full implementation
// Vanilla JS, no framework. Loaded as ES module.

// ═══════════════════════════════════════════════════════════════════════════
// §0 — Utilities
// ═══════════════════════════════════════════════════════════════════════════

const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const $ = (sel) => document.querySelector(sel);

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  return res.json();
}

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) Object.entries(attrs).forEach(([k, v]) => {
    // Skip null / undefined attributes — avoids accidentally setting
    // `disabled="null"` which always disables the button in HTML.
    if (v === null || v === undefined) return;
    if (k === "className") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2).toLowerCase(), v);
    else node.setAttribute(k, v);
  });
  children.flat().forEach(c => {
    if (c == null) return;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return node;
}

function debounce(fn, ms) {
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ═══════════════════════════════════════════════════════════════════════════
// §0.1 — Tab router
// ═══════════════════════════════════════════════════════════════════════════

function switchTab(name) {
  $$("[data-tab]").forEach(btn => btn.classList.toggle("active", btn.dataset.tab === name));
  $$(".pane").forEach(p => p.classList.toggle("hidden", p.dataset.pane !== name));
  // Lazy-load panel content on first visit
  if (name === "commands" && !CommandForm._loaded) CommandForm.init();
  if (name === "recipes" && !RecipePanel._loaded) RecipePanel.init();
  if (name === "skills" && !SkillsPanel._loaded) SkillsPanel.init();
}

$$("[data-tab]").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// ═══════════════════════════════════════════════════════════════════════════
// §1 — C2: Command Form
// ═══════════════════════════════════════════════════════════════════════════

const CommandForm = {
  _loaded: false,
  _schemas: [],
  _activeSchema: null,
  _editMode: "form", // "form" | "textarea"
  _textareaValue: "",

  async init() {
    this._loaded = true;
    const root = $("#command-form-root");
    root.innerHTML = '<p class="loading">加载命令 schema…</p>';
    try {
      const resp = await api("GET", "/commands/schemas");
      this._schemas = resp.data.schemas || [];
      this.render(root);
    } catch (e) {
      root.innerHTML = `<p class="error">加载失败: ${e.message}</p>`;
    }
  },

  render(root) {
    root.innerHTML = "";
    // Category filter + command selector
    const categories = [...new Set(this._schemas.map(s => s.category))].sort();
    const toolbar = el("div", { className: "cmd-toolbar" },
      el("select", { className: "cmd-category-select", onChange: () => this._onCategoryChange() },
        el("option", { value: "" }, "全部分类"),
        ...categories.map(c => el("option", { value: c }, c))
      ),
      el("select", { className: "cmd-schema-select", onChange: () => this._onSchemaSelect() },
        el("option", { value: "" }, "— 选择命令 —"),
        ...this._schemas.map(s => el("option", { value: s.id }, `${s.title} (${s.id})`))
      ),
      el("button", { className: "btn btn-sm btn-toggle", onClick: () => this._toggleMode() }, "切换自由编辑")
    );
    root.appendChild(toolbar);

    // Form area
    root.appendChild(el("div", { className: "cmd-form-area" }));
    // Preview area
    root.appendChild(el("div", { className: "cmd-preview-area" }));
    // Execute button area
    root.appendChild(el("div", { className: "cmd-exec-area" }));
  },

  _onCategoryChange() {
    const cat = $(".cmd-category-select").value;
    const sel = $(".cmd-schema-select");
    sel.innerHTML = "";
    sel.appendChild(el("option", { value: "" }, "— 选择命令 —"));
    const filtered = cat ? this._schemas.filter(s => s.category === cat) : this._schemas;
    filtered.forEach(s => sel.appendChild(el("option", { value: s.id }, `${s.title} (${s.id})`)));
    this._activeSchema = null;
    $(".cmd-form-area").innerHTML = "";
    $(".cmd-preview-area").innerHTML = "";
    $(".cmd-exec-area").innerHTML = "";
  },

  _onSchemaSelect() {
    const id = $(".cmd-schema-select").value;
    this._activeSchema = this._schemas.find(s => s.id === id) || null;
    this._editMode = "form";
    this._textareaValue = "";
    this._renderForm();
  },

  _toggleMode() {
    if (!this._activeSchema) return;
    this._editMode = this._editMode === "form" ? "textarea" : "form";
    this._renderForm();
  },

  _renderForm() {
    const area = $(".cmd-form-area");
    const previewArea = $(".cmd-preview-area");
    const execArea = $(".cmd-exec-area");
    area.innerHTML = "";
    previewArea.innerHTML = "";
    execArea.innerHTML = "";
    if (!this._activeSchema) return;

    const schema = this._activeSchema;

    if (this._editMode === "textarea") {
      const ta = el("textarea", {
        className: "cmd-textarea",
        rows: "4",
        placeholder: `输入完整命令，如: ${schema.command} --flag value`
      });
      ta.value = this._textareaValue || schema.command + " ";
      ta.addEventListener("input", () => { this._textareaValue = ta.value; });
      area.appendChild(el("div", { className: "cmd-textarea-wrap" },
        el("label", { className: "form-label" }, "自由编辑命令:"),
        ta
      ));
      execArea.appendChild(this._makeExecButton(() => this._textareaValue.trim()));
      return;
    }

    // Form mode
    const desc = el("p", { className: "cmd-desc" }, schema.description);
    area.appendChild(desc);

    if (schema.destructive) {
      area.appendChild(el("div", { className: "cmd-warn" }, "⚠️ 此命令具有破坏性，执行前需确认"));
    }

    const formEl = el("div", { className: "cmd-fields" });
    schema.params.forEach(p => {
      formEl.appendChild(this._renderParam(p));
    });
    area.appendChild(formEl);

    // Resolve dynamic options (options_endpoint) for select/multi-select
    this._resolveDynamicOptions(schema);

    // Apply initial visible_when state
    this._applyVisibility(schema);

    // Live preview with debounce
    const doPreview = debounce(() => this._fetchPreview(), 400);
    area.addEventListener("input", (e) => { this._applyVisibility(schema); doPreview(); });
    area.addEventListener("change", (e) => { this._applyVisibility(schema); doPreview(); });

    // Exec button
    execArea.appendChild(this._makeExecButton(() => $(".cmd-preview-cmd")?.textContent || ""));

    // Trigger first preview
    this._fetchPreview();
  },

  _renderParam(p) {
    const wrap = el("div", { className: "form-field" });
    // Store visible_when expression as data attribute for evaluation
    if (p.visible_when) wrap.setAttribute("data-visible-when", p.visible_when);
    wrap.setAttribute("data-field-name", p.name);

    const label = el("label", { className: "form-label" }, p.label || p.name);
    if (p.required) label.appendChild(el("span", { className: "required" }, " *"));
    wrap.appendChild(label);

    if (p.help) wrap.appendChild(el("span", { className: "form-help" }, p.help));

    let input;
    switch (p.type) {
      case "boolean":
        input = el("input", { type: "checkbox", "data-param": p.name, className: "form-check" });
        if (p.default === true) input.checked = true;
        break;
      case "select":
        input = el("select", { "data-param": p.name, className: "form-select" },
          el("option", { value: "" }, "— 请选择 —"),
          ...(p.options || []).map(o => el("option", { value: o.value }, o.label || o.value))
        );
        if (p.options_endpoint) input.setAttribute("data-options-endpoint", p.options_endpoint);
        if (p.default) input.value = p.default;
        break;
      case "multi-select":
        input = el("select", { "data-param": p.name, className: "form-select", multiple: "true" },
          ...(p.options || []).map(o => el("option", { value: o.value }, o.label || o.value))
        );
        if (p.options_endpoint) input.setAttribute("data-options-endpoint", p.options_endpoint);
        if (p.default) {
          const defaults = Array.isArray(p.default) ? p.default : p.default.split(",");
          [...input.options].forEach(opt => { if (defaults.includes(opt.value)) opt.selected = true; });
        }
        break;
      case "integer":
        input = el("input", { type: "number", "data-param": p.name, className: "form-input", placeholder: p.help || "" });
        if (p.default != null) input.value = p.default;
        break;
      case "text":
        input = el("textarea", { "data-param": p.name, className: "form-textarea", rows: "3", placeholder: p.help || "" });
        if (p.default) input.value = p.default;
        break;
      default: // string, path
        input = el("input", { type: "text", "data-param": p.name, className: "form-input", placeholder: p.help || "" });
        if (p.default) input.value = p.default;
    }
    wrap.appendChild(input);
    return wrap;
  },

  /**
   * C6: Resolve dynamic options from options_endpoint.
   * For select/multi-select params that have options_endpoint set,
   * fetches the endpoint and populates the <select> with live data.
   */
  async _resolveDynamicOptions(schema) {
    for (const p of schema.params) {
      if (!p.options_endpoint) continue;
      const input = $(`[data-param="${p.name}"]`);
      if (!input) continue;
      try {
        const resp = await api("GET", p.options_endpoint);
        if (resp.status !== "ok" || !resp.data) continue;
        // Extract option values from response data.
        // Common patterns: resp.data.agents (array of {name,...}), resp.data.skills (array of strings)
        let items = [];
        if (resp.data.agents) {
          items = resp.data.agents.map(a => ({ value: a.name, label: a.name + (a.installed ? "" : " (未安装)") }));
        } else if (resp.data.skills) {
          items = resp.data.skills.map(s => typeof s === "string" ? { value: s, label: s } : { value: s.name, label: s.name });
        } else if (Array.isArray(resp.data)) {
          items = resp.data.map(v => typeof v === "string" ? { value: v, label: v } : { value: v.name || v.id || String(v), label: v.name || v.label || String(v) });
        }
        if (!items.length) continue;

        // Preserve current selection
        const currentVal = p.type === "multi-select"
          ? [...input.selectedOptions].map(o => o.value)
          : input.value;

        // Clear and repopulate
        input.innerHTML = "";
        if (p.type === "select") {
          input.appendChild(el("option", { value: "" }, "— 请选择 —"));
        }
        items.forEach(item => {
          input.appendChild(el("option", { value: item.value }, item.label));
        });

        // Restore selection
        if (p.type === "multi-select" && Array.isArray(currentVal)) {
          [...input.options].forEach(opt => { opt.selected = currentVal.includes(opt.value); });
        } else if (currentVal) {
          input.value = currentVal;
        }
        // Apply default if nothing was selected
        if (!input.value && p.default) input.value = p.default;
      } catch (e) {
        // Silently fail — keep whatever static options were there
        console.warn(`Failed to fetch options from ${p.options_endpoint}:`, e);
      }
    }
  },

  /**
   * C6: Apply visible_when conditional visibility.
   * Evaluates simple expressions like "dry_run == false", "mode == 'symlink'"
   * and shows/hides fields accordingly.
   */
  _applyVisibility(schema) {
    const values = this._gatherValues();
    schema.params.forEach(p => {
      if (!p.visible_when) return;
      const field = $(`.form-field[data-field-name="${p.name}"]`);
      if (!field) return;
      const visible = this._evalVisibleWhen(p.visible_when, values);
      field.style.display = visible ? "" : "none";
    });
  },

  /**
   * Evaluate a visible_when expression string against current values.
   * Supports: "field == value", "field == 'string'", "field == true/false"
   * Also supports "field != value" as the negation.
   */
  _evalVisibleWhen(expr, values) {
    // Support "a == b" and "a != b"
    let match = expr.match(/^\s*(\w+)\s*(==|!=)\s*(.+)\s*$/);
    if (!match) return true; // Can't parse → show
    const [, field, op, rawVal] = match;
    const actual = values[field];
    // Parse expected value
    let expected;
    const trimmed = rawVal.trim();
    if (trimmed === "true") expected = true;
    else if (trimmed === "false") expected = false;
    else if (/^\d+$/.test(trimmed)) expected = parseInt(trimmed, 10);
    else expected = trimmed.replace(/^['"]|['"]$/g, ""); // strip quotes

    let result;
    if (typeof expected === "boolean") {
      // Compare with boolean coercion
      const boolActual = actual === true || actual === "true" || actual === 1;
      result = boolActual === expected;
    } else {
      result = String(actual ?? "") === String(expected);
    }
    return op === "==" ? result : !result;
  },

  _gatherValues() {
    const values = {};
    const schema = this._activeSchema;
    if (!schema) return values;
    schema.params.forEach(p => {
      const input = $(`[data-param="${p.name}"]`);
      if (!input) return;
      if (p.type === "boolean") {
        values[p.name] = input.checked;
      } else if (p.type === "multi-select") {
        values[p.name] = [...input.selectedOptions].map(o => o.value);
      } else if (p.type === "integer") {
        if (input.value !== "") values[p.name] = parseInt(input.value, 10);
      } else {
        if (input.value !== "") values[p.name] = input.value;
      }
    });
    return values;
  },

  async _fetchPreview() {
    if (!this._activeSchema) return;
    const previewArea = $(".cmd-preview-area");
    const values = this._gatherValues();
    try {
      const resp = await api("POST", "/commands/plan", { command_id: this._activeSchema.id, values });
      if (resp.status === "ok") {
        const cmd = resp.data.command;
        this._textareaValue = cmd;
        previewArea.innerHTML = "";
        previewArea.appendChild(el("div", { className: "cmd-preview" },
          el("span", { className: "cmd-preview-label" }, "预览:"),
          el("code", { className: "cmd-preview-cmd" }, cmd)
        ));
        if (resp.warnings && resp.warnings.length) {
          previewArea.appendChild(el("div", { className: "cmd-preview-warn" }, resp.warnings.join("; ")));
        }
      } else {
        previewArea.innerHTML = "";
        previewArea.appendChild(el("div", { className: "cmd-preview cmd-preview-err" },
          el("span", null, "错误: " + (resp.errors || []).join("; "))
        ));
      }
    } catch (e) {
      previewArea.innerHTML = `<div class="cmd-preview cmd-preview-err">网络错误</div>`;
    }
  },

  _makeExecButton(getCmdFn) {
    const wrap = el("div", { className: "cmd-exec-wrap" });
    const btn = el("button", { className: "btn btn-primary", onClick: async () => {
      const cmd = getCmdFn();
      if (!cmd) return;
      if (this._activeSchema?.confirmation_required || this._activeSchema?.destructive) {
        if (!confirm(`确认执行此命令？\n${cmd}`)) return;
      }
      btn.disabled = true;
      btn.textContent = "执行中…";
      try {
        const resp = await api("POST", "/commands/execute", { command: cmd });
        HistoryStack.push(cmd, resp);
        this._showResult(resp);
      } catch (e) {
        this._showResult({ status: "error", errors: [e.message] });
      } finally {
        btn.disabled = false;
        btn.textContent = "执行";
      }
    }}, "执行");
    wrap.appendChild(btn);
    return wrap;
  },

  _showResult(resp) {
    const execArea = $(".cmd-exec-area");
    let existing = execArea.querySelector(".cmd-result");
    if (existing) existing.remove();
    const ok = resp.status === "ok";
    // Build output text from response data
    let output = "";
    if (resp.data) {
      if (resp.data.stdout) output = resp.data.stdout;
      else if (resp.data.output) output = resp.data.output;
      else if (resp.data.stderr && !ok) output = resp.data.stderr;
    }
    if (!output && resp.errors && resp.errors.length) {
      output = resp.errors.join("\n");
    }
    if (!output && resp.data) {
      output = JSON.stringify(resp.data, null, 2);
    }
    const resultDiv = el("div", { className: `cmd-result ${ok ? "cmd-result-ok" : "cmd-result-err"}` },
      el("strong", null, ok ? "✓ 执行成功" : "✗ 执行失败"),
      resp.data?.error ? el("p", { className: "cmd-result-error-msg" }, resp.data.error) : null,
      el("pre", { className: "cmd-result-output" }, output)
    );
    execArea.appendChild(resultDiv);
  }
};



// ═══════════════════════════════════════════════════════════════════════════
// §2 — C3: Recipe Panel
// ═══════════════════════════════════════════════════════════════════════════

const RecipePanel = {
  _loaded: false,
  _recipes: [],
  _activeRecipe: null,
  _previewSteps: [],

  async init() {
    this._loaded = true;
    const root = $("#recipe-panel-root");
    root.innerHTML = '<p class="loading">加载操作案例…</p>';
    try {
      const resp = await api("GET", "/recipes");
      this._recipes = resp.data.recipes || [];
      this.render(root);
    } catch (e) {
      root.innerHTML = `<p class="error">加载失败: ${e.message}</p>`;
    }
  },

  render(root) {
    root.innerHTML = "";
    if (!this._recipes.length) {
      root.appendChild(el("p", { className: "empty" }, "暂无操作案例"));
      return;
    }
    const layout = el("div", { className: "recipe-layout" });
    // Left: recipe list
    const list = el("div", { className: "recipe-list" });
    this._recipes.forEach(r => {
      const card = el("div", { className: "recipe-card", onClick: () => this._selectRecipe(r.id) },
        el("div", { className: "recipe-card-title" }, r.title),
        el("div", { className: "recipe-card-meta" },
          el("span", { className: `badge badge-${r.difficulty}` }, r.difficulty),
          el("span", null, ` ~${r.est_minutes}min · ${r.step_count}步`)
        ),
        el("div", { className: "recipe-card-desc" }, r.description)
      );
      list.appendChild(card);
    });
    layout.appendChild(list);
    // Right: detail / preview
    layout.appendChild(el("div", { className: "recipe-detail" },
      el("p", { className: "empty" }, "← 点击左侧选择操作案例")
    ));
    root.appendChild(layout);
  },

  async _selectRecipe(id) {
    // Highlight
    $$(".recipe-card").forEach(c => c.classList.remove("active"));
    const cards = $$(".recipe-card");
    const idx = this._recipes.findIndex(r => r.id === id);
    if (idx >= 0 && cards[idx]) cards[idx].classList.add("active");

    const detail = $(".recipe-detail");
    detail.innerHTML = '<p class="loading">加载详情…</p>';
    try {
      const resp = await api("GET", `/recipes/${id}`);
      this._activeRecipe = resp.data;
      // Auto-preview
      const prevResp = await api("POST", `/recipes/${id}/preview`, { overrides: {} });
      this._previewSteps = prevResp.data?.steps || [];
      this._renderDetail(detail);
    } catch (e) {
      detail.innerHTML = `<p class="error">${e.message}</p>`;
    }
  },

  _renderDetail(container) {
    container.innerHTML = "";
    const r = this._activeRecipe;
    if (!r) return;

    container.appendChild(el("h3", { className: "recipe-title" }, r.title));
    container.appendChild(el("p", { className: "recipe-desc" }, r.description));

    if (r.prerequisites && r.prerequisites.length) {
      container.appendChild(el("div", { className: "recipe-prereqs" },
        el("strong", null, "前提条件: "),
        el("span", null, r.prerequisites.join(", "))
      ));
    }

    // Steps
    const stepsEl = el("div", { className: "recipe-steps" });
    (r.steps || []).forEach((step, i) => {
      const preview = this._previewSteps[i] || {};
      const stepEl = el("div", { className: "recipe-step", "data-step-idx": String(i) },
        el("div", { className: "recipe-step-header" },
          el("span", { className: "recipe-step-num" }, `#${step.id}`),
          el("span", { className: "recipe-step-title" }, step.title),
          step.requires_confirm ? el("span", { className: "badge badge-warn" }, "需确认") : null
        ),
        el("div", { className: "recipe-step-desc" }, step.description),
        el("div", { className: "recipe-step-cmd" },
          el("code", null, preview.command || `[${step.command_id}]`)
        ),
        el("div", { className: "recipe-step-cmd-edit" },
          el("input", { type: "text", value: preview.command || "", "data-step-cmd": String(i), placeholder: "可修改命令后执行" })
        ),
        preview.errors && preview.errors.length
          ? el("div", { className: "recipe-step-err" }, preview.errors.join("; "))
          : null,
        el("div", { className: "recipe-step-actions" },
          el("button", { className: "btn btn-sm", onClick: () => this._execStep(i) }, "执行此步"),
          el("span", { className: "recipe-step-status" })
        )
      );
      stepsEl.appendChild(stepEl);
    });
    container.appendChild(stepsEl);

    // Batch execute
    container.appendChild(el("div", { className: "recipe-batch" },
      el("button", { className: "btn btn-primary", onClick: () => this._execAll() }, "全部执行"),
      el("button", { className: "btn btn-sm", onClick: () => this._execStepByStep() }, "逐步执行")
    ));
  },

  async _execStep(idx) {
    const step = this._previewSteps[idx];
    if (!step) return;
    // Read command from editable input (user may have modified it)
    const cmdInput = $(`[data-step-cmd="${idx}"]`);
    const command = cmdInput ? cmdInput.value.trim() : (step.command || "");
    if (!command) return;
    const stepEl = $$(`.recipe-step`)[idx];
    const statusEl = stepEl?.querySelector(".recipe-step-status");
    if (statusEl) statusEl.textContent = "执行中…";
    stepEl?.classList.add("running");
    try {
      const resp = await api("POST", "/commands/execute", { command });
      HistoryStack.push(command, resp);
      const ok = resp.status === "ok";
      if (statusEl) statusEl.textContent = ok ? "✓" : "✗";
      stepEl?.classList.remove("running");
      stepEl?.classList.add(ok ? "done" : "failed");
    } catch (e) {
      if (statusEl) statusEl.textContent = "✗ 错误";
      stepEl?.classList.remove("running");
      stepEl?.classList.add("failed");
    }
  },

  async _execAll() {
    // Collect commands from editable inputs (user may have modified them)
    const commands = [];
    for (let i = 0; i < this._previewSteps.length; i++) {
      const cmdInput = $(`[data-step-cmd="${i}"]`);
      const cmd = cmdInput ? cmdInput.value.trim() : (this._previewSteps[i]?.command || "");
      if (cmd) commands.push(cmd);
    }
    if (!commands.length) return;
    if (!confirm(`确认执行全部 ${commands.length} 步？`)) return;
    try {
      const resp = await api("POST", "/commands/batch/execute", { commands });
      (resp.data?.results || []).forEach((r, i) => {
        HistoryStack.push(commands[i], { status: r.success ? "ok" : "error", data: r });
      });
      // Update UI
      const stepEls = $$(".recipe-step");
      (resp.data?.results || []).forEach((r, i) => {
        const statusEl = stepEls[i]?.querySelector(".recipe-step-status");
        if (statusEl) statusEl.textContent = r.success ? "✓" : "✗";
        stepEls[i]?.classList.add(r.success ? "done" : "failed");
      });
    } catch (e) {
      alert("批量执行出错: " + e.message);
    }
  },

  async _execStepByStep() {
    for (let i = 0; i < this._previewSteps.length; i++) {
      const step = this._previewSteps[i];
      if (!step || !step.command) continue;
      const recipe = this._activeRecipe;
      const stepDef = recipe?.steps?.[i];
      if (stepDef?.requires_confirm) {
        if (!confirm(`步骤 #${stepDef.id}: ${stepDef.title}\n执行: ${step.command}\n\n继续？`)) return;
      }
      await this._execStep(i);
      // Small delay for UI feedback
      await new Promise(r => setTimeout(r, 300));
    }
  }
};



// ═══════════════════════════════════════════════════════════════════════════
// §3 — C4: Skills Three-Column Panel
// ═══════════════════════════════════════════════════════════════════════════

/**
 * SkillsPanel — 统一同步工作流重构版
 *
 * 两步式心智模型：
 *   Step 1: 扫描所有 Agent 的本地 skills → 统一导入到 AgentMesh 注册表
 *   Step 2: 从注册表软链同步（symlink）到任一目标 Agent 的配置目录
 *
 * 顶部工具条提供两个「批量」按钮（统一导入 / 软链推送到所有 Agent），
 * 选中单个 skill 后右侧显示逐 agent 的「推送卡片」（按 agent 列出当前
 * diff 状态 + 一键软链推送按钮）。所有按钮点击后展开可编辑命令区，
 * 预填默认命令但允许用户二次修改后再执行。
 */
const SkillsPanel = {
  _loaded: false,
  _skills: [],
  _agents: [],              // /agents 返回的完整信息（含 installed 标志）
  _activeSkill: null,

  async init() {
    this._loaded = true;
    const root = $("#skills-panel-root");
    root.innerHTML = '<p class="loading">加载 Skills 与 Agents…</p>';
    try {
      const [skillsResp, agentsResp] = await Promise.all([
        api("GET", "/skills"),
        api("GET", "/agents"),
      ]);
      this._skills = skillsResp.data?.skills || [];
      this._agents = agentsResp.data?.agents || [];
      this.render(root);
    } catch (e) {
      root.innerHTML = `<p class="error">加载失败: ${e.message}</p>`;
    }
  },

  render(root) {
    root.innerHTML = "";

    // ─── Top Toolbar: 统一操作 ──────────────────────────────────
    const installedAgents = this._agents
      .filter(a => a.installed && a.name !== "claude-code") // claude-code 是 export-only
      .map(a => a.name);
    const allAgentsArg = installedAgents.join(",") || "all";

    const toolbar = el("div", { className: "skills-toolbar" },
      el("div", { className: "skills-toolbar-hint" },
        "📦 统一工作流：先把所有 Agent 的 skills 导入 AgentMesh 注册表，再一键软链同步回各 Agent"
      ),
      el("div", { className: "skills-toolbar-row" },
        el("button", {
          className: "btn btn-primary",
          onClick: () => this._showEditable(
            "step1",
            "Step 1 — 扫描并导入所有 Agent 的 Skills",
            "am skills import --from agent:all --apply"
          )
        }, "① 统一导入全部 Agent Skills"),
        el("button", {
          className: "btn btn-primary",
          onClick: () => this._showEditable(
            "step2",
            `Step 2 — 软链同步到所有已安装 Agent (${installedAgents.length} 个)`,
            `am skills sync --to ${allAgentsArg} --mode symlink --apply --yes --confirm`
          )
        }, `② 软链同步到所有 Agent (${installedAgents.length})`),
        el("button", {
          className: "btn btn-sm",
          onClick: () => this._showEditable(
            "preview",
            "预览同步计划 (dry-run)",
            `am skills sync --to ${allAgentsArg} --mode symlink --dry-run --json`
          )
        }, "🔍 预览同步计划"),
        el("button", {
          className: "btn btn-sm",
          onClick: () => this.init() // full refresh
        }, "🔄 刷新")
      ),
      // 可编辑命令区（初始隐藏）
      el("div", { id: "skills-toolbar-edit", className: "skills-edit-cmd hidden" })
    );
    root.appendChild(toolbar);

    // ─── 3-column layout ─────────────────────────────────────────
    if (!this._skills.length) {
      root.appendChild(el("p", { className: "empty" },
        "注册表中暂无 Skills。请先点击「① 统一导入全部 Agent Skills」。"
      ));
      return;
    }

    const layout = el("div", { className: "skills-layout" });

    // Column 1: Skill list
    const col1 = el("div", { className: "skills-col skills-col-list" });
    col1.appendChild(el("h4", null, `Skills (${this._skills.length})`));
    this._skills.forEach(name => {
      col1.appendChild(el("div", {
        className: "skills-item",
        onClick: () => this._selectSkill(name)
      }, name));
    });
    layout.appendChild(col1);

    // Column 2: Detail
    layout.appendChild(el("div", { className: "skills-col skills-col-detail" },
      el("p", { className: "empty" }, "← 选择一个 Skill 查看详情")
    ));

    // Column 3: Per-agent sync cards
    layout.appendChild(el("div", { className: "skills-col skills-col-actions" },
      el("p", { className: "empty" }, "选择 Skill 后可逐 Agent 推送")
    ));

    root.appendChild(layout);
  },

  async _selectSkill(name) {
    $$(".skills-item").forEach(item => item.classList.toggle("active", item.textContent === name));

    const detailCol = $(".skills-col-detail");
    const actionsCol = $(".skills-col-actions");
    detailCol.innerHTML = '<p class="loading">加载详情…</p>';
    actionsCol.innerHTML = '<p class="loading">计算各 Agent 差异…</p>';

    // 拉取 skill 详情 + 对每个已安装 agent 的 diff 等级
    const installedAgents = this._agents
      .filter(a => a.installed && a.name !== "claude-code")
      .map(a => a.name);
    const targetsParam = installedAgents.length ? `?targets=${installedAgents.join(",")}` : "";

    try {
      const resp = await api("GET", `/skills/${name}${targetsParam}`);
      this._activeSkill = resp.data;
      this._renderDetail(detailCol);
      this._renderAgentCards(actionsCol, name);
    } catch (e) {
      detailCol.innerHTML = `<p class="error">${e.message}</p>`;
      actionsCol.innerHTML = "";
    }
  },

  _renderDetail(container) {
    container.innerHTML = "";
    const d = this._activeSkill;
    if (!d) return;

    container.appendChild(el("h4", null, d.skill || d.name || "Skill 详情"));

    const info = el("div", { className: "skills-info" });
    const keys = ["file_count", "total_bytes", "source_agent", "imported_at", "enabled_targets", "risk_summary", "last_sync", "status"];
    keys.forEach(k => {
      if (d[k] == null) return;
      const val = typeof d[k] === "object" ? JSON.stringify(d[k]) : String(d[k]);
      info.appendChild(el("div", { className: "skills-info-row" },
        el("span", { className: "skills-info-key" }, k + ":"),
        el("span", { className: "skills-info-val" }, val)
      ));
    });
    container.appendChild(info);

    // ─── Rename / Delete actions ──────────────────────────────────
    const skillName = d.skill || d.name || "";
    if (skillName) {
      const mgmtSection = el("div", { className: "skills-mgmt" },
        el("h5", null, "管理操作"),
        el("div", { className: "skills-mgmt-row" },
          el("button", {
            className: "btn btn-sm",
            onClick: () => this._showRenameDialog(skillName)
          }, "✏️ 重命名"),
          el("button", {
            className: "btn btn-sm btn-danger",
            onClick: () => this._showDeleteDialog(skillName)
          }, "🗑️ 删除")
        ),
        el("div", { id: "skills-detail-edit", className: "skills-edit-cmd hidden" })
      );
      container.appendChild(mgmtSection);
    }

    // Raw JSON expandable
    container.appendChild(el("details", { className: "skills-raw" },
      el("summary", null, "原始 JSON"),
      el("pre", null, JSON.stringify(d, null, 2))
    ));
  },

  /**
   * Show an inline rename dialog: prompts for the new name, then shows
   * the editable command before execution.
   */
  _showRenameDialog(skillName) {
    const editArea = $("#skills-detail-edit");
    if (!editArea) return;
    editArea.innerHTML = "";
    editArea.classList.remove("hidden");

    const newNameInput = el("input", {
      type: "text",
      className: "form-input",
      placeholder: "新名称（小写 a-z 0-9 - _）",
      value: ""
    });

    const genBtn = el("button", {
      className: "btn btn-sm btn-primary",
      onClick: () => {
        const newName = newNameInput.value.trim();
        if (!newName) { alert("请输入新名称"); return; }
        if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(newName)) {
          alert("名称格式不合法（小写 a-z 0-9 - _，1-64 字符）");
          return;
        }
        // Replace with editable command view
        this._showEditable(
          "rename-exec",
          `重命名: ${skillName} → ${newName}`,
          `am skills rename ${skillName} ${newName} --json`
        );
      }
    }, "生成命令");

    const cancelBtn = el("button", {
      className: "btn btn-sm",
      onClick: () => { editArea.innerHTML = ""; editArea.classList.add("hidden"); }
    }, "取消");

    editArea.appendChild(el("label", { className: "form-label" }, `重命名 "${skillName}" — 输入新名称:`));
    editArea.appendChild(el("div", { className: "skills-rename-row" }, newNameInput, genBtn, cancelBtn));
    newNameInput.focus();
  },

  /**
   * Show a delete confirmation with editable command.
   */
  _showDeleteDialog(skillName) {
    const purgeLabel = "同时清理 target 上的副本";
    const editArea = $("#skills-detail-edit");
    if (!editArea) return;
    editArea.innerHTML = "";
    editArea.classList.remove("hidden");

    const purgeCheck = el("input", { type: "checkbox", className: "form-check" });
    const confirmBtn = el("button", {
      className: "btn btn-sm btn-danger",
      onClick: () => {
        const purge = purgeCheck.checked;
        const cmd = purge
          ? `am skills delete ${skillName} --purge-targets --yes --json`
          : `am skills delete ${skillName} --yes --json`;
        this._showEditable("delete-exec", `删除 skill: ${skillName}`, cmd);
      }
    }, "生成命令");

    const cancelBtn = el("button", {
      className: "btn btn-sm",
      onClick: () => { editArea.innerHTML = ""; editArea.classList.add("hidden"); }
    }, "取消");

    editArea.appendChild(el("label", { className: "form-label" }, `确认删除 "${skillName}":`));
    editArea.appendChild(el("div", { className: "skills-delete-row" },
      el("label", { className: "form-check-label" }, purgeCheck, ` ${purgeLabel}`),
      confirmBtn,
      cancelBtn
    ));
  },

  /**
   * Render per-agent sync cards in the right column.
   * Each card shows: agent name, current diff level, symlink push button.
   */
  _renderAgentCards(container, skillName) {
    container.innerHTML = "";
    container.appendChild(el("h4", null, "推送到 Agent"));
    container.appendChild(el("p", { className: "skills-hint" },
      "选择目标 Agent 一键软链推送。destination agent 的配置目录会通过 symlink 指回 AgentMesh 注册表，修改将双向同步。"
    ));

    const installedAgents = this._agents.filter(a => a.name !== "claude-code");
    const skillDetail = this._activeSkill || {};
    const lastDiff = skillDetail.last_diff || {};  // { <agent>: level_name }

    installedAgents.forEach(agent => {
      const level = lastDiff[agent.name] || (agent.installed ? "—" : "not-installed");
      const disabled = !agent.installed;
      const card = el("div", { className: `skills-agent-card ${disabled ? "disabled" : ""}` },
        el("div", { className: "skills-agent-header" },
          el("span", { className: "skills-agent-name" }, agent.name),
          el("span", { className: "skills-agent-level badge" }, level)
        ),
        el("div", { className: "skills-agent-actions" },
          el("button", {
            className: "btn btn-sm btn-primary",
            disabled: disabled ? "true" : null,
            onClick: () => this._showEditable(
              `push-${agent.name}`,
              `软链推送 ${skillName} → ${agent.name}`,
              `am skills sync ${skillName} --to ${agent.name} --mode symlink --apply --yes --confirm`
            )
          }, "🔗 推送 (symlink)"),
          el("button", {
            className: "btn btn-xs",
            disabled: disabled ? "true" : null,
            onClick: () => this._showEditable(
              `copy-${agent.name}`,
              `复制推送 ${skillName} → ${agent.name}`,
              `am skills sync ${skillName} --to ${agent.name} --mode copy --apply --yes`
            )
          }, "复制"),
          el("button", {
            className: "btn btn-xs",
            disabled: disabled ? "true" : null,
            onClick: () => this._showEditable(
              `diff-${agent.name}`,
              `查看 Diff ${skillName} ↔ ${agent.name}`,
              `am skills diff ${skillName} --target ${agent.name} --json`
            )
          }, "Diff")
        )
      );
      container.appendChild(card);
    });

    // 一键推送到所有 agent
    const allInstalled = installedAgents.filter(a => a.installed).map(a => a.name).join(",");
    if (allInstalled) {
      container.appendChild(el("div", { className: "skills-agent-batch" },
        el("button", {
          className: "btn btn-primary",
          onClick: () => this._showEditable(
            "push-all",
            `推送 ${skillName} 到全部 Agent`,
            `am skills sync ${skillName} --to ${allInstalled} --mode symlink --apply --yes --confirm`
          )
        }, `🚀 一键软链到全部 (${installedAgents.filter(a => a.installed).length})`)
      ));
    }

    // 可编辑命令区（右侧面板共享一个）
    container.appendChild(el("div", { id: "skills-actions-edit", className: "skills-edit-cmd hidden" }));
  },

  /**
   * Show the editable command area. The `slot` distinguishes between
   * the toolbar-level edit (top) and the actions-column edit (right);
   * both are reused to minimize UI clutter.
   */
  _showEditable(slot, label, defaultCmd) {
    // Toolbar-scope buttons use #skills-toolbar-edit; per-agent buttons use the right column;
    // rename/delete use the detail-column edit area.
    let editArea;
    if (slot.startsWith("step") || slot === "preview") {
      editArea = $("#skills-toolbar-edit");
    } else if (slot.startsWith("rename") || slot.startsWith("delete")) {
      editArea = $("#skills-detail-edit");
    } else {
      editArea = $("#skills-actions-edit");
    }
    if (!editArea) return;

    editArea.innerHTML = "";
    editArea.classList.remove("hidden");

    const input = el("input", {
      type: "text",
      className: "form-input skills-edit-input",
      value: defaultCmd
    });
    const statusEl = el("div", { className: "skills-edit-status" });

    const execBtn = el("button", {
      className: "btn btn-primary btn-sm",
      onClick: async () => {
        const cmd = input.value.trim();
        if (!cmd) return;
        if (!confirm(`执行: ${cmd}?`)) return;
        execBtn.disabled = true;
        execBtn.textContent = "执行中…";
        statusEl.innerHTML = "";
        try {
          const resp = await api("POST", "/commands/execute", { command: cmd });
          HistoryStack.push(cmd, resp);
          const ok = resp.status === "ok";
          const msg = ok
            ? "✓ 执行成功"
            : "✗ 执行失败: " + ((resp.errors || []).join("; ") || resp.data?.error || "");
          statusEl.appendChild(el("div", {
            className: ok ? "skills-edit-ok" : "skills-edit-err"
          }, msg));
          // 展示 stdout / stderr 的前 500 字（便于查看 symlink 路径等）
          const out = resp.data?.stdout || resp.data?.stderr || "";
          if (out) {
            statusEl.appendChild(el("pre", { className: "skills-edit-output" }, out.slice(0, 2000)));
          }
          if (ok && cmd.includes("import")) {
            // import 成功后刷新 skills 列表
            setTimeout(() => this.init(), 400);
          } else if (ok && (cmd.includes("rename") || cmd.includes("delete"))) {
            // rename / delete 成功后重新加载整个面板
            setTimeout(() => this.init(), 400);
          } else if (ok && this._activeSkill) {
            // sync 成功后刷新当前 skill 的 diff 状态
            setTimeout(() => this._selectSkill(this._activeSkill.skill || this._activeSkill.name), 400);
          }
        } catch (e) {
          statusEl.appendChild(el("div", { className: "skills-edit-err" }, "✗ 网络错误: " + e.message));
        } finally {
          execBtn.disabled = false;
          execBtn.textContent = "执行";
        }
      }
    }, "执行");

    const cancelBtn = el("button", {
      className: "btn btn-sm",
      onClick: () => { editArea.innerHTML = ""; editArea.classList.add("hidden"); }
    }, "取消");

    editArea.appendChild(el("label", { className: "form-label" }, label + " — 可编辑命令:"));
    editArea.appendChild(input);
    editArea.appendChild(el("div", { className: "skills-edit-btns" }, execBtn, cancelBtn));
    editArea.appendChild(statusEl);
    input.focus();
    input.select();
  }
};



// ═══════════════════════════════════════════════════════════════════════════
// §4 — C5: localStorage Execution History Stack
// ═══════════════════════════════════════════════════════════════════════════

const HistoryStack = {
  _KEY: "agentmesh_exec_history",
  _MAX: 200,

  _load() {
    try {
      return JSON.parse(localStorage.getItem(this._KEY) || "[]");
    } catch { return []; }
  },

  _save(items) {
    localStorage.setItem(this._KEY, JSON.stringify(items.slice(-this._MAX)));
  },

  push(command, response) {
    const items = this._load();
    items.push({
      id: Date.now() + "_" + Math.random().toString(36).slice(2, 8),
      command,
      status: response?.status || "unknown",
      timestamp: new Date().toISOString(),
      stdout: response?.data?.stdout || response?.data?.output || "",
      stderr: response?.data?.stderr || "",
      errors: response?.errors || [],
      error: response?.data?.error || "",
    });
    this._save(items);
    this.renderPanel();
  },

  clear() {
    localStorage.removeItem(this._KEY);
    this.renderPanel();
  },

  export() {
    const items = this._load();
    const blob = new Blob([JSON.stringify(items, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `agentmesh_history_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  },

  /**
   * C8: Server-side export via POST /export/history.
   * Triggers a file download in the selected format (json|csv|txt).
   */
  async serverExport(format) {
    try {
      const res = await fetch("/export/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format, limit: 500 })
      });
      if (!res.ok) { alert("导出失败: HTTP " + res.status); return; }
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename = match ? match[1] : `agentmesh_history.${format}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("导出失败: " + e.message);
    }
  },

  renderPanel() {
    const root = $("#history-panel-root");
    if (!root) return;
    const items = this._load();
    root.innerHTML = "";

    if (!items.length) {
      root.classList.remove("has-items");
      return;
    }
    root.classList.add("has-items");

    // Header
    const header = el("div", { className: "history-header" },
      el("span", { className: "history-title" }, `执行记录 (${items.length})`),
      el("div", { className: "history-actions" },
        el("button", { className: "btn btn-sm", onClick: () => this.export() }, "导出 (本地)"),
        el("select", { className: "export-format-select", onChange: (e) => { if (e.target.value) { this.serverExport(e.target.value); e.target.value = ""; } } },
          el("option", { value: "" }, "服务端导出…"),
          el("option", { value: "json" }, "JSON"),
          el("option", { value: "csv" }, "CSV"),
          el("option", { value: "txt" }, "TXT")
        ),
        el("button", { className: "btn btn-sm btn-danger", onClick: () => { if (confirm("清空所有记录？")) this.clear(); } }, "清空")
      )
    );
    root.appendChild(header);

    // Items (newest first, max 50 displayed)
    const list = el("div", { className: "history-list" });
    const displayed = items.slice(-50).reverse();
    displayed.forEach(item => {
      const row = el("div", { className: `history-row ${item.status === "ok" ? "history-ok" : "history-err"}` },
        el("span", { className: "history-time" }, new Date(item.timestamp).toLocaleTimeString()),
        el("code", { className: "history-cmd" }, item.command),
        el("span", { className: `history-status` }, item.status === "ok" ? "✓" : "✗"),
        el("button", { className: "btn btn-xs", onClick: () => this._reExec(item.command) }, "再次执行")
      );
      list.appendChild(row);
    });
    root.appendChild(list);
  },

  async _reExec(command) {
    if (!confirm(`再次执行: ${command}?`)) return;
    try {
      const resp = await api("POST", "/commands/execute", { command });
      this.push(command, resp);
    } catch (e) {
      alert("执行失败: " + e.message);
    }
  }
};

// ═══════════════════════════════════════════════════════════════════════════
// §5 — C7: Global Search
// ═══════════════════════════════════════════════════════════════════════════

const SearchPanel = {
  _init: false,

  init() {
    if (this._init) return;
    this._init = true;
    const input = $("#global-search");
    const resultsEl = $("#search-results");
    if (!input || !resultsEl) return;

    const doSearch = debounce(() => this._search(input.value.trim()), 300);
    input.addEventListener("input", doSearch);
    input.addEventListener("focus", () => { if (input.value.trim()) this._search(input.value.trim()); });

    // Close on click outside
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".search-wrap")) resultsEl.classList.add("hidden");
    });
    // Close on Escape
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { resultsEl.classList.add("hidden"); input.blur(); }
    });
  },

  async _search(query) {
    const resultsEl = $("#search-results");
    if (!query) { resultsEl.classList.add("hidden"); return; }
    try {
      const resp = await api("POST", "/commands/search", { query });
      const results = resp.data?.results || [];
      resultsEl.innerHTML = "";
      if (!results.length) {
        resultsEl.appendChild(el("div", { className: "search-empty" }, "无匹配结果"));
        resultsEl.classList.remove("hidden");
        return;
      }
      results.slice(0, 20).forEach(item => {
        const cmd = item.command || "";
        const source = item.source === "favorites" ? "⭐" : "";
        const row = el("div", { className: "search-row", onClick: () => this._runResult(cmd) },
          el("code", { className: "search-row-cmd" }, cmd),
          source ? el("span", { className: "search-row-badge" }, source) : null,
          item.timestamp ? el("span", { className: "search-row-time" }, new Date(item.timestamp).toLocaleDateString()) : null
        );
        resultsEl.appendChild(row);
      });
      resultsEl.classList.remove("hidden");
    } catch (e) {
      resultsEl.innerHTML = "";
      resultsEl.appendChild(el("div", { className: "search-empty" }, "搜索出错"));
      resultsEl.classList.remove("hidden");
    }
  },

  async _runResult(command) {
    $("#search-results").classList.add("hidden");
    $("#global-search").value = "";
    if (!command) return;
    if (!confirm(`执行: ${command}?`)) return;
    try {
      const resp = await api("POST", "/commands/execute", { command });
      HistoryStack.push(command, resp);
    } catch (e) {
      alert("执行失败: " + e.message);
    }
  }
};

// ═══════════════════════════════════════════════════════════════════════════
// §6 — Boot
// ═══════════════════════════════════════════════════════════════════════════

// Render history on load
HistoryStack.renderPanel();
// Init search
SearchPanel.init();

console.log("AgentMesh workstation loaded (Phase C). Backend API at /commands/schemas, /recipes, /skills.");
