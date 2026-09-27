/* 独立交互原型。示例规则、预览与运行均在内存中，不调用业务 API。 */
"use strict";

const icons = {
    layout: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18M9 9h12"/>',
    folder: '<path d="M3 7V5a2 2 0 0 1 2-2h5l3 4h6a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
    config: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6ZM14 3v6h6M8 13h8M8 17h8M11 11v4M14 15v4"/>',
    history: '<path d="M3 4v6h6M3 10a9 9 0 1 1 1 7M12 7v5l3 2"/>',
    sliders:
        '<path d="M4 6h6m4 0h6M4 12h10m4 0h2M4 18h2m4 0h10M10 3v6m4 0v6M6 15v6"/>',
    external:
        '<path d="M14 3h7v7m-1-6-9 9M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
    database:
        '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 9v11M3 14h18"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
    sprout: '<path d="M12 22v-9M12 15C3 15 3 5 3 5c9 0 10 6 9 10ZM12 10C12 2 21 2 21 2c0 7-3 10-9 8Z"/>',
    save: '<path d="M5 3h12l4 4v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',
    play: '<path d="m8 4 12 8-12 8V4Z"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6M8 13h8m-8 4h5"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    branches:
        '<rect x="8" y="2" width="8" height="5" rx="1"/><rect x="2" y="17" width="7" height="5" rx="1"/><rect x="15" y="17" width="7" height="5" rx="1"/><path d="M12 7v5M5.5 17v-5h13v5"/>',
    refresh:
        '<path d="M3 11a9 9 0 0 1 15-6l3 2M21 3v4h-4M21 13a9 9 0 0 1-15 6l-3-2M3 21v-4h4"/>',
    layers: '<path d="m12 3 10 6-10 6L2 9ZM2 14l10 6 10-6M2 19l10 6 10-6" transform="translate(0 -2)"/>',
    shield: '<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6Z"/><path d="m8 12 3 3 5-6"/>',
    arrow: '<path d="M3 12h17m-5-5 5 5-5 5"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    check: '<path d="m5 12 4 4 10-10"/>',
    sparkles:
        '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4m-2-2h4"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 5 9 8 9-8"/>',
    person: '<circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    hash: '<path d="M5 8h15M4 16h15M10 3 8 21M17 3l-2 18"/>',
    calendar:
        '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6m10-6v6M3 11h18"/>',
    key: '<circle cx="8" cy="8" r="5"/><path d="m12 12 9 9m-4-4 3-3m-6 0 3-3"/>',
    edit: '<path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14Z"/>',
    list: '<path d="M9 5h12M9 12h12M9 19h12M3 5h1M3 12h1M3 19h1"/>',
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHTML = (value) =>
    String(value).replace(
        /[&<>"']/g,
        (char) =>
            ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            })[char],
    );
const icon = (name) =>
    `<svg class="ui-icon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.table}</svg>`;
