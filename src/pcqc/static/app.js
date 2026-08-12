const state = {
  config: null,
  runs: [],
  run: null,
  reviews: [],
  selectedId: null,
  action: "",
  query: "",
  file: null,
  csvText: "",
  previewRows: [],
  selectedRowIds: new Set(),
  rowSelectionQuery: "",
  pollTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeUrl(value) {
  if (typeof value !== "string" || !/^https?:\/\//i.test(value.trim())) return "";
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function money(pennies) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format((pennies || 0) / 100);
}

function titleCase(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function helpLabel(label, explanation) {
  const id = `help-${String(label).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`;
  return `<span class="term-label">${escapeHtml(label)}<span class="info-wrap"><button class="info-tip" type="button" aria-label="Explain ${escapeHtml(label)}" aria-describedby="${id}">?</button><span class="info-tooltip" id="${id}" role="tooltip">${escapeHtml(explanation)}</span></span></span>`;
}

function compactDate(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2800);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail || message; } catch { /* response was not JSON */ }
    throw new Error(message);
  }
  return response.json();
}

function blockedActionLabel(record) {
  const codes = record?.result?.rationale_codes || [];
  if (codes.some((code) => String(code).startsWith("finish_not_verified") || String(code).includes("finish_match_requires"))) {
    return "Blocked: finish not verified";
  }
  if (codes.some((code) => String(code).startsWith("catalog_image_unavailable") || String(code).startsWith("catalog_artwork_not_verified"))) {
    return "Blocked: catalog artwork unavailable";
  }
  if (codes.some((code) => String(code).startsWith("catalog_variant_family_ambiguous") || String(code).includes("catalog_unspecified"))) {
    return "Blocked: variant evidence incomplete";
  }
  if (codes.some((code) => String(code).includes("_unavailable:"))) {
    return "Blocked: enrichment unavailable";
  }
  return "No final action";
}

function actionBadge(action, record = null) {
  const labels = {
    keep: "Keep",
    delete: "Delete",
    change_condition: "Correct condition",
    reassign_product: "Reassign product",
    human_review: blockedActionLabel(record),
  };
  return `<span class="badge ${escapeHtml(action)}">${escapeHtml(labels[action] || titleCase(action))}</span>`;
}

function resolvedLabel(target) {
  const labels = {
    ignored: "Ignored (kept current assignment)",
    deleted: "Deleted",
    condition_change: "Condition changed",
    needs_modification: "Modified outside this export",
  };
  return labels[target] || "Not supplied";
}

function runIsOutdated(run) {
  return Boolean(
    run
    && state.config?.current_policy_version
    && run.policy_version !== state.config.current_policy_version
  );
}

function pocOutcome(record) {
  const result = record.result || {};
  const actions = (record.ui?.recommended_actions || []).filter((action) => action !== "human_review");
  if (actions.includes("delete") || result.decision === "deleted") {
    return { code: "delete", label: "Delete sale" };
  }
  if (actions.includes("reassign_product")) {
    return { code: "reassign_product", label: result.replacement_product_id ? `Reassign to product ${result.replacement_product_id}` : "Reassign product" };
  }
  if (actions.includes("change_condition") || result.decision === "condition_change") {
    return { code: "change_condition", label: result.predicted_condition_id ? `Change to condition ID ${result.predicted_condition_id}` : "Change condition" };
  }
  if (actions.includes("keep") || result.decision === "ignored") {
    return { code: "keep", label: "Keep sale with current product and condition" };
  }
  return { code: "unknown", label: "No substantive conclusion" };
}

function sourceOutcome(record) {
  const history = record.historical_outcome || {};
  if (history.target === "deleted") return { code: "delete", label: "Delete sale" };
  if (history.target === "ignored") return { code: "keep", label: "Keep sale with current product and condition" };
  if (history.target === "condition_change") {
    return { code: "change_condition", label: history.target_condition_id ? `Change to condition ID ${history.target_condition_id}` : "Change condition" };
  }
  if (history.target === "needs_modification") {
    return { code: "not_comparable", label: "Modified outside this export" };
  }
  return { code: "unknown", label: "No recorded outcome" };
}

