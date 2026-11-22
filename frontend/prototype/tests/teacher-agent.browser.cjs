const {after, before, test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');

let server, browser, origin;
before(async () => {
  const {createServer} = await import('vite');
  server = await createServer({
    root: path.resolve(__dirname, '../..'),
    server: {host: '127.0.0.1', port: 0},
    optimizeDeps: {entries: ['index.html', 'prototype/index.html']},
    logLevel: 'error'
  });
  await server.listen();
  origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch();
});
after(async () => {
  try {
    await browser?.close();
  } finally {
    await server?.close();
  }
});

const stamp = '2026-11-19T08:00:00Z';
const firstRun = '62b00623-40e9-4856-a1eb-ed490e93912a';
const secondRun = 'run_174e0b06-65e3-43f3-86a5-892a3ff35628';
const analysis = `先统计论文 [${firstRun}]，再查看名单 [${secondRun}]。\n<b>分析原文</b> [00000000-0000-4000-8000-000000000000]`;
const notice = '分析原文中的 <b>数值</b> 未能核实，请查看查询结果。';
const patch = {operation: 'list', group_by: [], include: ['items', 'sources']};
const csrfToken = 'fixture-csrf';
const conversationDetail = '/teacher-agent/conversations/c1';

async function openWorkspace(testContext, role, entry, payloads = {}) {
  const context = await browser.newContext({serviceWorkers: 'block'});
  testContext.after(() => context.close());
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  const errors = [], writes = [], reads = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.origin !== origin) errors.push(`External request: ${url.origin}`);
  });
  const faults = {revoked: false, failRead: false, loseReply: false, detailGate: null};
  let created = false;
  const receipts = new Map();
  const turns = [], results = [];
  const summary = () => ({id: 'c1', title: '论文查询', active_domain: 'paper',
    turn_count: turns.length, lock_version: turns.length, updated_at: stamp});
  const run = (id, title, amount) => ({
    query_run_id: id, status: 'ok',
    summary: {headline: title, metrics: [{label: '涉及学生', value: amount, unit: '人', drilldown_patch: patch}],
      breakdown: [], scope_student_count: 7, basis: 'submitted_latest', data_as_of: stamp, notice: '依据正式提交版本'},
    items: [{item_kind: 'paper_record', title: '已提交论文', student_name: '学生甲',
      links: {submission_url: '/api/v1/submissions/sub-1', portrait_url: '/api/v1/students/stu-1/portrait'}}],
    sources: [{version_number: 2, field_pointers: [], submission_url: '/api/v1/submissions/sub-1',
      portrait_url: '/api/v1/students/stu-1/portrait', files: [
        {name: '证明.pdf', download_url: '/api/v1/files/f-1/download'},
        {name: '无效地址', download_url: 'data:text/plain,invalid'}]}]
  });
  await context.route(url => url.origin === origin && url.pathname.startsWith('/api/v1/'), async route => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname.slice('/api/v1'.length);
    if (endpoint === '/me') return route.fulfill({json: {id: role, name: '测试账号', role, csrf_token: csrfToken}});
    if (!endpoint.startsWith('/teacher-agent/')) return route.fulfill({json: []});
    if (request.method() === 'GET') {
      reads.push(endpoint);
      if (endpoint.endsWith('/conversations')) return route.fulfill({json: created ? [summary()] : []});
      if (faults.failRead) return route.fulfill({status: 404, json: {detail: '记录不可访问'}});
      if (endpoint.includes('/runs/')) return route.fulfill({json: results.flat().find(item => endpoint.endsWith('/' + item.query_run_id))});
      if (endpoint === conversationDetail && faults.detailGate) await faults.detailGate;
      const detail = {conversation: summary(), turns: turns.map(turn => ({...turn, analysis: null,
        access_revoked: faults.revoked, run_ids: faults.revoked ? [] : turn.run_ids})),
        latest_result: faults.revoked ? null : results.at(-1)?.at(-1), latest_results: faults.revoked ? [] : results.at(-1)};
      return route.fulfill({json: payloads.detail?.(detail, results.at(-1)) ?? detail});
    }
    const body = request.postDataJSON();
    writes.push({endpoint, body, headers: request.headers()});
    if (endpoint.endsWith('/conversations')) {
      created = true;
      return route.fulfill({status: 201, json: summary()});
    }
    const key = request.headers()['idempotency-key'];
    if (receipts.has(key)) return route.fulfill({json: receipts.get(key)});
    const batch = turns.length === 0 ? [run(firstRun, '总体统计', 5), run(secondRun, '已发表统计', 3)] :
      [run('r' + (turns.length + 2), '后续查询', 1)];
    const turn = {id: 't' + (turns.length + 1), turn_index: turns.length + 1, created_at: stamp,
      user_message: body.input.label || '论文分析', run_ids: batch.map(item => item.query_run_id)};
    turns.push(turn);
    results.push(batch);
    const reply = {turn, conversation_lock_version: turns.length,
      analysis: turns.length === 1 ? analysis : null, result: batch.at(-1),
      ...(turns.length === 2 ? {analysis_notice: notice} : {results: batch})};
    const response = payloads.turn?.(reply) ?? reply;
    receipts.set(key, response);
    return faults.loseReply ? route.abort() : route.fulfill({json: response});
  });

  const panel = page.getByRole('dialog', {name: 'InnoGrad Agent 对话'});
  const waitForWorkspace = () =>
    page.getByRole('button', {name: entry === '/' ? '退出' : '当前账号与系统设置', exact: true}).waitFor();
  const openAgent = async () => {
    await waitForWorkspace();
    await page.getByRole('button', {name: '打开 Agent 助手', exact: true}).click();
    await panel.waitFor();
  };
  const send = label => panel.getByRole('button', {name: label, exact: true}).click();
  await page.goto(origin + entry);
  await waitForWorkspace();
  return {page, panel, openAgent, send, errors, reads, writes, turns, results, faults};
}