const number = (value) => Number(value).toLocaleString("en-US");
const labels = {
    auto: "数据库自增",
    name: "姓名",
    email: "电子邮箱",
    integer: "整数范围",
    decimal: "小数范围",
    choice: "选项集合",
    datetime: "日期时间",
    reference: "外键引用",
};
const generatorIcons = {
    auto: "key",
    name: "person",
    email: "mail",
    integer: "hash",
    decimal: "hash",
    choice: "list",
    datetime: "calendar",
    reference: "branches",
};
const field = (
    name,
    type,
    generator,
    params = {},
    constraints = ["NOT NULL"],
) => ({ name, type, generator, params, constraints });
const tables = {
    users: {
        description: "用户基础信息",
        count: 1000,
        selected: true,
        depends: [],
        fields: [
            field("id", "INTEGER", "auto", {}, ["PRIMARY KEY"]),
            field("full_name", "TEXT", "name"),
            field("email", "TEXT", "email", { domain: "example.test" }),
            field("age", "INTEGER", "integer", { min: 18, max: 65 }),
            field("status", "TEXT", "choice", {
                values: ["active", "inactive", "pending"],
            }),
            field("created_at", "DATETIME", "datetime", {
                start: "2026-01-01",
                end: "2026-09-25",
            }),
            field("balance", "DECIMAL", "decimal", { min: 0, max: 5000 }),
        ],
    },
    orders: {
        description: "订单与交易",
        count: 3000,
        selected: true,
        depends: ["users"],
        fields: [
            field("id", "INTEGER", "auto", {}, ["PRIMARY KEY"]),
            field("user_id", "INTEGER", "reference", { target: "users.id" }, [
                "FOREIGN KEY",
                "NOT NULL",
            ]),
            field("total", "DECIMAL", "decimal", { min: 25, max: 2500 }),
            field("status", "TEXT", "choice", {
                values: ["paid", "pending", "shipped"],
            }),
            field("created_at", "DATETIME", "datetime", {
                start: "2026-07-01",
                end: "2026-09-25",
            }),
        ],
    },
    products: {
        description: "商品目录",
        count: 200,
        selected: false,
        depends: [],
        fields: [
            field("id", "INTEGER", "auto", {}, ["PRIMARY KEY"]),
            field("name", "TEXT", "choice", {
                values: ["无线键盘", "桌面收纳架", "便携咖啡杯", "阅读台灯"],
            }),
            field("price", "DECIMAL", "decimal", { min: 29, max: 999 }),
            field("stock", "INTEGER", "integer", { min: 0, max: 200 }),
        ],
    },
    order_items: {
        description: "订单明细",
        count: 6000,
        selected: false,
        depends: ["orders", "products"],
        fields: [
            field("id", "INTEGER", "auto", {}, ["PRIMARY KEY"]),
            field("order_id", "INTEGER", "reference", { target: "orders.id" }, [
                "FOREIGN KEY",
                "NOT NULL",
            ]),
            field(
                "product_id",
                "INTEGER",
                "reference",
                { target: "products.id" },
                ["FOREIGN KEY", "NOT NULL"],
            ),
            field("quantity", "INTEGER", "integer", { min: 1, max: 5 }),
        ],
    },
};
let currentTable = "users";
let currentTab = "rules";
let revision = 0;
let sampleRound = 0;
let checkedRevision = -1;
let savedRevision = -1;
let savedConfig = null;
let editingField = null;
let editorReturnTarget = null;
let runTimer = null;
let toastTimer = null;
let currentView = "workbench";
const runs = [];

