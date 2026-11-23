const conversations = '/teacher-agent/conversations';
const basisLabels = {current_effective_archives: '当前有效归档', submitted_latest: '最新提交版本'};
const allowedEvidence = /^\/api\/v1\/(?:submissions\/[A-Za-z0-9-]+|students\/[A-Za-z0-9-]+\/portrait|files\/[A-Za-z0-9-]+\/download)$/;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(label, action) {
  const node = element('button', label, 'btn');
  node.type = 'button';
  node.onclick = action;
  return node;
}

function evidenceLink(parent, url, label) {
  if (typeof url !== 'string' || !allowedEvidence.test(url)) return;
  const link = element('a', label);
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  parent.append(link);
}

function clarification(prompt) {
  const box = element('div', prompt.message, 'callout');
  for (const suggestion of prompt.suggestions || []) box.append(element('p', suggestion));
  for (const candidate of prompt.student_candidates || []) {
    box.append(element('p', [candidate.student_name, candidate.year, candidate.major].join(' · ')));
  }
  return box;
}

function analysisParagraph(text, targets) {
  const paragraph = element('p', null, 'agent-analysis');
  let offset = 0;
  for (const match of text.matchAll(/\[(?:run )?([a-zA-Z0-9_-]+)\]/g)) {
    const card = targets.get(match[1]);
    if (!card) continue;
    const link = element('a', match[0]);
    link.href = '#' + card.id;
    link.onclick = event => {
      event.preventDefault();
      card.focus({preventScroll: true});
      card.scrollIntoView({block: 'start'});
    };
    paragraph.append(text.slice(offset, match.index), link);
    offset = match.index + match[0].length;
  }
  paragraph.append(text.slice(offset));
  return paragraph;
}

function resultCard(result, submit) {
  const card = element('section', null, 'evidence agent-result');
  if (result.query_run_id) {
    card.id = 'agent-run-' + result.query_run_id;
    card.tabIndex = -1;
  }
  const summary = result.summary;
  if (!summary) return card;
  card.append(element('h4', summary.headline), element('p', [
    basisLabels[summary.basis] || summary.basis, `授权范围 ${summary.scope_student_count} 人`,
    `数据时间 ${summary.data_as_of}`, summary.scope_recomputed ? '已按当前授权范围重新计算' : ''
  ].filter(Boolean).join(' · ')));
  const metrics = element('div', null, 'actions');
  function metric(label, patch) {
    metrics.append(result.query_run_id && patch ? button(label, () => submit({
      mode: 'drilldown_patch', parent_run_id: result.query_run_id, patch, label
    })) : element('span', label, 'badge'));
  }
  for (const item of summary.metrics) metric(`${item.label} ${item.value} ${item.unit}`, item.drilldown_patch);
  for (const row of summary.breakdown) {
    metric(`${row.label} · ${row.record_count} 条记录 / ${row.student_count} 人`, row.drilldown_patch);
  }
  card.append(metrics);
  for (const item of result.items) {
    const row = element('div', null, 'agent-row');
    row.append(element('strong', item.title || item.student_name),
      element('span', item.item_kind === 'student_summary' ? `匹配 ${item.matched_record_count} 条记录` : item.student_name));
    evidenceLink(row, item.links?.submission_url, '提交材料');
    evidenceLink(row, item.links?.portrait_url, '学生画像');
    card.append(row);
  }
  if (result.portrait) {
    const portrait = result.portrait;
    const row = element('div', null, 'agent-row');
    row.append(element('strong', portrait.student_name), element('span', `${portrait.major} · ${portrait.stage}`));
    evidenceLink(row, portrait.portrait_url, '学生画像');
    card.append(row, element('p', portrait.notice));
  }
  for (const source of result.sources) {
    const details = element('details');
    const title = source.field_pointers.find(field => field.field === 'title')?.value;
    details.append(element('summary', [title || '材料依据', `提交版本 ${source.version_number}`,
      source.simulation ? '模拟材料' : ''].filter(Boolean).join(' · ')));
    for (const field of source.field_pointers) details.append(element('p', `${field.field} · ${field.value}`));
    const links = element('div', null, 'agent-row');
    evidenceLink(links, source.submission_url, '原始提交');
    evidenceLink(links, source.portrait_url, '学生画像');
    for (const file of source.files) evidenceLink(links, file.download_url, file.name);
    details.append(links);
    card.append(details);
  }
  card.append(element('p', summary.notice));
  return card;
}