for (const [scenario, resultList, olderRunIds, expected, expectedRuns] of [
  ['missing result lists fall back to the legacy result', () => undefined, undefined, ['已发表统计'], [secondRun]],
  ['explicit empty result lists override the legacy result', () => [], [], [], []],
  ['duplicate runs keep their first card in backend order',
    ([overview, published]) => [published, overview,
      {...published, summary: {...published.summary, headline: '重复结果'}}],
    [secondRun, firstRun, secondRun], ['已发表统计', '总体统计'], [secondRun, firstRun]]
]) {
  test(`#39 ${scenario} on submission, reload and older replay`, async testContext => {
    const {page, panel, openAgent, send, reads, errors} = await openWorkspace(testContext, 'teacher', '/', {
      turn: reply => reply.turn.turn_index === 1 ? {...reply, results: resultList(reply.results),
        turn: {...reply.turn, run_id: secondRun, run_ids: undefined}} : reply,
      detail: detail => {
        const firstIsLatest = detail.turns.length === 1;
        return {...detail,
          latest_results: firstIsLatest ? resultList(detail.latest_results) : detail.latest_results,
          turns: detail.turns.map(turn => turn.turn_index === 1 ?
            {...turn, run_id: secondRun, run_ids: firstIsLatest ? undefined : olderRunIds} : turn)};
      }
    });
    const firstTurn = panel.locator('article').first();
    const secondTurn = panel.getByRole('heading', {name: '第 2 轮', exact: true});
    const headlines = firstTurn.locator('.agent-result h4');
    const replay = firstTurn.getByRole('button', {name: '查看本轮结果', exact: true});
    const visible = async () => ({cards: await headlines.allTextContents(), replay: await replay.count()});
    await openAgent();
    await panel.getByLabel('你的问题').fill('查看论文结果');
    await send('发送问题');
    await firstTurn.waitFor();
    const submitted = await visible();
    await page.reload();
    await openAgent();
    await firstTurn.waitFor();
    const reloaded = await visible();
    await panel.getByLabel('你的问题').fill('再看后续论文');
    await send('发送追问');
    await secondTurn.waitFor();
    await page.reload();
    await openAgent();
    await secondTurn.waitFor();
    const older = await visible();
    if (expectedRuns.length) {
      await replay.click();
      await firstTurn.getByRole('heading', {name: expected[0], exact: true}).waitFor();
    }
    const replayed = await visible();
    const loaded = {cards: expected, replay: 0};
    assert.deepEqual({submitted, reloaded, older, replayed}, {
      submitted: loaded, reloaded: loaded, older: {cards: [], replay: Number(expectedRuns.length > 0)}, replayed: loaded
    });
    assert.deepEqual(reads.filter(endpoint => endpoint.includes('/runs/')).sort(),
      expectedRuns.map(id => '/teacher-agent/runs/' + id).sort());
    assert.deepEqual(errors, []);
  });
}