function hydrateIcons(root = document) {
    root.querySelectorAll("[data-icon]").forEach((el) => {
        el.innerHTML = icon(el.dataset.icon);
    });
}
function notify(message) {
    clearTimeout(toastTimer);
    $("#toast-text").textContent = message;
    $("#toast").hidden = false;
    toastTimer = setTimeout(() => {
        $("#toast").hidden = true;
    }, 3500);
}
function selectedTables() {
    return Object.entries(tables).filter(([, table]) => table.selected);
}
function changed() {
    revision += 1;
    checkedRevision = -1;
    $("#save-state").textContent = "有未保存的修改";
    updateSummary();
}
function updateSummary() {
    const selected = selectedTables();
    const total = selected.reduce(
        (sum, [, table]) =>
            sum + (validCount(table.count) ? Number(table.count) : 0),
        0,
    );
    $("#selection-summary").textContent = `已选择 ${selected.length} 张表`;
    $("#selection-detail").textContent = selected.some(
        ([, table]) => !validCount(table.count),
    )
        ? "请修正无效的生成行数"
        : `预计生成 ${number(total)} 行数据`;
    $("#generate").disabled = selected.length === 0;
}
function renderSidebar() {
    const search = $("#table-search").value.toLowerCase().trim();
    const visible = Object.entries(tables).filter(([name, table]) =>
        `${name} ${table.description}`.toLowerCase().includes(search),
    );
    $("#table-list").innerHTML = visible
        .map(
            ([name, table]) =>
                `<div class="table-item ${name === currentTable ? "active" : ""}"><input type="checkbox" data-select="${name}" aria-label="选择 ${name} 参与生成" ${table.selected ? "checked" : ""}><button class="table-select" data-table="${name}" ${name === currentTable ? 'aria-current="true"' : ""}><span data-icon="table"></span><span><strong>${name}</strong><small>${table.description}</small></span></button><span class="table-amount">${table.selected ? (validCount(table.count) ? number(table.count) : "待修正") : "—"}</span></div>`,
        )
        .join("");
    $("#table-count").textContent = String(visible.length).padStart(2, "0");
    $("#search-empty").hidden = visible.length > 0;
    hydrateIcons($("#table-list"));
    $$("[data-select]").forEach((input) =>
        input.addEventListener("change", () => {
            tables[input.dataset.select].selected = input.checked;
            changed();
            renderSidebar();
            document
                .querySelector(`[data-select="${input.dataset.select}"]`)
                ?.focus();
        }),
    );
    $$("[data-table]").forEach((button) =>
        button.addEventListener("click", () =>
            selectTable(button.dataset.table),
        ),
    );
}
function selectTable(name) {
    currentTable = name;
    if (currentView !== "workbench") showView("workbench");
    renderSidebar();
    renderTable();
}
function ruleDescription(item) {
    const p = item.params;
    if (item.generator === "auto") return "写入时由数据库分配";
    if (item.generator === "reference") return p.target;
    if (item.generator === "name")
        return $("#locale").value === "zh_CN"
            ? "中文姓名 · zh_CN"
            : "英文姓名 · en_US";
    if (item.generator === "email") return `@${p.domain}`;
    if (item.generator === "integer" || item.generator === "decimal")
        return `${number(p.min)} — ${number(p.max)}${item.generator === "decimal" ? " · 2 位小数" : ""}`;
    if (item.generator === "choice") return p.values.join(" / ");
    return `${p.start} → ${p.end}`;
}
function renderTable() {
    const table = tables[currentTable];
    $("#current-table-name").textContent = currentTable;
    $("#current-table-description").textContent = table.description;
    $("#field-count").textContent = `${table.fields.length} 个字段`;
    $("#row-count").value = table.count;
    $("#rules-body").innerHTML = table.fields
        .map(
            (item, index) =>
                `<tr><td class="number-col">${String(index + 1).padStart(2, "0")}</td><td><span class="field-name">${item.name}</span><span class="field-type">${item.type}</span></td><td><button class="rule-button" data-field="${index}" aria-label="${item.generator === "auto" || item.generator === "reference" ? "查看" : "编辑"} ${item.name} 规则"><span class="generator-icon" data-icon="${generatorIcons[item.generator]}"></span><span><span class="rule-label">${labels[item.generator]}</span><span class="rule-description">${escapeHTML(ruleDescription(item))}</span></span></button></td><td>${item.constraints.map((constraint) => `<span class="constraint-tag ${constraint === "PRIMARY KEY" ? "pk" : ""}">${constraint === "PRIMARY KEY" ? icon("key") : ""}${constraint}</span>`).join("")}</td><td><button class="icon-button edit-rule" data-field="${index}" aria-label="${item.name} 字段详情"><span data-icon="${item.generator === "auto" || item.generator === "reference" ? "info" : "edit"}"></span></button></td></tr>`,
        )
        .join("");
    $("#rule-summary").textContent =
        `${table.fields.filter((item) => item.generator !== "auto").length} 项生成规则`;
    hydrateIcons($("#rules-body"));
    $("#rules-body")
        .querySelectorAll("[data-field]")
        .forEach((button) =>
            button.addEventListener("click", () =>
                openField(Number(button.dataset.field), button),
            ),
        );
    if (currentTab === "preview") renderPreview();
    if (currentTab === "relations") renderRelations();
}
function setTab(tabName) {
    currentTab = tabName;
    $$("[data-tab]").forEach((button) => {
        const active = button.dataset.tab === tabName;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", String(active));
    });
    ["rules", "preview", "relations"].forEach((name) => {
        $(`#${name}-panel`).hidden = name !== tabName;
    });
    $("#refresh-preview").innerHTML =
        `${icon("refresh")}${tabName === "preview" ? "换一组样例" : "预览本表"}`;
    if (tabName === "preview") renderPreview();
    if (tabName === "relations") renderRelations();
}
function validCount(value) {
    return (
        value !== "" &&
        Number.isInteger(Number(value)) &&
        Number(value) >= 1 &&
        Number(value) <= 1000000
    );
}
function sample(item, index, round = sampleRound) {
    const seed = Number($("#seed").value) || 0;
    let hash = seed + index * 137 + round * 47 + item.name.length * 31;
    hash = ((hash * 1664525 + 1013904223) >>> 0) / 4294967296;
    const slot = Math.abs(seed + index + round) % 5;
    const p = item.params;
    if (item.generator === "auto") return "写入时生成";
    if (item.generator === "reference") return `待关联 ${p.target}`;
    if (item.generator === "name")
        return (
            $("#locale").value === "zh_CN"
                ? ["林知夏", "陈予安", "周书宁", "许景行", "沈一禾"]
                : [
                      "Alex Morgan",
                      "Jamie Lee",
                      "Robin Chen",
                      "Sam Taylor",
                      "Casey Lin",
                  ]
        )[slot];
    if (item.generator === "email")
        return `${["zhixia.lin", "yuan.chen", "shuning.zhou", "jingxing.xu", "yihe.shen"][slot]}@${p.domain}`;
    if (item.generator === "choice")
        return p.values[(slot + index) % p.values.length];
    if (item.generator === "integer")
        return String(p.min + Math.floor(hash * (p.max - p.min + 1)));
    if (item.generator === "decimal")
        return (p.min + hash * (p.max - p.min)).toFixed(2);
    const start = Date.parse(`${p.start}T00:00:00Z`);
    const end = Date.parse(`${p.end}T23:59:59Z`);
    return new Date(start + hash * (end - start))
        .toISOString()
        .slice(0, 19)
        .replace("T", " ");
}
function renderPreview() {
    const fields = tables[currentTable].fields;
    $("#preview-state").textContent =
        `当前规则的演示样例 · 第 ${sampleRound + 1} 组`;
    $("#preview-table").innerHTML =
        `<thead><tr>${fields.map((item, index) => `<th><button data-preview-field="${index}" aria-label="查看 ${item.name} 规则">${item.name}</button></th>`).join("")}</tr></thead><tbody>${Array.from({ length: 5 }, (_, row) => `<tr>${fields.map((item) => `<td class="${item.generator === "auto" || item.generator === "reference" ? "auto-value" : ""}">${escapeHTML(sample(item, row))}</td>`).join("")}</tr>`).join("")}</tbody>`;
    $$("[data-preview-field]").forEach((button) =>
        button.addEventListener("click", () =>
            openField(Number(button.dataset.previewField), button),
        ),
    );
}
function renderRelations() {
    const node = (name) =>
        `<button class="relation-node ${name === currentTable ? "current" : ""}" data-relation-table="${name}"><strong>${name}</strong><small>${tables[name].description} · ${tables[name].selected ? "参与生成" : "未选择"}</small></button>`;
    $("#relations-content").innerHTML =
        `<div class="relation-paths"><div class="relation-flow">${node("users")}<span class="relation-arrow">→<small>user_id</small></span>${node("orders")}<span class="relation-arrow">→<small>order_id</small></span>${node("order_items")}</div><div class="relation-flow">${node("products")}<span class="relation-arrow">→<small>product_id</small></span>${node("order_items")}</div><p class="form-help">箭头指向引用该主键的表。点击节点查看字段，生成范围保持不变。</p></div>`;
    $$("[data-relation-table]").forEach((button) =>
        button.addEventListener("click", () =>
            selectTable(button.dataset.relationTable),
        ),
    );
}
function showView(name) {
    currentView = name;
    ["workbench", "configs", "runs"].forEach((view) => {
        $(`#${view}-view`).hidden = name !== view;
    });
    $$("[data-view]").forEach((button) => {
        button.classList.toggle("active", button.dataset.view === name);
        if (button.dataset.view === name)
            button.setAttribute("aria-current", "page");
        else button.removeAttribute("aria-current");
    });
    if (name === "configs") renderConfigs();
    if (name === "runs") renderRuns();
}
function showDialog(id) {
    const dialog = $(`#${id}`);
    if (!dialog.open) dialog.showModal();
}
function readRuleDraft() {
    const generator = $("#generator").value;
    const params = {};
    if (generator === "email") {
        const domain = $("#param-domain").value.trim().toLowerCase();
        if (!/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/.test(domain))
            throw new Error("请输入有效域名，例如 example.test。");
        params.domain = domain;
    } else if (generator === "integer" || generator === "decimal") {
        const minText = $("#param-min").value;
        const maxText = $("#param-max").value;
        const min = Number(minText),
            max = Number(maxText);
        if (
            minText === "" ||
            maxText === "" ||
            !Number.isFinite(min) ||
            !Number.isFinite(max)
        )
            throw new Error("请填写完整的数值范围。");
        if (min > max) throw new Error("最小值不能大于最大值。");
        if (
            generator === "integer" &&
            (!Number.isInteger(min) || !Number.isInteger(max))
        )
            throw new Error("整数范围不支持小数。");
        if (Math.abs(min) > 1000000000 || Math.abs(max) > 1000000000)
            throw new Error("原型支持的数值范围为 -10 亿至 10 亿。");
        params.min = min;
        params.max = max;
    } else if (generator === "choice") {
        params.values = $("#param-values")
            .value.split(/[,，]/)
            .map((value) => value.trim())
            .filter(Boolean);
        if (!params.values.length) throw new Error("请至少填写一个选项。");
    } else if (generator === "datetime") {
        params.start = $("#param-start").value;
        params.end = $("#param-end").value;
        if (!params.start || !params.end || params.start > params.end)
            throw new Error("请填写有效的日期范围，起始日期不能晚于结束日期。");
    }
    return { ...editingField, generator, params };
}
function validateDraft() {
    const inputs = $$("#generator-options input");
    inputs.forEach((input) => {
        input.removeAttribute("aria-invalid");
        input.removeAttribute("aria-describedby");
    });
    try {
        const draft = readRuleDraft();
        $("#field-error").textContent = "";
        $("#rule-sample").textContent = sample(draft, 0);
        $('#field-form button[type="submit"]').disabled = false;
        return draft;
    } catch (error) {
        $("#field-error").textContent = error.message;
        inputs.forEach((input) => {
            input.setAttribute("aria-invalid", "true");
            input.setAttribute("aria-describedby", "field-error");
        });
        $("#rule-sample").textContent = "修正规则后显示样例";
        $('#field-form button[type="submit"]').disabled = true;
        return null;
    }
}
function renderGeneratorOptions(params = {}) {
    const generator = $("#generator").value;
    let content = "";
    if (generator === "email")
        content = `<label class="form-label">邮箱域名<input id="param-domain" type="text" maxlength="100" value="${escapeHTML(params.domain || "example.test")}" spellcheck="false" required></label><p class="form-help">固定域名，让样例更贴近你的测试场景。</p>`;
    else if (generator === "integer" || generator === "decimal")
        content = `<div class="form-pair"><label class="form-label">最小值<input id="param-min" type="number" step="${generator === "integer" ? "1" : "0.01"}" value="${params.min ?? 0}" required></label><label class="form-label">最大值<input id="param-max" type="number" step="${generator === "integer" ? "1" : "0.01"}" value="${params.max ?? 100}" required></label></div><p class="form-help">包含上下界。${generator === "decimal" ? "样例保留 2 位小数。" : "所有生成值均为整数。"}</p>`;
    else if (generator === "choice")
        content = `<label class="form-label">可选值<input id="param-values" type="text" maxlength="300" value="${escapeHTML((params.values || ["active", "inactive"]).join(", "))}" required></label><p class="form-help">用逗号分隔。演示样例从这些选项中取值。</p>`;
    else if (generator === "datetime")
        content = `<label class="form-label">起始日期<input id="param-start" type="date" value="${params.start || "2026-01-01"}" required></label><label class="form-label">结束日期<input id="param-end" type="date" value="${params.end || "2026-09-25"}" required></label>`;
    else
        content =
            '<p class="form-help">姓名样例遵循工作台选择的数据语言与地区。</p>';
    $("#generator-options").innerHTML = content;
    $("#generator-options")
        .querySelectorAll("input")
        .forEach((input) => input.addEventListener("input", validateDraft));
    validateDraft();
}
function openField(index, trigger) {
    editingField = tables[currentTable].fields[index];
    editorReturnTarget = {
        table: currentTable,
        index,
        preview: currentTab === "preview",
    };
    if (
        editingField.generator === "auto" ||
        editingField.generator === "reference"
    ) {
        const isAuto = editingField.generator === "auto";
        actionDialog(
            `${editingField.name} · 字段信息`,
            `<p class="action-message">${isAuto ? "这个字段由数据库自动分配主键。预览不虚构写入后的 ID，也不允许在此覆盖数据库规则。" : `此字段引用 ${escapeHTML(editingField.params.target)}。实际生成需要关联表中的有效记录；原型用引用说明代替真实外键值。`}</p><div class="check-success">${icon("shield")}${escapeHTML(editingField.constraints.join(" · "))}</div>`,
            [
                {
                    label: "知道了",
                    primary: true,
                    action: () => $("#action-dialog").close(),
                },
            ],
        );
        return;
    }
    $("#field-title").textContent = editingField.name;
    $("#field-meta").textContent = `${currentTable} / ${editingField.type}`;
    const allowed =
        editingField.type === "TEXT"
            ? ["name", "email", "choice"]
            : editingField.type === "INTEGER"
              ? ["integer"]
              : editingField.type === "DECIMAL"
                ? ["decimal"]
                : ["datetime"];
    $("#generator").innerHTML = allowed
        .map(
            (name) =>
                `<option value="${name}" ${name === editingField.generator ? "selected" : ""}>${labels[name]}</option>`,
        )
        .join("");
    $("#constraint-description").textContent =
        `保留字段约束：${editingField.constraints.join("、")}。规则仅影响生成的数据。`;
    renderGeneratorOptions(editingField.params);
    showDialog("field-dialog");
}
function actionDialog(
    title,
    content,
    buttons = [],
    eyebrow = "READY WHEN YOU ARE",
) {
    $("#action-title").textContent = title;
    $("#action-eyebrow").textContent = eyebrow;
    $("#action-content").innerHTML = content;
    $("#action-footer").replaceChildren();
    buttons.forEach(({ label, primary, action, disabled }) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `button${primary ? " primary" : ""}`;
        button.textContent = label;
        button.disabled = Boolean(disabled);
        button.addEventListener("click", action);
        $("#action-footer").append(button);
    });
    showDialog("action-dialog");
}
function validationIssues() {
    const issues = [];
    const selected = selectedTables();
    if (!selected.length) issues.push("请至少勾选一张参与生成的数据表。");
    if (!$("#seed").checkValidity())
        issues.push("随机种子应为 0–999999 之间的整数。");
    for (const [name, table] of selected) {
        if (!validCount(table.count))
            issues.push(`${name}：生成行数应为 1–1,000,000 之间的整数。`);
        table.depends.forEach((dependency) => {
            if (!tables[dependency].selected)
                issues.push(
                    `${name} 引用 ${dependency}，请同时勾选 ${dependency}。原型不读取已有数据库记录。`,
                );
        });
    }
    return issues;
}
function checkConfiguration(generate = false) {
    const issues = validationIssues();
    if (issues.length) {
        actionDialog(
            "还有几处需要调整",
            `<div class="check-success error">${icon("info")}配置检查未通过</div>${issues.map((issue) => `<p class="action-message">${escapeHTML(issue)}</p>`).join("")}`,
            [
                {
                    label: "返回调整",
                    primary: true,
                    action: () => $("#action-dialog").close(),
                },
            ],
            "A LITTLE ATTENTION",
        );
        return;
    }
    checkedRevision = revision;
    const selected = selectedTables();
    const total = selected.reduce(
        (sum, [, table]) => sum + Number(table.count),
        0,
    );
    const content = `<div class="check-success">${icon("check")}已检查生成范围、行数及表间依赖</div><div class="plan-list">${selected.map(([name, table]) => `<div class="plan-row"><code>${name}</code><span>${number(table.count)} 行</span></div>`).join("")}</div><p class="action-message">目标：<strong>shop_demo.db（演示）</strong><br>共 ${selected.length} 张表，${number(total)} 行。此次仅模拟追加生成，不连接或修改真实数据库。</p>`;
    actionDialog(
        generate ? "生成前，再确认一下。" : "配置已准备就绪",
        content,
        [
            { label: "返回工作台", action: () => $("#action-dialog").close() },
            {
                label: "模拟生成",
                primary: true,
                action: () =>
                    simulateRun(structuredClone(selected), total, revision),
            },
        ],
    );
}
function simulateRun(snapshot, total, version) {
    if (version !== checkedRevision || version !== revision) {
        checkConfiguration(true);
        return;
    }
    const run = {
        time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
        total,
        tables: snapshot.map(([name]) => name),
        status: "运行中",
    };
    let step = 0;
    $("#action-title").textContent = "数据正在生长。";
    $("#action-content").innerHTML =
        `<p class="action-message">正在模拟生成 ${number(total)} 行数据。</p><div class="progress-track" role="progressbar" aria-label="模拟生成进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="progress-fill"></div></div><p class="action-message" id="progress-text">准备规则与表间依赖…</p>`;
    $("#action-footer").innerHTML =
        '<button class="button" id="cancel-run">取消模拟</button>';
    $("#cancel-run").addEventListener("click", () =>
        $("#action-dialog").close(),
    );
    runTimer = setInterval(() => {
        step += 1;
        $(".progress-fill").style.width = `${step * 25}%`;
        $('[role="progressbar"]').setAttribute(
            "aria-valuenow",
            String(step * 25),
        );
        $("#progress-text").textContent =
            `模拟进度 ${step * 25}% · ${number(Math.round((total * step) / 4))} / ${number(total)} 行`;
        if (step < 4) return;
        clearInterval(runTimer);
        runTimer = null;
        run.status = "模拟完成";
        runs.unshift(run);
        actionDialog(
            "准备好了，去验证你的想法。",
            `<div class="check-success">${icon("check")}模拟完成 · ${number(total)} 行 / ${snapshot.length} 张表</div><p class="action-message">真实数据库没有发生变化。你可以继续调整规则，或查看本次模拟记录。</p>`,
            [
                {
                    label: "继续编辑",
                    action: () => $("#action-dialog").close(),
                },
                {
                    label: "查看运行记录",
                    primary: true,
                    action: () => {
                        $("#action-dialog").close();
                        showView("runs");
                    },
                },
            ],
            "A FRESH START",
        );
    }, 400);
}
function saveConfiguration() {
    const issues = validationIssues();
    if (issues.length) {
        checkConfiguration();
        return;
    }
    savedConfig = {
        tables: structuredClone(tables),
        provider: $("#provider").value,
        locale: $("#locale").value,
        seed: $("#seed").value,
        time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    };
    savedRevision = revision;
    $("#save-state").textContent = `已保存至本次会话 · ${savedConfig.time}`;
    notify("演示配置已保存到本次会话");
}
function renderConfigs() {
    $("#saved-configs").innerHTML = savedConfig
        ? `<article class="saved-item"><span class="table-symbol">${icon("file")}</span><div><strong>电商测试数据</strong><p>${savedConfig.time} 保存 · ${Object.values(savedConfig.tables).filter((table) => table.selected).length} 张表 · ${escapeHTML(savedConfig.provider)} · ${escapeHTML(savedConfig.locale)}</p></div><button class="button" id="restore-config">打开配置</button></article><p class="form-help">保存在当前页面内存中，刷新页面后重置。</p>`
        : '<div class="empty-collection">还没有保存的演示配置。<br>在工作台调整规则后，点击「保存配置」。</div>';
    $("#restore-config")?.addEventListener("click", () => {
        const restore = () => {
            Object.assign(tables, structuredClone(savedConfig.tables));
            $("#provider").value = savedConfig.provider;
            $("#locale").value = savedConfig.locale;
            $("#seed").value = savedConfig.seed;
            changed();
            savedRevision = revision;
            $("#save-state").textContent =
                `已打开保存的配置 · ${savedConfig.time}`;
            showView("workbench");
            renderSidebar();
            renderTable();
            notify("已打开演示配置");
        };
        if (savedRevision !== revision)
            actionDialog(
                "打开保存的配置？",
                '<p class="action-message">当前尚未保存的修改将被保存版本替换。</p>',
                [
                    {
                        label: "取消",
                        action: () => $("#action-dialog").close(),
                    },
                    {
                        label: "打开配置",
                        primary: true,
                        action: () => {
                            $("#action-dialog").close();
                            restore();
                        },
                    },
                ],
            );
        else restore();
    });
}
function renderRuns() {
    $("#run-history").innerHTML = runs.length
        ? runs
              .map(
                  (run) =>
                      `<article class="history-item"><span class="table-symbol">${icon("check")}</span><div><strong>电商测试数据</strong><p>${run.time} · ${number(run.total)} 行 · ${run.tables.join(" / ")}</p></div><span>${run.status}</span></article>`,
              )
              .join("")
        : '<div class="empty-collection">还没有运行记录。<br>返回工作台，体验「检查并生成」。</div>';
}