function outcomeComparison(record) {
  const poc = pocOutcome(record);
  const source = sourceOutcome(record);
  if (["unknown", "not_comparable"].includes(poc.code) || ["unknown", "not_comparable"].includes(source.code)) {
    return {
      kind: "unavailable",
      label: "Comparison unavailable",
      poc,
      source,
      explanation: "The export does not contain enough information to compare the two outcomes.",
    };
  }
  const targetIdsDiffer = poc.code === "change_condition"
    && source.code === "change_condition"
    && record.result?.predicted_condition_id
    && record.historical_outcome?.target_condition_id
    && String(record.result.predicted_condition_id) !== String(record.historical_outcome.target_condition_id);
  if (poc.code !== source.code || targetIdsDiffer) {
    return {
      kind: "disagreement",
      label: "Different outcomes",
      poc,
      source,
      explanation: source.code === "delete"
        ? "The POC conclusion conflicts with PriceCharting's recorded deletion. The export does not include the deletion reason, so this difference requires human follow-up rather than assuming either side is correct."
        : "The POC conclusion conflicts with PriceCharting's recorded outcome. Review the identity and condition evidence before taking action.",
    };
  }
  return {
    kind: "agreement",
    label: "Same outcome",
    poc,
    source,
    explanation: "The POC conclusion agrees with PriceCharting's recorded outcome.",
  };
}

function variantWarningText(dimensions, siblingIds) {
  const names = dimensions.split(",").map((dimension) => ({
    finish: "finish",
    printing: "printing or parallel",
  })[dimension] || titleCase(dimension));
  return `PriceCharting contains another ${names.join(" and ")} variant in this product family (product ID ${siblingIds.split(",").join(", ")}). The listing must be compared with verified catalog artwork.`;
}

function evidenceFlagText(flag) {
  const exact = {
    discarded_irrelevant_predicted_condition_id: "The engine returned an unused condition ID without recommending a condition change. The POC discarded that value.",
    catalog_image_unavailable: "The assigned PriceCharting product image could not be retrieved and verified.",
    catalog_artwork_not_verified: "The listing image was not positively matched to the assigned PriceCharting catalog image.",
    finish_not_verified: "The card finish could not be positively matched.",
  };
  if (exact[flag]) return exact[flag];
  if (String(flag).startsWith("assigned_product_api_unavailable:")) {
    return "The assigned product could not be enriched through the PriceCharting API. Catalog evidence may be incomplete.";
  }
  if (String(flag).startsWith("candidate_search_unavailable:")) {
    return "Replacement-product search was unavailable. No candidate list should be treated as complete.";
  }
  const unspecified = String(flag).match(/^([a-z_]+)_catalog_unspecified:sale=(.+)$/);
  if (unspecified) {
    const dimension = ({
      language: "language",
      printing: "printing or parallel",
      packaging: "quantity or packaging",
      card_code: "set or card number",
      finish: "finish",
    })[unspecified[1]] || titleCase(unspecified[1]);
    return `The listing explicitly identifies ${dimension} as ${titleCase(unspecified[2])}, but the catalog text does not state it. Verify it against the assigned catalog image.`;
  }
  const variant = String(flag).match(/^catalog_variant_family_ambiguous:dimensions=([^:]+):siblings=(.+)$/);
  if (variant) return variantWarningText(variant[1], variant[2]);
  return titleCase(flag);
}

function readableReason(reason) {
  return String(reason || "").replace(
    /catalog_variant_family_ambiguous:dimensions=([^:;]+):siblings=([0-9,]+)/g,
    (_, dimensions, siblingIds) => variantWarningText(dimensions, siblingIds),
  ).replaceAll("..", ".");
}

function imageMarkup(url, alt, className = "review-thumb") {
  const safe = safeUrl(url);
  if (!safe) return `<div class="${className} thumb-placeholder">No image</div>`;
  return `<img class="${className}" src="${escapeHtml(safe)}" alt="${escapeHtml(alt)}" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'${className} thumb-placeholder', textContent:'Image unavailable'}))">`;
}

async function loadConfig() {
  state.config = await api("/api/config");
  const status = $("#systemStatus");
  status.classList.add("ready");
  status.textContent = state.config.gemini_configured ? `${state.config.main_model} ready` : "Rules mode ready";
  if (!state.config.gemini_configured) {
    const option = $('#modeInput option[value="multimodal"]');
    option.disabled = true;
    $("#modeInput").value = "rules";
  }
}

async function loadRuns(selectLatest = false) {
  state.runs = await api("/api/runs");
  renderRuns();
  if (selectLatest && !state.run && state.runs.length) await selectRun(state.runs[0].id);
}

function renderRuns() {
  const root = $("#runList");
  if (!state.runs.length) {
    root.innerHTML = '<div class="list-empty">No runs yet</div>';
    return;
  }
  root.innerHTML = state.runs.map((run) => `
    <button class="run-item ${state.run?.id === run.id ? "active" : ""}" data-run-id="${escapeHtml(run.id)}">
      <strong>${escapeHtml(run.filename)}</strong>
      <span>${escapeHtml(run.status)} - ${run.processed}/${run.total} - ${compactDate(run.created_at)}${runIsOutdated(run) ? " - OUTDATED" : ""}</span>
    </button>
  `).join("");
  $$(".run-item").forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.runId)));
}