test('#39 card prompts and authorized turn choices survive reload and disappear on revocation', async testContext => {
  const studentName = '示例学生';
  const prompt = {
    message: '有两位同名学生，请明确选择。',
    suggestions: ['请补充年级或专业。'],
    student_candidates: [
      {student_id: 'stu-1', student_name: studentName, year: '2024', major: '软件工程', degree: 'master'},
      {student_id: 'stu-2', student_name: studentName, year: '2025', major: '计算机科学', degree: 'doctoral'}
    ]
  };
  const cardPrompt = {message: '论文统计需要补充发表状态。'};
  const withPrompts = ([overview, published]) => [
    {...overview, clarification: prompt},
    {...published, clarification: cardPrompt}
  ];
  const {page, panel, openAgent, send, errors, reads, faults} = await openWorkspace(testContext, 'teacher', '/', {
    turn: reply => ({...reply, turn: {...reply.turn, clarification: prompt}, results: withPrompts(reply.results)}),
    detail: (detail, batch) => ({...detail,
      turns: detail.turns.map(turn => ({...turn, clarification: prompt, run_id: secondRun})),
      latest_result: batch.at(-1), latest_results: withPrompts(batch)})
  });
  const expected = [
    '总体统计', '已发表统计', cardPrompt.message, prompt.message, ...prompt.suggestions,
    `${studentName} · 2024 · 软件工程`, `${studentName} · 2025 · 计算机科学`
  ];
  const visibleCounts = () => Promise.all(expected.map(text => panel.getByText(text).count()));
  await openAgent();
  await panel.getByLabel('你的问题').fill(`先统计已发表论文，再看${studentName}的论文`);
  await send('发送问题');
  await panel.getByRole('heading', {name: '已发表统计', exact: true}).waitFor();
  const submitted = await visibleCounts();
  await page.reload();
  await openAgent();
  await panel.getByRole('heading', {name: '已发表统计', exact: true}).waitFor();
  const reloaded = await visibleCounts();

  faults.revoked = true;
  await page.reload();
  await openAgent();
  await panel.getByText('查询范围已变更，本轮内容不可查看。', {exact: true}).waitFor();
  assert.deepEqual(await visibleCounts(), expected.map(() => 0));
  assert.equal(await panel.getByRole('heading', {level: 3}).count(), 0);
  assert.equal(await panel.getByRole('link').count(), 0);
  assert.equal(await panel.getByRole('button', {name: '查看本轮结果'}).count(), 0);
  assert.deepEqual(reads.filter(endpoint => endpoint.includes('/runs/')), []);

  const visibleOnce = expected.map(() => 1);
  assert.deepEqual({submitted, reloaded}, {submitted: visibleOnce, reloaded: visibleOnce});
  assert.deepEqual(errors, []);
});

test('#39 clarification-only legacy envelopes show one prompt and no result cards', async testContext => {
  const prompt = {message: '请补充要查询的年份。'};
  const result = {status: 'clarification_needed', query_run_id: null, clarification: prompt};
  const {page, panel, openAgent, send, errors} = await openWorkspace(testContext, 'teacher', '/', {
    turn: reply => ({...reply, turn: {...reply.turn, run_ids: []}, result, results: []}),
    detail: detail => ({...detail, turns: detail.turns.map(turn => ({...turn, run_ids: [], clarification: prompt})),
      latest_result: result, latest_results: []})
  });
  const firstTurn = panel.getByRole('heading', {name: '第 1 轮', exact: true});
  const counts = async () => [
    await panel.getByText(prompt.message, {exact: true}).count(),
    await panel.locator('.agent-result').count()
  ];
  await openAgent();
  await panel.getByLabel('你的问题').fill('查询论文');
  await send('发送问题');
  await firstTurn.waitFor();
  const submitted = await counts();
  await page.reload();
  await openAgent();
  await firstTurn.waitFor();
  const reloaded = await counts();
  assert.deepEqual({submitted, reloaded}, {submitted: [1, 0], reloaded: [1, 0]});
  assert.deepEqual(errors, []);
});