hydrateIcons();
renderSidebar();
renderTable();
updateSummary();
$$("[data-view]").forEach((button) =>
    button.addEventListener("click", () => showView(button.dataset.view)),
);
$$("[data-tab]").forEach((button) =>
    button.addEventListener("click", () => setTab(button.dataset.tab)),
);
$(".editor-tabs").addEventListener("keydown", (event) => {
    const tabs = $$("[data-tab]");
    const index = tabs.indexOf(document.activeElement);
    if (index < 0) return;
    const next =
        event.key === "ArrowRight"
            ? (index + 1) % tabs.length
            : event.key === "ArrowLeft"
              ? (index + tabs.length - 1) % tabs.length
              : event.key === "Home"
                ? 0
                : event.key === "End"
                  ? tabs.length - 1
                  : null;
    if (next !== null) {
        event.preventDefault();
        tabs[next].focus();
    }
});
$("#table-search").addEventListener("input", renderSidebar);
$("#row-count").addEventListener("input", () => {
    tables[currentTable].count = $("#row-count").value;
    changed();
    renderSidebar();
});
$("#provider").addEventListener("change", () => {
    changed();
    notify("已切换演示配置中的数据生成引擎");
});
$("#locale").addEventListener("change", () => {
    changed();
    renderTable();
});
$("#seed").addEventListener("input", () => {
    changed();
    if (currentTab === "preview") renderPreview();
});
$("#refresh-preview").addEventListener("click", () => {
    if (currentTab === "preview") sampleRound += 1;
    setTab("preview");
});
$("#generator").addEventListener("change", () => renderGeneratorOptions());
$("#field-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const draft = validateDraft();
    if (!draft) return;
    const target = editorReturnTarget;
    tables[target.table].fields[target.index] = draft;
    changed();
    renderTable();
    $("#field-dialog").close();
    notify(`${draft.name} 的规则已应用`);
});
$("#field-dialog").addEventListener("close", () => {
    if (!editorReturnTarget || editorReturnTarget.table !== currentTable)
        return;
    const selector = editorReturnTarget.preview
        ? `[data-preview-field="${editorReturnTarget.index}"]`
        : `.rule-button[data-field="${editorReturnTarget.index}"]`;
    $(selector)?.focus({ preventScroll: true });
});
$$("[data-close]").forEach((button) =>
    button.addEventListener("click", () =>
        $(`#${button.dataset.close}`).close(),
    ),
);
$$("dialog").forEach((dialog) =>
    dialog.addEventListener("click", (event) => {
        const rect = dialog.getBoundingClientRect();
        if (
            event.target === dialog &&
            (event.clientX < rect.left ||
                event.clientX > rect.right ||
                event.clientY < rect.top ||
                event.clientY > rect.bottom)
        )
            dialog.close();
    }),
);
$("#appearance").addEventListener("click", () =>
    showDialog("appearance-dialog"),
);
function setMaterial(material, manual = false) {
    document.body.dataset.material = material;
    if (manual) document.body.dataset.transparencyOverride = "true";
    $$(".material-choice").forEach((button) => {
        const selected = button.dataset.material === material;
        button.classList.toggle("selected", selected);
        button.setAttribute("aria-pressed", String(selected));
    });
}
$$(".material-choice").forEach((button) =>
    button.addEventListener("click", () =>
        setMaterial(button.dataset.material, true),
    ),
);
$("#reduce-motion").checked = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
).matches;
$("#reduce-motion").addEventListener("change", () =>
    document.body.classList.toggle(
        "reduce-motion",
        $("#reduce-motion").checked,
    ),
);
setMaterial(
    window.matchMedia("(prefers-reduced-transparency: reduce)").matches
        ? "solid"
        : "clear",
);
$("#check-config").addEventListener("click", () => checkConfiguration());
$("#generate").addEventListener("click", () => checkConfiguration(true));
$("#save-config").addEventListener("click", saveConfiguration);
$("#action-dialog").addEventListener("close", () => {
    if (runTimer !== null) {
        clearInterval(runTimer);
        runTimer = null;
        notify("已取消模拟生成");
    }
});
$("#connection").addEventListener("click", () =>
    actionDialog(
        "shop_demo.db",
        '<div class="check-success connection-summary">' +
            icon("database") +
            '<span>SQLite · 本地演示库</span></div><dl class="connection-details"><div><dt>数据库</dt><dd><code>shop_demo.db</code></dd></div><div><dt>数据表</dt><dd>4 张表</dd></div><div><dt>连接状态</dt><dd>演示 · 未连接真实数据库</dd></div></dl><p class="action-message">包含 users、orders、products、order_items 四张表，用于体验字段规则、预览和生成流程。</p>',
        [
            {
                label: "继续体验",
                primary: true,
                action: () => $("#action-dialog").close(),
            },
        ],
        "DEMO CONNECTION",
    ),
);
document.addEventListener("keydown", (event) => {
    if (
        event.key === "/" &&
        !["INPUT", "SELECT", "TEXTAREA"].includes(
            document.activeElement.tagName,
        ) &&
        !$("dialog[open]")
    ) {
        event.preventDefault();
        $("#table-search").focus();
    }
});