async function selectRun(runId) {
  window.clearTimeout(state.pollTimer);
  state.run = await api(`/api/runs/${encodeURIComponent(runId)}`);
  state.selectedId = null;
  $("#welcome").classList.add("hidden");
  $("#runWorkspace").classList.remove("hidden");
  renderRuns();
  renderRun();
  await loadReviews();
  if (["queued", "running"].includes(state.run.status)) schedulePoll();
}

function renderRun() {
  const run = state.run;
  if (!run) return;
  $("#runMode").textContent = run.mode === "multimodal" ? "Gemini + images" : "Rules only";
  $("#runId").textContent = run.id;
  $("#runTitle").textContent = run.filename;
  const progress = run.total ? Math.round((run.processed / run.total) * 100) : 0;
  $("#progressBar").style.width = `${progress}%`;
  const statusCopy = {
    queued: "Queued for processing",
    running: `Reviewing evidence - ${run.processed} of ${run.total}`,
    completed: `Completed ${run.total} sales with no processing failures`,
    completed_with_errors: `Completed with ${run.failed} processing failure${run.failed === 1 ? "" : "s"}`,
    failed: "Run stopped before completion",
  };
  $("#runProgressText").textContent = statusCopy[run.status] || run.status;
  const versionNotice = $("#runVersionNotice");
  const outdated = runIsOutdated(run);
  versionNotice.classList.toggle("hidden", !outdated);
  versionNotice.innerHTML = outdated
    ? "<strong>Outdated saved run</strong><span>This run predates the current evidence policy. Rerun it before interpreting blocked or no-final-action results.</span>"
    : "";
  $("#exportButton").href = `/api/runs/${encodeURIComponent(run.id)}/export`;
  const counts = run.action_counts || {};
  const stats = [
    ["Processed", `${run.processed}/${run.total}`],
    ["Keep", counts.keep || 0],
    ["Delete", counts.delete || 0],
    ["Correct / Reassign", (counts.change_condition || 0) + (counts.reassign_product || 0)],
    ["Adjudicated", run.adjudicated || 0],
  ];
  $("#statGrid").innerHTML = stats.map(([label, value]) => `<div class="stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
}

async function loadReviews() {
  if (!state.run) return;
  const params = new URLSearchParams();
  if (state.action) params.set("action", state.action);
  if (state.query) params.set("query", state.query);
  state.reviews = await api(`/api/runs/${encodeURIComponent(state.run.id)}/reviews?${params}`);
  renderReviewList();
  if (state.selectedId) {
    const selected = state.reviews.find((record) => record.identifier === state.selectedId);
    if (selected) renderDetail(selected);
  }
}

function renderReviewList() {
  $("#queueCount").textContent = `${state.reviews.length} sale${state.reviews.length === 1 ? "" : "s"}`;
  const root = $("#reviewList");
  if (!state.reviews.length) {
    root.innerHTML = `<div class="list-empty">${state.run?.processed ? "No sales match this filter." : "Results appear here as evidence is processed."}</div>`;
    return;
  }
  root.innerHTML = state.reviews.map((record) => {
    const sale = record.sale || {};
    const actions = record.ui?.recommended_actions || ["human_review"];
    const comparison = outcomeComparison(record);
    return `
      <button class="review-card ${state.selectedId === record.identifier ? "active" : ""}" data-identifier="${escapeHtml(record.identifier)}">
        ${imageMarkup(sale.picture_url, sale.sale_title)}
        <span class="review-copy">
          <strong>${escapeHtml(sale.sale_title || record.identifier)}</strong>
          <p>${escapeHtml(sale.product_title)} - ${escapeHtml(record.identifier)}</p>
          <span class="badge-row">${comparison.kind === "disagreement" ? '<span class="badge disagreement">Differs from PriceCharting</span>' : ""}${actions.map((action) => actionBadge(action, record)).join("")}${record.adjudication ? '<span class="badge reviewed">Reviewed</span>' : ""}</span>
        </span>
        <span class="review-value">${money(sale.sale_amount_pennies)}</span>
      </button>
    `;
  }).join("");
  $$(".review-card").forEach((button) => button.addEventListener("click", () => {
    state.selectedId = button.dataset.identifier;
    renderReviewList();
    const record = state.reviews.find((item) => item.identifier === state.selectedId);
    if (record) renderDetail(record);
    if (window.innerWidth < 720) $("#detailPanel").scrollIntoView({ behavior: "smooth" });
  }));
}

function imageFrame(url, label, alt) {
  const safe = safeUrl(url);
  return `
    <div class="image-card">
      <div class="image-label"><span>${escapeHtml(label)}</span>${safe ? `<a href="${escapeHtml(safe)}" target="_blank" rel="noreferrer">Open &nearr;</a>` : ""}</div>
      <div class="image-frame">${safe ? `<img src="${escapeHtml(safe)}" alt="${escapeHtml(alt)}">` : '<span class="image-missing">Image not available</span>'}</div>
    </div>
  `;
}

function renderDetail(record) {
  const sale = record.sale || {};
  const result = record.result || {};
  const evidence = record.evidence || {};
  const catalog = evidence.catalog || {};
  const ui = record.ui || {};
  const comparisons = result.identity_comparison || {};
  const candidates = evidence.replacement_candidates || [];
  const conditionCatalog = evidence.condition_catalog || {};
  const ebayUrl = /^\d+$/.test(record.identifier) ? `https://www.ebay.com/itm/${record.identifier}` : "";
  const productUrl = safeUrl(catalog.page_url);
  const reason = readableReason(record.error ? `Processing error: ${record.error}` : result.reason || "No model result is available yet.");
  const history = record.historical_outcome || {};
  const evidenceAndFlags = ui.evidence_and_flags || ui.evidence_facts || [];
  const adjudication = record.adjudication || {};
  const requiresManualVerification = (ui.recommended_actions || []).includes("human_review");
  const outdatedRun = runIsOutdated(state.run);
  const comparison = outcomeComparison(record);
  const currentCondition = conditionCatalog[String(sale.original_condition_id)] || `Condition ${sale.original_condition_id}`;
  const recommendedCondition = result.predicted_condition_id
    ? conditionCatalog[String(result.predicted_condition_id)] || `Condition ${result.predicted_condition_id}`
    : "No condition change";
  let historicalTargetCondition = "Not available in export";
  if (history.target_condition_id) {
    historicalTargetCondition = conditionCatalog[String(history.target_condition_id)] || `Condition ${history.target_condition_id}`;
  } else if (history.target === "deleted") {
    historicalTargetCondition = "Not applicable - sale deleted";
  } else if (history.target === "ignored") {
    historicalTargetCondition = "No condition change";
  }

  $("#detailPanel").innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <div>
          <span class="eyebrow">Sale ${escapeHtml(record.identifier)}</span>
          <h2>${escapeHtml(sale.sale_title)}</h2>
          <p>Assigned to ${escapeHtml(sale.product_title)} - ${escapeHtml(currentCondition)} (ID ${escapeHtml(sale.original_condition_id)})</p>
        </div>
        <span class="sale-amount">${money(sale.sale_amount_pennies)}</span>
      </div>
      <div class="detail-actions">
        ${comparison.kind === "disagreement" ? '<span class="badge disagreement">Differs from PriceCharting</span>' : ""}
        ${(ui.recommended_actions || ["human_review"]).map((action) => actionBadge(action, record)).join("")}
        ${ebayUrl ? `<a class="badge" href="${ebayUrl}" target="_blank" rel="noreferrer">eBay &nearr;</a>` : ""}
        ${productUrl ? `<a class="badge" href="${escapeHtml(productUrl)}" target="_blank" rel="noreferrer">PriceCharting &nearr;</a>` : ""}
      </div>
    </div>

    <section class="outcome-comparison ${escapeHtml(comparison.kind)}">
      <div class="outcome-comparison-heading">
        <span>${escapeHtml(comparison.label)}</span>
        <strong>${comparison.kind === "disagreement" ? "POC and PriceCharting disagree" : comparison.kind === "agreement" ? "POC and PriceCharting agree" : "A direct comparison is not possible"}</strong>
      </div>
      <div class="outcome-pair">
        <div><span>POC conclusion</span><strong>${escapeHtml(comparison.poc.label)}</strong></div>
        <b aria-hidden="true">${comparison.kind === "disagreement" ? "&ne;" : comparison.kind === "agreement" ? "=" : "?"}</b>
        <div><span>PriceCharting recorded outcome</span><strong>${escapeHtml(comparison.source.label)}</strong></div>
      </div>
      <p>${escapeHtml(comparison.explanation)}</p>
    </section>

    <section class="decision-compare">
      <div class="decision-card model-decision">
        <div class="decision-card-heading"><span>POC output</span><b>${escapeHtml(result.model || "No result")}</b></div>
        <dl>
          <div><dt>${helpLabel("POC conclusion", "The substantive outcome found by the combined model and deterministic checks. It can remain provisional when a safety check requires manual verification.")}</dt><dd>${escapeHtml(comparison.poc.label)}</dd></div>
          <div><dt>${helpLabel("Recommended next step", "What the reviewer should do next. A blocked result means the POC conclusion is visible, but a named evidence gap prevents a final action.")}</dt><dd>${(ui.recommended_actions || ["human_review"]).map((action) => actionBadge(action, record)).join("")}</dd></div>
          <div><dt>${helpLabel("Recommended condition", "The condition the POC recommends. No condition change means it did not propose a different condition ID.")}</dt><dd>${escapeHtml(recommendedCondition)}${result.predicted_condition_id ? ` (ID ${escapeHtml(result.predicted_condition_id)})` : ""}</dd></div>
          <div><dt>${helpLabel("Replacement product", "The PriceCharting product ID proposed when the assigned catalog product appears wrong. None selected means the POC did not identify a safe replacement.")}</dt><dd>${escapeHtml(result.replacement_product_id || "None selected")}</dd></div>
          <div class="no-score"><dt>${helpLabel("Model confidence", "Not produced. The POC does not generate a confidence percentage; routing relies on explicit evidence and deterministic safety rules.")}</dt><dd>Not produced <small>This POC does not generate a confidence percentage.</small></dd></div>
        </dl>
      </div>
      <div class="decision-card feed-decision">
        <div class="decision-card-heading"><span>PriceCharting recorded outcome</span><b>Not model input</b></div>
        <dl>
          <div><dt>${helpLabel("Recorded outcome", "The outcome represented by PriceCharting's historical status. This is compared directly with the POC conclusion above.")}</dt><dd>${escapeHtml(comparison.source.label)}</dd></div>
          <div><dt>${helpLabel("Source status", "The exact status value from the PriceCharting CSV, shown without reinterpretation.")}</dt><dd>${escapeHtml(history.status_raw || "Not supplied")}</dd></div>
          <div><dt>${helpLabel("Resolved label", "Resolved label is our normalized evaluation category. For PriceCharting, Ignored means the reviewer kept the current product and condition.")}</dt><dd>${escapeHtml(resolvedLabel(history.target))}</dd></div>
          <div><dt>${helpLabel("Condition outcome", "A condition target derived from a condition-status slug. It is not applicable when the historical outcome was deletion.")}</dt><dd>${escapeHtml(historicalTargetCondition)}</dd></div>
          <div class="no-score"><dt>${helpLabel("Source score", "Copied directly from the CSV score column. PriceCharting has not documented its calculation or scale. It is not model or reviewer confidence and is not sent to Gemini.")}</dt><dd>${history.score ?? "Not supplied"}<small>Meaning and scale are undocumented by PriceCharting.</small></dd></div>
        </dl>
      </div>
    </section>

    <div class="action-banner"><span>Why the POC reached this conclusion</span><strong>${escapeHtml(reason)}</strong></div>

    <div class="image-compare">
      ${imageFrame(sale.picture_url, "eBay listing", sale.sale_title)}
      ${imageFrame(catalog.image_url, "Assigned catalog", sale.product_title)}
    </div>

    <section class="identity-section">
      <div class="section-heading"><h3>Identity comparison</h3><span>No aggregate confidence</span></div>
      <div class="identity-grid">
        ${Object.entries(comparisons).map(([dimension, value]) => `<div class="identity-item"><span>${escapeHtml(titleCase(dimension))}</span><i class="state ${escapeHtml(value)}" title="${escapeHtml(value)}"></i></div>`).join("") || '<div class="list-empty">No identity comparison available.</div>'}
      </div>
    </section>

    <section class="evidence-section">
      <div class="section-heading"><h3>Evidence and review flags</h3><span>${evidenceAndFlags.length} recorded</span></div>
      <div class="evidence-list">
        ${evidenceAndFlags.map((fact) => `<div class="evidence-fact">${escapeHtml(evidenceFlagText(fact))}</div>`).join("") || '<div class="evidence-fact">No evidence conflicts or review warnings were recorded.</div>'}
      </div>
    </section>

    ${candidates.length ? `
      <section class="candidate-section">
        <div class="section-heading"><h3>Replacement candidates</h3><span>Retrieval is not proof</span></div>
        <div class="candidate-list">
          ${candidates.slice(0, 5).map((candidate) => {
            const url = safeUrl(candidate.catalog?.page_url);
            const body = `<span><strong>${escapeHtml(candidate.product_name)}</strong><span>${escapeHtml(candidate.console_name || "Catalog set unavailable")} - ID ${escapeHtml(candidate.product_id)}</span></span><b>${candidate.catalog?.product_id_verified ? "Catalog verified" : "Catalog unverified"}</b>`;
            return url ? `<a class="candidate" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${body}</a>` : `<div class="candidate">${body}</div>`;
          }).join("")}
        </div>
      </section>
    ` : ""}

    <section class="adjudication-section">
      <div class="section-heading"><h3>Your review decision</h3><span>${record.adjudication ? `Saved ${compactDate(record.adjudication.reviewed_at)}` : "Required before action"}</span></div>
      <div class="adjudication-controls">
        ${outdatedRun ? '<div class="adjudication-help stale"><strong>Do not adjudicate this saved result yet</strong><span>It was generated under an earlier evidence policy. Rerun the row first; catalog and variant fixes may change the blocked status.</span></div>' : requiresManualVerification ? `<div class="adjudication-help"><strong>Why is there no final action?</strong><span>${escapeHtml(blockedActionLabel(record))}. The POC conclusion remains provisional until this evidence gap is resolved.</span></div>` : ""}
        <div class="adjudication-facts">
          <label><span>Sale validity</span><small>Should this completed sale be included? Choose uncertain when a historical deletion reason is unavailable.</small><select id="listingValidity" aria-label="Sale validity" ${outdatedRun ? "disabled" : ""}><option value="">Choose...</option><option value="valid">Valid sale</option><option value="invalid">Invalid sale</option><option value="uncertain">Cannot determine</option></select></label>
          <label><span>Product assignment</span><small>Does the listing match the currently assigned PriceCharting product?</small><select id="productAssignment" aria-label="Product assignment" ${outdatedRun ? "disabled" : ""}><option value="">Choose...</option><option value="correct">Correct product</option><option value="incorrect">Wrong product</option><option value="uncertain">Cannot determine</option></select></label>
          <label><span>Condition assignment</span><small>Does the listing match the currently assigned condition ID?</small><select id="conditionAssignment" aria-label="Condition assignment" ${outdatedRun ? "disabled" : ""}><option value="">Choose...</option><option value="correct">Correct condition</option><option value="incorrect">Wrong condition</option><option value="uncertain">Cannot determine</option></select></label>
        </div>
        <div class="adjudication-row">
          <select id="overrideAction" aria-label="Adjudication action" ${outdatedRun ? "disabled" : ""}>
            ${requiresManualVerification ? `
              <option value="needs_follow_up">Final action: needs follow-up</option>
              <option value="keep">Final action: keep sale</option>
              <option value="delete">Final action: delete sale</option>
              <option value="change_condition">Final action: change condition</option>
              <option value="reassign_product">Final action: reassign product</option>
            ` : `
              <option value="accepted">Accept POC recommendation</option>
              <option value="keep">Override: keep sale</option>
              <option value="delete">Override: delete sale</option>
              <option value="change_condition">Override: change condition</option>
              <option value="reassign_product">Override: reassign product</option>
              <option value="needs_follow_up">Needs follow-up</option>
            `}
          </select>
          <button class="button button-primary" id="saveAdjudication" ${outdatedRun ? "disabled" : ""}>${outdatedRun ? "Rerun required" : "Save decision"}</button>
        </div>
        <textarea id="adjudicationNotes" placeholder="Optional evidence note, including anything the export cannot explain" ${outdatedRun ? "disabled" : ""}>${escapeHtml(adjudication.notes || "")}</textarea>
      </div>
    </section>

  `;
  if (record.adjudication) {
    $("#overrideAction").value = adjudication.action;
    $("#listingValidity").value = adjudication.listing_validity || "";
    $("#productAssignment").value = adjudication.product_assignment || "";
    $("#conditionAssignment").value = adjudication.condition_assignment || "";
  }
  if (!outdatedRun) $("#saveAdjudication").addEventListener("click", saveAdjudication);
}

async function saveAdjudication() {
  if (!state.run || !state.selectedId) return;
  const action = $("#overrideAction").value;
  const listingValidity = $("#listingValidity").value;
  const productAssignment = $("#productAssignment").value;
  const conditionAssignment = $("#conditionAssignment").value;
  if (!listingValidity || !productAssignment || !conditionAssignment) {
    showToast("Choose all three evidence judgments before saving");
    return;
  }
  const notes = $("#adjudicationNotes").value;
  const updated = await api(`/api/runs/${encodeURIComponent(state.run.id)}/reviews/${encodeURIComponent(state.selectedId)}/adjudication`, {
    method: "PUT",
    body: JSON.stringify({
      action,
      listing_validity: listingValidity,
      product_assignment: productAssignment,
      condition_assignment: conditionAssignment,
      notes,
    }),
  });
  const index = state.reviews.findIndex((record) => record.identifier === state.selectedId);
  if (index >= 0) state.reviews[index] = updated;
  state.run = await api(`/api/runs/${encodeURIComponent(state.run.id)}`);
  renderRun();
  renderReviewList();
  renderDetail(updated);
  showToast("Human decision saved");
}

function schedulePoll() {
  window.clearTimeout(state.pollTimer);
  state.pollTimer = window.setTimeout(async () => {
    if (!state.run) return;
    state.run = await api(`/api/runs/${encodeURIComponent(state.run.id)}`);
    renderRun();
    await loadReviews();
    await loadRuns();
    if (["queued", "running"].includes(state.run.status)) schedulePoll();
  }, 1800);
}

function openUpload() {
  $("#uploadError").classList.add("hidden");
  $("#uploadDialog").showModal();
}

function matchingPreviewRows() {
  const query = state.rowSelectionQuery.trim().toLowerCase();
  if (!query) return state.previewRows;
  return state.previewRows.filter((row) => [
    row.identifier,
    row.product_id,
    row.product_title,
    row.sale_title,
  ].some((value) => String(value || "").toLowerCase().includes(query)));
}

function renderRowSelector() {
  const panel = $("#rowSelector");
  const randomControl = $("#randomSampleControl");
  const selectionMode = $("#rowSelectionMode").value;
  randomControl.classList.toggle("hidden", selectionMode !== "random");
  if (!state.previewRows.length) {
    panel.classList.add("hidden");
    return;
  }
  const button = $("#startRunButton");
  if (selectionMode === "random") {
    panel.classList.add("hidden");
    const requested = Number($("#randomSampleSize").value);
    const sampleSize = Math.min(requested, state.previewRows.length, state.config.max_run_rows);
    const valid = Number.isInteger(requested) && requested >= 1;
    button.disabled = !valid;
    button.textContent = valid ? `Start random sample (${sampleSize})` : "Enter a sample size";
    return;
  }
  panel.classList.remove("hidden");
  const matching = matchingPreviewRows();
  const visible = matching.slice(0, 200);
  $("#selectedRowCount").textContent = `${state.selectedRowIds.size} of ${state.previewRows.length} selected`;
  $("#selectableRowList").innerHTML = visible.length ? visible.map((row) => `
    <label class="selectable-row">
      <input type="checkbox" value="${escapeHtml(row.identifier)}" ${state.selectedRowIds.has(row.identifier) ? "checked" : ""}>
      <span class="selectable-row-copy">
        <strong>${escapeHtml(row.identifier)}</strong>
        <span>${escapeHtml(row.sale_title)}</span>
        <small>Product ${escapeHtml(row.product_id)} &middot; ${escapeHtml(row.product_title)} &middot; ${escapeHtml(money(row.sale_amount_pennies))}</small>
      </span>
    </label>
  `).join("") : '<div class="selector-empty">No rows match that listing ID or title.</div>';
  const hiddenMatches = matching.length - visible.length;
  $("#rowSelectorNote").textContent = hiddenMatches > 0
    ? `${matching.length} matches. Refine your search to see the remaining ${hiddenMatches}.`
    : `${matching.length} matching row${matching.length === 1 ? "" : "s"}. Only selected rows will use scoring or model calls.`;
  button.disabled = state.selectedRowIds.size === 0;
  button.textContent = state.selectedRowIds.size ? `Start review (${state.selectedRowIds.size})` : "Select at least one row";
}

async function updateFile(file) {
  if (!file) return;
  state.file = file;
  state.csvText = "";
  state.previewRows = [];
  state.selectedRowIds.clear();
  state.rowSelectionQuery = "";
  $("#rowSearchInput").value = "";
  $("#rowSelector").classList.add("hidden");
  $("#uploadError").classList.add("hidden");
  $("#dropTitle").textContent = file.name;
  $("#dropHint").textContent = `${(file.size / 1024).toFixed(1)} KB - reading feed rows...`;
  const button = $("#startRunButton");
  button.disabled = true;
  button.textContent = "Reading rows...";
  try {
    const csvText = await file.text();
    const preview = await api("/api/runs/preview", {
      method: "POST",
      body: JSON.stringify({ csv_text: csvText }),
    });
    if (state.file !== file) return;
    state.csvText = csvText;
    state.previewRows = preview.rows;
    const sampleInput = $("#randomSampleSize");
    sampleInput.max = Math.min(state.config.max_run_rows, preview.total);
    sampleInput.value = Math.min(Number(sampleInput.value) || 15, preview.total);
    $("#dropHint").textContent = `${preview.total} feed rows ready - choose random or specific rows below`;
    renderRowSelector();
  } catch (error) {
    if (state.file !== file) return;
    $("#uploadError").textContent = error.message;
    $("#uploadError").classList.remove("hidden");
    $("#dropHint").textContent = "This file could not be previewed";
    button.disabled = true;
    button.textContent = "Select a valid CSV";
  }
}

async function startRun(event) {
  event.preventDefault();
  if (!state.file) {
    $("#uploadError").textContent = "Choose a CSV file first.";
    $("#uploadError").classList.remove("hidden");
    return;
  }
  const selectionMode = $("#rowSelectionMode").value;
  if (selectionMode === "specific" && !state.selectedRowIds.size) {
    $("#uploadError").textContent = "Select at least one listing row to score.";
    $("#uploadError").classList.remove("hidden");
    return;
  }
  const randomSampleSize = Number($("#randomSampleSize").value);
  if (selectionMode === "random" && (!Number.isInteger(randomSampleSize) || randomSampleSize < 1)) {
    $("#uploadError").textContent = "Enter at least one row for the random sample.";
    $("#uploadError").classList.remove("hidden");
    return;
  }
  const button = $("#startRunButton");
  button.disabled = true;
  button.textContent = "Creating run...";
  try {
    const selection = selectionMode === "specific"
      ? { selected_identifiers: [...state.selectedRowIds] }
      : { random_sample_size: randomSampleSize };
    const run = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        filename: state.file.name,
        csv_text: state.csvText,
        mode: $("#modeInput").value,
        ...selection,
      }),
    });
    $("#uploadDialog").close();
    state.file = null;
    state.csvText = "";
    state.previewRows = [];
    state.selectedRowIds.clear();
    state.rowSelectionQuery = "";
    $("#fileInput").value = "";
    $("#rowSearchInput").value = "";
    $("#rowSelector").classList.add("hidden");
    $("#dropTitle").textContent = "Drop a PriceCharting export here";
    $("#dropHint").textContent = "or choose a file from this computer";
    await loadRuns();
    await selectRun(run.id);
    showToast("Review run started");
  } catch (error) {
    $("#uploadError").textContent = error.message;
    $("#uploadError").classList.remove("hidden");
  } finally {
    if (state.file) {
      renderRowSelector();
    } else {
      button.disabled = false;
      button.textContent = "Start review";
    }
  }
}

function bindEvents() {
  ["#welcomeUpload", "#headerUpload"].forEach((selector) => $(selector).addEventListener("click", openUpload));
  $("#refreshRuns").addEventListener("click", () => loadRuns());
  $("#uploadForm").addEventListener("submit", startRun);
  $$(".close-dialog").forEach((button) => button.addEventListener("click", () => $("#uploadDialog").close()));
  $("#fileInput").addEventListener("change", (event) => updateFile(event.target.files[0]));
  $("#rowSelectionMode").addEventListener("change", renderRowSelector);
  $("#randomSampleSize").addEventListener("input", renderRowSelector);
  $("#rowSearchInput").addEventListener("input", (event) => {
    state.rowSelectionQuery = event.target.value;
    renderRowSelector();
  });
  $("#selectableRowList").addEventListener("change", (event) => {
    const checkbox = event.target.closest('input[type="checkbox"]');
    if (!checkbox) return;
    if (checkbox.checked) {
      if (state.selectedRowIds.size >= state.config.max_run_rows) {
        checkbox.checked = false;
        showToast(`A run is limited to ${state.config.max_run_rows} rows`);
        return;
      }
      state.selectedRowIds.add(checkbox.value);
    } else {
      state.selectedRowIds.delete(checkbox.value);
    }
    renderRowSelector();
  });
  $("#selectVisibleRows").addEventListener("click", () => {
    const available = state.config.max_run_rows - state.selectedRowIds.size;
    matchingPreviewRows().filter((row) => !state.selectedRowIds.has(row.identifier)).slice(0, available)
      .forEach((row) => state.selectedRowIds.add(row.identifier));
    renderRowSelector();
  });
  $("#clearSelectedRows").addEventListener("click", () => {
    state.selectedRowIds.clear();
    renderRowSelector();
  });
  const drop = $("#dropZone");
  ["dragenter", "dragover"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.remove("dragging"); }));
  drop.addEventListener("drop", (event) => updateFile(event.dataTransfer.files[0]));
  $("#filters").addEventListener("click", async (event) => {
    const button = event.target.closest(".filter");
    if (!button) return;
    state.action = button.dataset.action;
    $$(".filter").forEach((item) => item.classList.toggle("active", item === button));
    await loadReviews();
  });
  let searchTimer;
  $("#searchInput").addEventListener("input", (event) => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(async () => { state.query = event.target.value; await loadReviews(); }, 220);
  });
}

async function init() {
  bindEvents();
  try {
    await loadConfig();
    await loadRuns(true);
  } catch (error) {
    $("#systemStatus").textContent = "Service unavailable";
    showToast(error.message);
  }
}

document.addEventListener("DOMContentLoaded", init);