test('teacher uses the floating workspace Agent for questions, drills, evidence and scope-checked history', async testContext => {
  const {page, panel, openAgent, send, errors, reads, writes, turns, faults} =
    await openWorkspace(testContext, 'teacher', '/prototype/');
  await openAgent();
  const workspaceHash = new URL(page.url()).hash;
  await panel.getByLabel('你的问题').fill('今年论文情况如何？');
  await send('发送问题');
  await panel.getByRole('heading', {name: '已发表统计'}).waitFor();
  assert.deepEqual(await panel.locator('.agent-result h4').allTextContents(), ['总体统计', '已发表统计']);
  assert.equal(await panel.locator('.agent-analysis').textContent(), analysis);
  assert.equal(await panel.locator('.agent-analysis b').count(), 0);
  assert.equal(await panel.getByRole('heading', {name: '今年论文情况如何？'}).count(), 1);
  assert.equal(await panel.locator('.agent-analysis a').count(), 2);
  for (const [id, headline] of [[firstRun, '总体统计'], [secondRun, '已发表统计']]) {
    const citation = panel.getByRole('link', {name: `[${id}]`, exact: true});
    const fragment = await citation.getAttribute('href');
    assert.ok(fragment.startsWith('#'));
    await citation.click();
    const target = panel.locator(fragment);
    assert.equal(await target.getByRole('heading').textContent(), headline);
    assert.equal(await target.evaluate(node => node === node.getRootNode().activeElement), true);
    assert.equal(new URL(page.url()).hash, workspaceHash);
  }
  await panel.locator('summary').last().click();
  assert.equal(await panel.getByRole('link', {name: '证明.pdf'}).getAttribute('href'), '/api/v1/files/f-1/download');
  assert.equal(await panel.getByText('无效地址').count(), 0);
  await send('刷新对话');
  await panel.getByRole('heading', {name: '已发表统计'}).waitFor();
  assert.deepEqual(await panel.locator('.agent-result h4').allTextContents(), ['总体统计', '已发表统计']);
  assert.equal(await panel.locator('.agent-analysis').count(), 0);
  assert.equal(await panel.getByRole('heading', {name: '今年论文情况如何？'}).count(), 0);
  assert.equal(await panel.getByRole('heading', {name: '论文分析'}).count(), 1);
  await send('涉及学生 5 人');
  await panel.getByRole('heading', {name: '第 2 轮'}).waitFor();
  await panel.getByRole('heading', {name: '后续查询'}).waitFor();
  const secondTurn = panel.locator('article').nth(1);
  assert.equal(await secondTurn.getByRole('heading', {name: '系统说明'}).count(), 1);
  assert.equal(await secondTurn.getByText(notice, {exact: true}).count(), 1);
  assert.equal(await secondTurn.getByRole('heading', {name: 'Pi 分析'}).count(), 0);
  await send('刷新对话');
  await panel.getByRole('heading', {name: '后续查询'}).waitFor();
  assert.equal(await panel.getByText(notice, {exact: true}).count(), 0);
  assert.deepEqual(writes.at(-1).body, {expected_lock_version: 1,
    input: {mode: 'drilldown_patch', parent_run_id: firstRun, patch, label: '涉及学生 5 人'}});
  await panel.getByLabel('你的问题').fill('只看最近提交的论文');
  faults.loseReply = true;
  await send('发送追问');
  await panel.getByText(/无法连接服务器/).waitFor();
  assert.equal(await panel.getByLabel('你的问题').inputValue(), '只看最近提交的论文');
  faults.loseReply = false;
  await send('发送追问');
  await panel.getByRole('heading', {name: '第 3 轮'}).waitFor();
  const question = panel.getByRole('textbox', {name: '你的问题'});
  await question.and(panel.locator(':enabled')).waitFor();
  await panel.getByRole('heading', {name: '只看最近提交的论文'}).waitFor();
  assert.equal(await question.inputValue(), '');
  assert.equal(turns.length, 3);
  assert.deepEqual(writes.at(-1).body, {expected_lock_version: 2,
    input: {mode: 'natural_language', message: '只看最近提交的论文'}});
  assert.equal(writes.length, 5);
  assert.ok(writes.every(write => write.headers['x-csrf-token'] === csrfToken && write.headers['idempotency-key']));
  assert.equal(new Set(writes.map(write => write.headers['idempotency-key'])).size, 4);
  assert.equal(writes.at(-1).headers['idempotency-key'], writes.at(-2).headers['idempotency-key']);
  await page.reload();
  await openAgent();
  await panel.getByRole('heading', {name: '后续查询'}).waitFor();
  assert.equal(await panel.locator('.agent-analysis').count(), 0);
  await panel.getByRole('button', {name: '查看本轮结果'}).first().click();
  await panel.getByRole('heading', {name: '总体统计'}).waitFor();
  assert.deepEqual(reads.filter(endpoint => endpoint.includes('/runs/')).sort(),
    [firstRun, secondRun].map(id => '/teacher-agent/runs/' + id).sort());
  await send('涉及学生 3 人');
  await panel.getByRole('heading', {name: '第 4 轮'}).waitFor();
  assert.deepEqual(writes.at(-1).body, {expected_lock_version: 3,
    input: {mode: 'drilldown_patch', parent_run_id: secondRun, patch, label: '涉及学生 3 人'}});
  await page.setViewportSize({width: 390, height: 844});
  assert.ok(await panel.evaluate(node => node.getBoundingClientRect().right <= window.innerWidth));
  faults.revoked = true;
  await send('刷新对话');
  await panel.getByText('查询范围已变更，本轮内容不可查看。').first().waitFor();
  assert.equal(await panel.locator('.agent-result, a, .agent-analysis').count(), 0);
  assert.equal(await panel.getByText('今年论文情况如何？').count(), 0);
  faults.failRead = true;
  await send('刷新对话');
  await panel.getByText('记录不可访问').waitFor();
  assert.equal(await panel.locator('article').count(), 0);
  assert.deepEqual(errors, []);
});