export function mountConversation(root, api) {
  root.innerHTML = `<fieldset class="agent-panel" aria-label="论文查询对话">
    <div class="card toolbar"><label>最近对话 <select name="conversation"></select></label>
    <button type="button" class="btn" name="refresh">刷新对话</button></div>
    <div class="agent-timeline"></div>
    <form class="card detail-content form-grid"><label class="full">你的问题
    <textarea name="question" maxlength="2000" required placeholder="例如：今年已发表的论文涉及多少名学生？"></textarea></label>
    <div class="actions full"><button class="btn primary">发送问题</button></div></form></fieldset>
    <p role="status" aria-live="polite"></p>`;
  const panel = root.querySelector('fieldset');
  const picker = root.querySelector('select');
  const timeline = root.querySelector('.agent-timeline');
  const form = root.querySelector('form');
  const question = form.elements.question;
  const status = root.querySelector('[role=status]');
  let conversation = null, turns = [], cards = new Map(), summaries = [];
  let createKey = crypto.randomUUID(), lastWrite = null;
  let refreshPending = false;

  function saveResults(turn, results, legacy) {
    if (legacy?.clarification && !legacy.query_run_id) turn.clarification ??= legacy.clarification;
    const seen = new Set();
    cards.set(turn.id, (results ?? (legacy?.query_run_id ? [legacy] : [])).filter(result => {
      const id = result.query_run_id;
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    }));
  }

  function options(selected) {
    picker.replaceChildren(new Option('新对话', ''));
    for (const item of summaries) {
      picker.add(new Option(`${item.title} · ${item.updated_at.slice(0, 16).replace('T', ' ')} · ${item.turn_count} 轮`, item.id));
    }
    picker.value = selected || '';
  }

  function draw() {
    timeline.replaceChildren();
    for (const turn of turns) {
      const section = element('article', null, 'card detail-content');
      timeline.append(section);
      section.append(element('h2', `第 ${turn.turn_index} 轮`));
      if (turn.access_revoked) {
        section.append(element('p', '查询范围已变更，本轮内容不可查看。'));
        continue;
      }
      section.append(element('h3', turn.user_message));
      const results = cards.get(turn.id) || [];
      const targets = new Map();
      const serializedTurnPrompt = JSON.stringify(turn.clarification);
      const resultNodes = results.map(result => {
        const card = resultCard(result, submit);
        if (result.clarification && JSON.stringify(result.clarification) !== serializedTurnPrompt) {
          card.prepend(clarification(result.clarification));
        }
        if (result.query_run_id) targets.set(result.query_run_id, card);
        return card;
      });
      if (turn.analysis) section.append(element('h4', 'Pi 分析'), analysisParagraph(turn.analysis, targets));
      if (turn.analysisNotice) section.append(element('h4', '系统说明'), element('p', turn.analysisNotice, 'callout'));
      section.append(...resultNodes);
      if (turn.clarification) section.append(clarification(turn.clarification));
      if (!cards.has(turn.id)) {
        const runIds = turn.run_ids ?? (turn.run_id ? [turn.run_id] : []);
        if (runIds.length) section.append(button('查看本轮结果', () => readHistory(turn.id)));
      }
      if (!results.length && turn.status === 'failed') section.append(element('p', '本轮查询失败。'));
    }
    form.querySelector('button').textContent = turns.length ? '发送追问' : '发送问题';
  }

  async function busy(message, task) {
    if (panel.disabled) return;
    panel.disabled = true;
    status.textContent = message;
    try {
      await task();
      status.textContent = '';
    } catch (error) {
      status.textContent = error.message;
    } finally {
      panel.disabled = false;
      if (refreshPending) refreshConversation();
    }
  }

  function clearDetail() {
    conversation = null;
    turns = [];
    cards.clear();
    draw();
  }

  async function loadDetail(selected) {
    clearDetail();
    if (selected) {
      const detail = await api(`${conversations}/${encodeURIComponent(selected)}`);
      conversation = detail.conversation;
      turns = detail.turns;
      const last = turns.at(-1);
      if (last && !last.access_revoked) {
        saveResults(last, detail.latest_results, detail.latest_result);
      }
      draw();
    }
    if (!refreshPending) timeline.hidden = false;
  }

  async function refresh(initial = false) {
    const selected = picker.value;
    clearDetail();
    summaries = [];
    picker.replaceChildren(new Option(selected ? '当前对话' : '新对话', selected));
    summaries = (await api(conversations)).filter(item => item.active_domain === 'paper');
    const next = initial ? summaries[0]?.id : selected;
    options(next);
    if (selected && !picker.value) question.value = '';
    await loadDetail(picker.value);
  }

  function refreshConversation() {
    timeline.hidden = true;
    refreshPending = panel.disabled;
    if (!refreshPending) return busy('正在刷新对话…', refresh);
  }

  function readHistory(turnId) {
    return busy('正在按当前授权范围读取历史结果…', async () => {
      await loadDetail(picker.value);
      const turn = turns.find(item => item.id === turnId);
      if (!turn || turn.access_revoked || cards.has(turnId)) return;
      const ids = turn.run_ids ?? (turn.run_id ? [turn.run_id] : []);
      try {
        const results = await Promise.all([...new Set(ids)].map(run => api(`/teacher-agent/runs/${encodeURIComponent(run)}`)));
        saveResults(turn, results);
        draw();
      } catch (error) {
        clearDetail();
        throw error;
      }
    });
  }

  function submit(input) {
    return busy('正在查询论文资料…', async () => {
      if (!conversation) {
        if (picker.value) throw Error('请先刷新对话，再发送问题。');
        conversation = await api(conversations, {method: 'POST', key: createKey, body: JSON.stringify({domain: 'paper'})});
        if (!root.isConnected) return;
        summaries.unshift(conversation);
        options(conversation.id);
        createKey = crypto.randomUUID();
      }
      const path = `${conversations}/${encodeURIComponent(conversation.id)}/turns`;
      const signature = JSON.stringify(input);
      if (lastWrite?.path !== path || lastWrite.signature !== signature) {
        lastWrite = {path, signature, key: crypto.randomUUID(),
          body: JSON.stringify({expected_lock_version: conversation.lock_version, input})};
      }
      let reply;
      try {
        reply = await api(path, {method: 'POST', body: lastWrite.body, key: lastWrite.key});
      } catch (error) {
        if (error.status >= 400 && error.status < 500) lastWrite = null;
        await loadDetail(conversation.id);
        throw error;
      }
      lastWrite = null;
      if (input.mode === 'natural_language') question.value = '';
      if (turns.some(item => item.id === reply.turn.id)) {
        await loadDetail(conversation.id);
        const saved = turns.find(item => item.id === reply.turn.id);
        if (saved && !saved.access_revoked && input.mode === 'natural_language') {
          saved.user_message = input.message;
          draw();
        }
        return;
      }
      const turn = {...reply.turn, analysis: reply.analysis ?? reply.turn.analysis,
        analysisNotice: reply.analysis_notice,
        user_message: input.mode === 'natural_language' ? input.message : reply.turn.user_message};
      turns.push(turn);
      saveResults(turn, reply.results, reply.result);
      conversation.lock_version = reply.conversation_lock_version;
      summaries = [{...conversation, turn_count: turn.turn_index, updated_at: turn.created_at},
        ...summaries.filter(item => item.id !== conversation.id)];
      options(conversation.id);
      draw();
      timeline.lastElementChild?.scrollIntoView({block: 'nearest'});
    });
  }

  picker.onchange = () => {
    question.value = '';
    createKey = crypto.randomUUID();
    lastWrite = null;
    busy('正在读取对话…', () => loadDetail(picker.value));
  };
  root.querySelector('[name=refresh]').onclick = refreshConversation;
  form.onsubmit = event => {
    event.preventDefault();
    const message = question.value.trim();
    if (message) submit({mode: 'natural_language', message});
  };
  busy('正在读取最近对话…', () => refresh(true));
  return refreshConversation;
}
