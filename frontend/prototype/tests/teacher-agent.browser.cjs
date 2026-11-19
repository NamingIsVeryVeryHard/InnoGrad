const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');

test('workspace questions, drills, evidence and scope-checked history', async () => {
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({serviceWorkers: 'block'});
    const page = await context.newPage();
    page.setDefaultTimeout(4000);
    const errors = [], writes = [], reads = [];
    page.on('pageerror', error => errors.push(error.message));
    let role = 'teacher', created = false, revoked = false, failRead = false, loseReply = false;
    const receipts = new Map();
    const turns = [], results = [];
    const stamp = '2026-11-19T08:00:00Z';
    const firstRun = '62b00623-40e9-4856-a1eb-ed490e93912a';
    const secondRun = '174e0b06-65e3-43f3-86a5-892a3ff35628';
    const analysis = `先统计论文 [${firstRun}]，再查看名单 [${secondRun}]。\n<b>分析原文</b> [00000000-0000-4000-8000-000000000000]`;
    const notice = '分析原文中的 <b>数值</b> 未能核实，请查看查询结果。';
    const patch = {operation: 'list', group_by: [], include: ['items', 'sources']};
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
    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== 'http://localhost:8213') {
        errors.push(`External request: ${url.origin}`);
        return route.abort();
      }
      if (url.pathname.startsWith('/prototype/')) {
        const file = url.pathname.slice('/prototype/'.length) || 'index.html';
        return route.fulfill({path: path.join(__dirname, '..', file)});
      }
      const endpoint = url.pathname.replace('/api/v1', '');
      if (endpoint === '/me') return route.fulfill({json: {id: role, name: '测试账号', role, csrf_token: 'fixture-csrf'}});
      if (!endpoint.startsWith('/teacher-agent/')) return route.fulfill({json: []});
      if (request.method() === 'GET') {
        reads.push(endpoint);
        if (endpoint.endsWith('/conversations')) return route.fulfill({json: created ? [summary()] : []});
        if (failRead) return route.fulfill({status: 404, json: {detail: '记录不可访问'}});
        if (endpoint.includes('/runs/')) return route.fulfill({json: results.flat().find(item => endpoint.endsWith('/' + item.query_run_id))});
        return route.fulfill({json: {conversation: summary(), turns: turns.map(turn => ({...turn, analysis: null,
          access_revoked: revoked, run_ids: revoked ? [] : turn.run_ids})),
          latest_result: revoked ? null : results.at(-1)?.at(-1), latest_results: revoked ? [] : results.at(-1)}});
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
      receipts.set(key, reply);
      return loseReply ? route.abort() : route.fulfill({json: reply});
    });

    await page.goto('http://localhost:8213/prototype/');
    await page.getByRole('button', {name: 'Agent 论文问答'}).click();
    const panel = page.locator('#agent-conversation');
    const send = label => panel.getByRole('button', {name: label, exact: true}).click();
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
      assert.equal(await page.locator(fragment).locator('h4').textContent(), headline);
      assert.equal(await page.locator(fragment).evaluate(node => node === document.activeElement), true);
      assert.equal(new URL(page.url()).hash, '#teacher-agent');
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
    loseReply = true;
    await send('发送追问');
    await panel.getByText(/无法连接服务器/).waitFor();
    assert.equal(await panel.getByLabel('你的问题').inputValue(), '只看最近提交的论文');
    loseReply = false;
    await send('发送追问');
    await panel.getByRole('heading', {name: '第 3 轮'}).waitFor();
    await page.waitForFunction(() => document.querySelector('[name=question]').value === '');
    await panel.getByRole('heading', {name: '只看最近提交的论文'}).waitFor();
    assert.equal(turns.length, 3);
    assert.deepEqual(writes.at(-1).body, {expected_lock_version: 2,
      input: {mode: 'natural_language', message: '只看最近提交的论文'}});
    assert.equal(writes.length, 5);
    assert.ok(writes.every(write => write.headers['x-csrf-token'] === 'fixture-csrf' && write.headers['idempotency-key']));
    assert.equal(new Set(writes.map(write => write.headers['idempotency-key'])).size, 4);
    assert.equal(writes.at(-1).headers['idempotency-key'], writes.at(-2).headers['idempotency-key']);
    await page.reload();
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
    revoked = true;
    await page.getByRole('button', {name: '刷新当前页面'}).click();
    await panel.getByText('查询范围已变更，本轮内容不可查看。').first().waitFor();
    assert.equal(await panel.locator('.agent-result, a, .agent-analysis').count(), 0);
    assert.equal(await panel.getByText('今年论文情况如何？').count(), 0);
    failRead = true;
    await send('刷新对话');
    await panel.getByText('记录不可访问').waitFor();
    assert.equal(await panel.locator('article').count(), 0);

    for (role of ['manager', 'student', 'operator']) {
      const before = reads.length;
      await page.reload();
      await page.locator('.campus-current-tab').waitFor();
      if (role === 'manager') {
        await panel.getByRole('button', {name: '刷新对话'}).waitFor();
      } else {
        assert.equal(await page.getByRole('button', {name: 'Agent 论文问答'}).count(), 0);
        assert.equal(await panel.count(), 0);
        assert.equal(reads.length, before);
      }
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