test('manager can ask, drill and replay from the floating Agent on the Vite root', async testContext => {
  const {page, panel, openAgent, send, errors, reads, writes} = await openWorkspace(testContext, 'manager', '/');
  await openAgent();
  await panel.getByLabel('你的问题').fill('查看论文成果统计');
  await send('发送问题');
  await panel.getByRole('heading', {name: '已发表统计'}).waitFor();
  assert.deepEqual(writes.at(-1).body, {expected_lock_version: 0,
    input: {mode: 'natural_language', message: '查看论文成果统计'}});
  await send('涉及学生 3 人');
  await panel.getByRole('heading', {name: '后续查询'}).waitFor();
  assert.deepEqual(writes.at(-1).body, {expected_lock_version: 1,
    input: {mode: 'drilldown_patch', parent_run_id: secondRun, patch, label: '涉及学生 3 人'}});
  await page.reload();
  await openAgent();
  await send('查看本轮结果');
  await panel.getByRole('heading', {name: '总体统计'}).waitFor();
  await panel.getByRole('heading', {name: '已发表统计'}).waitFor();
  assert.deepEqual(reads.filter(endpoint => endpoint.includes('/runs/')).sort(),
    [firstRun, secondRun].map(id => '/teacher-agent/runs/' + id).sort());
  assert.deepEqual(errors, []);
});

test('refreshing the paper Agent page updates results and clears them when access is revoked', async testContext => {
  const {page, panel, send, errors, results, faults} = await openWorkspace(testContext, 'teacher', '/prototype/');
  await page.setViewportSize({width: 1280, height: 720});
  await page.getByRole('button', {name: 'Agent 论文问答'}).click();
  await panel.getByLabel('你的问题').fill('刷新前的论文查询');
  await send('发送问题');
  await panel.getByRole('heading', {name: '已发表统计'}).waitFor();
  assert.equal(new URL(page.url()).hash, '#teacher-agent');

  const refreshPage = page.getByRole('button', {name: '刷新当前页面', exact: true});
  results[0][1].summary.headline = '刷新后的论文统计';
  await refreshPage.click();
  await panel.getByRole('heading', {name: '刷新后的论文统计'}).waitFor();
  assert.equal(await panel.getByRole('heading', {name: '已发表统计'}).count(), 0);

  faults.revoked = true;
  await refreshPage.click();
  await panel.getByText('查询范围已变更，本轮内容不可查看。').waitFor();
  assert.equal(await panel.getByRole('heading', {name: /论文统计|总体统计|刷新前的论文查询/}).count(), 0);
  assert.equal(await panel.getByRole('link').count(), 0);
  assert.deepEqual(errors, []);
});

for (const closeThrough of ['navigation', 'collapse']) {
  test(`reopening paper Agent after ${closeThrough} hides old cards until access is checked`, async testContext => {
    const {page, panel, openAgent, send, errors, faults} = await openWorkspace(testContext, 'teacher', '/prototype/');
    const paperAgent = page.getByRole('button', {name: 'Agent 论文问答'});
    await paperAgent.click();
    await panel.getByLabel('你的问题').fill('授权变化前的论文查询');
    await send('发送问题');
    const oldData = panel.getByRole('heading', {name: /已发表统计|总体统计|授权变化前的论文查询/});
    await panel.getByRole('heading', {name: '已发表统计'}).waitFor();

    const leaveThroughNavigation = closeThrough === 'navigation';
    if (leaveThroughNavigation) {
      await page.getByRole('button', {name: '我的首页', exact: true}).click();
    } else {
      await send('收起对话');
    }
    await panel.waitFor({state: 'hidden'});

    faults.revoked = true;
    let releaseDetail;
    faults.detailGate = new Promise(resolve => { releaseDetail = resolve; });
    try {
      await Promise.all([
        page.waitForRequest(request => request.method() === 'GET' &&
          request.url() === `${origin}/api/v1${conversationDetail}`, {timeout: 4000}),
        leaveThroughNavigation ? paperAgent.click() : openAgent()
      ]);
      await panel.waitFor();
      assert.equal(await oldData.count(), 0);
      assert.equal(await panel.getByRole('link').count(), 0);
    } finally {
      releaseDetail();
    }
    await panel.getByText('查询范围已变更，本轮内容不可查看。').waitFor();
    assert.equal(await oldData.count(), 0);
    assert.equal(await panel.getByRole('link').count(), 0);
    assert.deepEqual(errors, []);
  });
}

for (const entry of ['/', '/prototype/']) {
  for (const role of ['student', 'operator']) {
    test(`${role} on ${entry} can use preset guides without querying Agent data`, async testContext => {
      const {page, panel, openAgent, send, errors, reads, writes} = await openWorkspace(testContext, role, entry);
      await openAgent();
      assert.equal(await page.getByRole('button', {name: 'Agent 论文问答'}).count(), 0);
      await panel.getByText('使用指引模式 · AI 对话服务暂未接入', {exact: true}).waitFor();
      for (const label of ['如何提交论文材料？', '在哪里查看审核进度？', '如何查看我的培养任务？']) {
        await panel.getByRole('button', {name: label}).waitFor();
      }
      await panel.getByRole('button', {name: /如何提交论文材料/}).click();
      await panel.getByText(/新建论文工作稿/).waitFor();
      await panel.getByLabel('输入消息').fill('查询我的个人数据');
      await send('发送消息');
      await panel.getByText(/无法查询个人数据或执行操作/).waitFor();
      assert.equal(await panel.getByRole('group', {name: '论文查询对话'}).count(), 0);
      assert.equal(await panel.getByRole('link').count(), 0);
      assert.deepEqual(reads, []);
      assert.deepEqual(writes, []);
      assert.deepEqual(errors, []);
    });
  }
}
